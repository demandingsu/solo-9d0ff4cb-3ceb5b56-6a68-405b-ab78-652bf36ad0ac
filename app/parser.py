"""HTML 解析器，针对与内置样例结构一致的公告页面。

目录页约定：
  - 每条详情链接位于 ul.catalog 的 li 内（任意 <a> 均视为详情入口）
  - 下一页：a[rel=next]
详情页约定：
  - table#announcement-meta 内 th/td 键值对
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import Announcement, AnnouncementType

VALID_TYPES = {t.value for t in AnnouncementType}


class ParseError(Exception):
    """页面结构不符合约定时抛出。"""


def _meta_table(soup: BeautifulSoup) -> dict[str, str]:
    table = soup.find("table", id="announcement-meta")
    if table is None:
        raise ParseError("详情页缺少 table#announcement-meta")
    meta: dict[str, str] = {}
    for tr in table.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is None or td is None:
            continue
        meta[th.get_text(strip=True)] = td.get_text(strip=True)
    return meta


def parse_detail(html_text: str, url: str) -> Announcement:
    soup = BeautifulSoup(html_text, "html.parser")
    meta = _meta_table(soup)

    required = ["公告编号", "招标编号", "公告类型", "项目名称", "发布时间"]
    missing = [k for k in required if not meta.get(k)]
    if missing:
        raise ParseError(f"详情页 {url} 缺少必填字段: {', '.join(missing)}")

    atype = meta["公告类型"]
    if atype not in VALID_TYPES:
        raise ParseError(f"详情页 {url} 公告类型无法识别: {atype}")

    title = (soup.title.get_text(strip=True) if soup.title else "") or meta.get("项目名称", "")
    deadline = meta.get("投标截止时间") or None
    based_on = meta.get("依据公告") or None
    withdraws = meta.get("撤回公告") or None

    if atype == AnnouncementType.RESCHEDULE.value and not based_on:
        raise ParseError(f"改期公告 {url} 缺少依据公告")
    if atype == AnnouncementType.WITHDRAWAL.value and not withdraws:
        raise ParseError(f"撤回公告 {url} 缺少撤回公告目标")
    if atype == AnnouncementType.RESCHEDULE.value and not deadline:
        raise ParseError(f"改期公告 {url} 缺少投标截止时间")

    return Announcement(
        announcement_id=meta["公告编号"],
        tender_code=meta["招标编号"],
        project_name=meta["项目名称"],
        type=AnnouncementType(atype),
        title=title,
        published_at=meta["发布时间"],
        deadline=deadline,
        based_on_id=based_on,
        withdraws_id=withdraws,
        source_url=url,
    )


def parse_catalog(html_text: str, url: str) -> tuple[list[str], Optional[str]]:
    """返回 (详情页绝对 URL 列表, 下一页绝对 URL 或 None)。"""
    soup = BeautifulSoup(html_text, "html.parser")
    catalog = soup.find("ul", class_="catalog")
    if catalog is None:
        raise ParseError(f"目录页 {url} 缺少 ul.catalog")

    detail_urls: list[str] = []
    for a in catalog.find_all("a", href=True):
        detail_urls.append(urljoin(url, a["href"]))
    if not detail_urls:
        raise ParseError(f"目录页 {url} 未包含任何详情链接")

    next_page = None
    nxt = soup.find("a", rel=True, href=True)
    # rel 可能被解析为列表，next 链接以 rel="next" 标识
    if nxt is not None and "next" in (nxt.get("rel") or []):
        next_page = urljoin(url, nxt["href"])
    return detail_urls, next_page
