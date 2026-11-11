"""公告采集器：沿目录分页抓取详情并解析。

任何网络或解析错误都抛出 CrawlError，由上层决定“保留旧结果”。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from . import config
from .models import Announcement
from .parser import ParseError, parse_catalog, parse_detail


class CrawlError(Exception):
    pass


class Crawler:
    def __init__(self) -> None:
        self._sem = asyncio.Semaphore(config.MAX_CONCURRENCY)

    async def _get(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise CrawlError(f"抓取失败 {url}: {exc}") from exc
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            raise CrawlError(f"响应不是 HTML {url} (content-type={ctype})")
        return resp.text

    async def _fetch_detail(self, client: httpx.AsyncClient, url: str) -> Announcement:
        async with self._sem:
            html_text = await self._get(client, url)
        try:
            return parse_detail(html_text, url)
        except ParseError as exc:
            raise CrawlError(str(exc)) from exc

    async def collect(self, catalog_url: str) -> tuple[list[Announcement], int]:
        """沿分页抓取全部详情。返回 (公告列表, 目录页数)。

        全部成功才返回；任一页面失败即抛 CrawlError，不返回部分结果。
        """
        async with httpx.AsyncClient(
            timeout=config.REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": config.USER_AGENT},
        ) as client:
            detail_urls: list[str] = []
            seen_pages: set[str] = set()
            page_url: str | None = catalog_url
            pages = 0

            while page_url is not None:
                if page_url in seen_pages:
                    raise CrawlError(f"目录分页出现循环: {page_url}")
                seen_pages.add(page_url)
                pages += 1
                if pages > config.MAX_PAGES:
                    raise CrawlError(f"目录页数超过上限 {config.MAX_PAGES}，疑似分页异常")

                html_text = await self._get(client, page_url)
                try:
                    urls, page_url = parse_catalog(html_text, page_url)
                except ParseError as exc:
                    raise CrawlError(str(exc)) from exc
                detail_urls.extend(urls)

            # 去重（不同目录页理论上不会重复，保险处理）
            detail_urls = list(dict.fromkeys(detail_urls))
            results = await asyncio.gather(
                *(self._fetch_detail(client, u) for u in detail_urls)
            )

        by_id: dict[str, Announcement] = {}
        for ann in results:
            if ann.announcement_id in by_id:
                raise CrawlError(f"公告编号重复: {ann.announcement_id}")
            by_id[ann.announcement_id] = ann
        return list(by_id.values()), pages

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
