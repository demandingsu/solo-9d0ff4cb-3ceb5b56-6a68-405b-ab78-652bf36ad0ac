"""API 集成测试：基于 FastAPI TestClient + 真实静态样例文件。

采集器对 http://testserver/sample/... 的请求被路由到本地样例 HTML，
完整走“分页抓取 -> 详情解析 -> 归集 -> 存储”流程。
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

SITE = config.SAMPLE_DIR
CATALOG_URL = "http://testserver/sample/catalog/page_1.html"


def _sample_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if not path.startswith("/sample/"):
        return httpx.Response(404, text="not found")
    rel = path[len("/sample/"):]
    f = (SITE / rel).resolve()
    if not str(f).startswith(str(SITE.resolve())) or not f.is_file():
        return httpx.Response(404, text="not found")
    return httpx.Response(
        200,
        content=f.read_bytes(),
        headers={"content-type": "text/html; charset=utf-8"},
    )


# 可在单个测试中替换的请求处理器，transport 始终保持同一个
_HANDLER = {"fn": _sample_handler}


def _dispatch(request: httpx.Request) -> httpx.Response:
    return _HANDLER["fn"](request)


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    # 每个测试使用独立存储文件，互不污染
    monkeypatch.setattr(config, "STORE_PATH", tmp_path / "store.json")
    from app import storage
    monkeypatch.setattr(storage, "store", storage.Store(config.STORE_PATH))
    from app import main
    monkeypatch.setattr(main, "store", storage.Store(config.STORE_PATH))

    _HANDLER["fn"] = _sample_handler
    transport = httpx.MockTransport(_dispatch)
    real_async_client = httpx.AsyncClient

    class PatchedAsyncClient(real_async_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedAsyncClient)
    return TestClient(app)


def test_full_collect_and_query_flow(client):
    resp = client.post("/api/collect", json={"catalog_url": CATALOG_URL})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_pages"] == 3
    assert body["total_announcements"] == 18
    assert body["replaced_previous"] is False

    # 静态样例页面本身可离线访问
    page = client.get("/sample/catalog/page_1.html")
    assert page.status_code == 200
    assert "招标公告目录" in page.text
    detail = client.get("/sample/detail/A001.html")
    assert detail.status_code == 200
    assert 'id="announcement-meta"' in detail.text

    summaries = client.get("/api/tenders").json()
    by_code = {s["tender_code"]: s for s in summaries}
    assert by_code["ZG-2026-001"]["current_deadline"] == "2026-12-04 09:30"
    assert by_code["ZG-2026-003"]["status"] == "conflict"
    assert by_code["ZG-2026-003"]["current_deadline"] is None
    conflict_codes = {c["announcement_id"] for c in by_code["ZG-2026-003"]["conflict"]}
    assert conflict_codes == {"A012", "A013"}

    t2 = client.get("/api/tenders/ZG-2026-002").json()
    assert t2["current_deadline"] == "2026-11-26 09:30"
    a011 = next(a for a in t2["announcements"] if a["announcement_id"] == "A011")
    a017 = next(a for a in t2["announcements"] if a["announcement_id"] == "A017")
    assert a011["valid"] is False and "撤回" in a011["invalid_reason"]
    assert a017["valid"] is False and "A011" in a017["invalid_reason"]
    # 每条公告都有来源链接
    assert all(a["source_url"].startswith("http://testserver/sample/detail/")
               for a in t2["announcements"])


def test_query_before_collect_returns_404(client):
    assert client.get("/api/tenders").status_code == 404


def test_recollect_replaces_old_result(client):
    r1 = client.post("/api/collect", json={"catalog_url": CATALOG_URL})
    assert r1.json()["replaced_previous"] is False
    r2 = client.post("/api/collect", json={"catalog_url": CATALOG_URL})
    assert r2.status_code == 200
    assert r2.json()["replaced_previous"] is True
    assert client.get("/api/raw").json()["total_announcements"] == 18


def test_failed_crawl_keeps_previous_result(client):
    ok = client.post("/api/collect", json={"catalog_url": CATALOG_URL})
    assert ok.status_code == 200

    def failing_handler(request: httpx.Request) -> httpx.Response:
        if "page_2" in request.url.path:
            raise httpx.ConnectError("simulated network outage")
        return _sample_handler(request)

    _HANDLER["fn"] = failing_handler
    try:
        bad = client.post("/api/collect", json={"catalog_url": CATALOG_URL})
        assert bad.status_code == 502
        assert bad.json()["detail"]["previous_result_retained"] is True
    finally:
        _HANDLER["fn"] = _sample_handler

    # 旧结果原样可查
    raw = client.get("/api/raw").json()
    assert raw["total_announcements"] == 18
    assert client.get("/api/tenders/ZG-2026-001").json()["current_deadline"] == \
        "2026-12-04 09:30"


def test_store_file_is_valid_json(client):
    client.post("/api/collect", json={"catalog_url": CATALOG_URL})
    data = json.loads(Path(config.STORE_PATH).read_text(encoding="utf-8"))
    assert data["total_announcements"] == 18
