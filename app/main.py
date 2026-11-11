"""FastAPI 入口：采集与查询接口 + 离线样例静态站点。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .chain import build_all, build_tender_detail, group_by_tender
from .crawler import CrawlError, Crawler
from .models import (
    CollectRequest,
    CollectResponse,
    CollectResult,
    TenderDetail,
    TenderSummary,
)
from .storage import store

app = FastAPI(
    title="市政工程投标公告采集 API",
    version="1.0.0",
    description="沿分页采集公告详情，按招标编号归集原公告/改期/撤回，输出有效截止时间链。",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/collect", response_model=CollectResponse)
async def collect(req: CollectRequest) -> CollectResponse:
    """触发一次完整采集。成功则整体替换旧结果；失败保留旧结果。"""
    previous = await store.load()
    try:
        announcements, total_pages = await Crawler().collect(str(req.catalog_url))
    except CrawlError as exc:
        # 不触碰 store：旧结果完整保留
        raise HTTPException(
            status_code=502,
            detail={
                "error": str(exc),
                "previous_result_retained": previous is not None,
                "message": "采集失败，已保留上一次成功采集的结果"
                if previous is not None
                else "采集失败，且不存在历史结果",
            },
        ) from exc

    result = CollectResult(
        catalog_url=str(req.catalog_url),
        total_pages=total_pages,
        total_announcements=len(announcements),
        collected_at=Crawler.now_iso(),
        announcements=announcements,
    )
    await store.replace(result)
    return CollectResponse(
        status="collected",
        catalog_url=result.catalog_url,
        total_pages=result.total_pages,
        total_announcements=result.total_announcements,
        collected_at=result.collected_at,
        replaced_previous=previous is not None,
    )


async def _require_data() -> CollectResult:
    result = await store.load()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="尚无采集结果，请先调用 POST /api/collect",
        )
    return result


@app.get("/api/tenders", response_model=list[TenderSummary])
async def list_tenders() -> list[TenderSummary]:
    """所有标段的截止时间汇总（含冲突标记）。"""
    result = await _require_data()
    details = build_all(result.announcements)
    return [
        TenderSummary(**d.model_dump(exclude={"announcements"})) for d in details
    ]


@app.get("/api/tenders/{tender_code}", response_model=TenderDetail)
async def get_tender(tender_code: str) -> TenderDetail:
    """单个标段的完整有效公告链（含每条公告的失效原因与来源链接）。"""
    result = await _require_data()
    grouped = group_by_tender(result.announcements)
    items = grouped.get(tender_code)
    if not items:
        raise HTTPException(status_code=404, detail=f"未找到招标编号 {tender_code}")
    return build_tender_detail(tender_code, items)


@app.get("/api/raw")
async def raw_announcements() -> dict:
    """最近一次采集的原始解析结果（便于核对，不做链路口算）。"""
    result = await _require_data()
    return result.model_dump()


# ---- 离线样例站点 ----
@app.get("/sample")
async def sample_index() -> RedirectResponse:
    return RedirectResponse(url="/sample/index.html")


if config.SAMPLE_DIR.exists():
    app.mount(
        "/sample",
        StaticFiles(directory=str(config.SAMPLE_DIR), html=True),
        name="sample",
    )


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(str(config.BASE_DIR / "app" / "index.html"))
