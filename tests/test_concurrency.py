"""并发采集发布顺序测试：用可控的完成顺序验证发布规则。

场景一：先发起的慢请求在后发起的请求成功发布之后才完成，迟到的旧结果
        不得覆盖新快照，响应须标明本次未发布。
场景二：后发起的请求抓取失败，先发起且仍在执行的成功请求仍应能发布；
        失败请求不得改写已有快照。
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app import config, main, storage
from app.crawler import CrawlError
from app.models import Announcement, AnnouncementType, CollectResult


def _announcement(aid: str, deadline: str) -> Announcement:
    return Announcement(
        announcement_id=aid,
        tender_code=f"T-{aid}",
        project_name=f"项目-{aid}",
        type=AnnouncementType.ORIGINAL,
        title=f"{aid}-title",
        published_at="2026-11-01 09:00",
        deadline=deadline,
        source_url=f"http://testserver/detail/{aid}.html",
    )


def _result(aid: str, deadline: str) -> CollectResult:
    return CollectResult(
        catalog_url=f"http://testserver/{aid}",
        total_pages=1,
        total_announcements=1,
        collected_at="2026-11-11T00:00:00+00:00",
        announcements=[_announcement(aid, deadline)],
    )


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch) -> storage.Store:
    monkeypatch.setattr(config, "STORE_PATH", tmp_path / "store.json")
    instance = storage.Store(config.STORE_PATH)
    monkeypatch.setattr(storage, "store", instance)
    monkeypatch.setattr(main, "store", instance)
    return instance


class _ControlledCrawler:
    """按调用（即请求）顺序控制每个采集何时完成、成功还是失败。"""

    def __init__(self, results: list[CollectResult | None]) -> None:
        self.results = results
        self.calls: list[str] = []
        self.started = [asyncio.Event() for _ in results]
        self.release = [asyncio.Event() for _ in results]

    async def collect(self, catalog_url: str):
        index = len(self.calls)
        assert index < len(self.results), "超出预期的采集调用次数"
        self.calls.append(catalog_url)
        self.started[index].set()
        await self.release[index].wait()
        result = self.results[index]
        if result is None:
            raise CrawlError("simulated crawl failure")
        return list(result.announcements), result.total_pages


def _start_request(client: httpx.AsyncClient, url: str) -> asyncio.Task:
    return asyncio.create_task(
        client.post("/api/collect", json={"catalog_url": url})
    )


async def _wait_started(controller: _ControlledCrawler, index: int) -> None:
    await asyncio.wait_for(controller.started[index].wait(), timeout=5)


def test_late_earlier_result_cannot_overwrite_newer_published_snapshot(
    isolated_store, monkeypatch
):
    async def scenario() -> None:
        controller = _ControlledCrawler(
            [_result("OLD", "2026-01-10 09:30"), _result("NEW", "2026-02-10 09:30")]
        )
        monkeypatch.setattr(main.Crawler, "collect", controller.collect)

        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            # 先发起“旧”请求（序号 1），确认其已进入采集后再发起“新”请求（序号 2）
            old_task = _start_request(client, "http://testserver/old")
            await _wait_started(controller, 0)
            new_task = _start_request(client, "http://testserver/new")
            await _wait_started(controller, 1)

            # 后发起的“新”请求先完成并成功发布
            controller.release[1].set()
            new_resp = await asyncio.wait_for(new_task, timeout=5)
            assert new_resp.status_code == 200
            new_body = new_resp.json()
            assert new_body["status"] == "collected"
            assert new_body["published"] is True
            assert (await client.get("/api/raw")).json()["announcements"][0][
                "announcement_id"
            ] == "NEW"

            # 迟到的“旧”请求完成：不得覆盖，响应须标明未发布
            controller.release[0].set()
            old_resp = await asyncio.wait_for(old_task, timeout=5)
            assert old_resp.status_code == 200
            old_body = old_resp.json()
            assert old_body["published"] is False
            assert old_body["status"] == "not_published"
            assert old_body["publication_status"] == "not_published"
            assert old_body["message"]

            raw = (await client.get("/api/raw")).json()
            assert raw["announcements"][0]["announcement_id"] == "NEW"
            assert raw["total_announcements"] == 1

        # 磁盘上也只有完整的新快照
        stored = json.loads(isolated_store.path.read_text(encoding="utf-8"))
        assert stored["announcements"][0]["announcement_id"] == "NEW"

    asyncio.run(scenario())


def test_failed_later_request_leaves_store_untouched_and_lets_earlier_publish(
    isolated_store, monkeypatch
):
    baseline = _result("BASE", "2026-12-01 09:30")

    async def scenario() -> None:
        await isolated_store.replace(baseline)

        controller = _ControlledCrawler(
            [_result("OLD", "2026-01-10 09:30"), None]  # 第二次调用模拟失败
        )
        monkeypatch.setattr(main.Crawler, "collect", controller.collect)

        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            old_task = _start_request(client, "http://testserver/old")
            await _wait_started(controller, 0)
            new_task = _start_request(client, "http://testserver/new")
            await _wait_started(controller, 1)

            # 后发起的请求失败：返回 502，且不触碰已有快照
            controller.release[1].set()
            new_resp = await asyncio.wait_for(new_task, timeout=5)
            assert new_resp.status_code == 502
            assert new_resp.json()["detail"]["previous_result_retained"] is True
            raw = (await client.get("/api/raw")).json()
            assert raw["announcements"][0]["announcement_id"] == "BASE"

            # 先发起、仍在执行的请求随后成功完成，应当可以发布
            controller.release[0].set()
            old_resp = await asyncio.wait_for(old_task, timeout=5)
            assert old_resp.status_code == 200
            old_body = old_resp.json()
            assert old_body["published"] is True
            assert old_body["status"] == "collected"
            raw = (await client.get("/api/raw")).json()
            assert raw["announcements"][0]["announcement_id"] == "OLD"

        stored = json.loads(isolated_store.path.read_text(encoding="utf-8"))
        assert stored["announcements"][0]["announcement_id"] == "OLD"

    asyncio.run(scenario())
