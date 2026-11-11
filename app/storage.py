"""结果存储：JSON 文件 + 发布顺序控制。

并发语义（按请求启动顺序判定先后）：

* 服务在每次采集请求**开始时**分配一个单调递增的序号，序号越小表示
  客户端发起得越早。
* 只有抓取完全成功的结果才尝试发布。发布时若已有**更晚发起**的采集
  成功发布过（已发布序号 >= 本请求序号），则本次结果被丢弃，响应明确
  标明“未发布”，不会覆盖较新的快照。
* 抓取失败的请求不参与发布，也不会更新“已发布序号”，因此不会阻塞
  更早发起、仍在执行且最终成功的请求。
* 写入始终是“临时文件 + 原子 rename”，查询只会看到完整快照。

这里使用线程锁而不是 asyncio.Lock：文件读写在当前实现中是同步的，
线程锁可以同时保护来自不同事件循环（例如测试中的多线程 TestClient）
的访问。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from . import config
from .models import CollectResult


class Store:
    def __init__(self, path: Path = config.STORE_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._sequence = 0
        self._last_published_sequence = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write_atomic(self, result: CollectResult) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        # 全量写入临时文件再原子替换，保证旧结果在写入失败时仍可用
        tmp.write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    async def begin_collect(self) -> int:
        """登记一次采集请求，返回其启动序号（越小发起越早）。"""
        with self._lock:
            self._sequence += 1
            return self._sequence

    async def publish(
        self, sequence: int, result: CollectResult
    ) -> tuple[bool, bool]:
        """尝试发布一次成功采集。

        返回 ``(是否发布, 是否替换了已有结果)``。当且仅当不存在更晚发起
        且已成功发布的采集时才会写入；判定与写入在同一把锁内完成。
        """
        with self._lock:
            if sequence <= self._last_published_sequence:
                # 更晚发起的采集已经成功发布，迟到的旧结果不能覆盖它。
                return False, False
            replaced_previous = self.path.exists()
            self._write_atomic(result)
            self._last_published_sequence = sequence
            return True, replaced_previous

    async def replace(self, result: CollectResult) -> None:
        with self._lock:
            self._write_atomic(result)

    async def load(self) -> CollectResult | None:
        with self._lock:
            if not self.path.exists():
                return None
            return CollectResult.model_validate(
                json.loads(self.path.read_text(encoding="utf-8"))
            )


store = Store()
