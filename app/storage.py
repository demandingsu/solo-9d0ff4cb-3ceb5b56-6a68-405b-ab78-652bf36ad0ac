"""结果存储：JSON 文件 + 异步锁。

再次采集成功时以完整新结果整体替换旧结果；采集失败时本模块不被触碰，
旧结果自然保留。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from . import config
from .models import CollectResult


class Store:
    def __init__(self, path: Path = config.STORE_PATH) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def replace(self, result: CollectResult) -> None:
        async with self._lock:
            tmp = self.path.with_suffix(".json.tmp")
            # 全量写入临时文件再原子替换，保证旧结果在写入失败时仍可用
            tmp.write_text(
                json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)

    async def load(self) -> CollectResult | None:
        async with self._lock:
            if not self.path.exists():
                return None
            return CollectResult.model_validate(
                json.loads(self.path.read_text(encoding="utf-8"))
            )


store = Store()
