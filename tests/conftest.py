"""pytest 公共夹具。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import Announcement  # noqa: E402
from app.parser import parse_catalog, parse_detail  # noqa: E402

SITE = Path(__file__).resolve().parent.parent / "sample_site"


@pytest.fixture(scope="session")
def sample_announcements() -> list[Announcement]:
    """直接从样例 HTML 解析出的全量公告（与真实采集路径一致的解析逻辑）。"""
    collected: list[Announcement] = []
    page = SITE / "catalog" / "page_1.html"
    base = "http://testserver/sample/catalog/page_1.html"
    seen: set[str] = set()
    while page is not None:
        html_text = page.read_text(encoding="utf-8")
        urls, next_url = parse_catalog(html_text, base)
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            aid = u.rsplit("/", 1)[-1].replace(".html", "")
            detail_html = (SITE / "detail" / f"{aid}.html").read_text(encoding="utf-8")
            collected.append(parse_detail(detail_html, u))
        if next_url is None:
            page = None
        else:
            name = next_url.rsplit("/", 1)[-1]
            page = SITE / "catalog" / name
            base = next_url
    return collected
