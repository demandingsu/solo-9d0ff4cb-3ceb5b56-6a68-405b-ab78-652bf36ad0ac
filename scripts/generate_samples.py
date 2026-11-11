#!/usr/bin/env python3
"""生成可离线访问的分页 HTML 公告样例站点。

目录结构（全部为相对链接，无任何外部资源）：
  sample_site/index.html            -> catalog/page_1.html 的副本入口
  sample_site/catalog/page_{1..3}.html
  sample_site/detail/<公告ID>.html

详情页统一结构：
  <table id="announcement-meta"> 中以 <th>字段名</th><td>值</td> 给出：
    招标编号 / 公告类型 / 项目名称 / 发布时间 / 投标截止时间
    依据公告（改期公告）/ 撤回公告（撤回公告）
解析器 app/parser.py 依赖上述结构。
"""
from __future__ import annotations

import html
import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "sample_site")
CATALOG_DIR = os.path.join(SITE, "catalog")
DETAIL_DIR = os.path.join(SITE, "detail")

TYPE_ORIGINAL = "招标公告"
TYPE_RESCHEDULE = "改期公告"
TYPE_WITHDRAWAL = "撤回公告"


@dataclass
class Ann:
    aid: str            # 公告 ID，同时是文件名
    code: str           # 招标编号
    atype: str          # 公告类型
    title: str
    project: str
    published: str      # 发布时间
    deadline: str | None = None
    based_on: str | None = None      # 改期所依据的公告 ID
    withdraws: str | None = None     # 撤回所针对的改期公告 ID


# 18 条公告，按发布时间排序，覆盖：正常链、撤回级联失效、并行改期冲突、部分撤回
ANNOUNCEMENTS: list[Ann] = [
    # T1 ZG-2026-001 市政道路改造 —— 原公告 + 3 次串行改期
    Ann("A001", "ZG-2026-001", TYPE_ORIGINAL, "市政道路改造工程招标公告",
        "市政道路改造工程", "2026-11-01 09:00", "2026-11-20 09:30"),
    # T4 ZG-2026-004 城市路灯节能 —— 原公告 + 2 次改期，撤回第一次改期
    Ann("A004", "ZG-2026-004", TYPE_ORIGINAL, "城市路灯节能改造招标公告",
        "城市路灯节能改造项目", "2026-11-01 10:00", "2026-11-21 09:30"),
    # T2 ZG-2026-002 桥梁加固 —— 原公告 + 3 次改期，撤回第二次改期（级联到第三次）
    Ann("A002", "ZG-2026-002", TYPE_ORIGINAL, "跨河桥梁加固工程招标公告",
        "跨河桥梁加固工程", "2026-11-01 11:00", "2026-11-22 09:30"),
    # T3 ZG-2026-003 排水管网 —— 原公告 + 并行改期冲突
    Ann("A003", "ZG-2026-003", TYPE_ORIGINAL, "排水管网更新工程招标公告",
        "排水管网更新工程", "2026-11-01 12:00", "2026-11-24 09:30"),
    Ann("A005", "ZG-2026-001", TYPE_RESCHEDULE, "市政道路改造工程投标截止时间改期公告（第一次）",
        "市政道路改造工程", "2026-11-05 09:00", "2026-11-25 09:30", based_on="A001"),
    Ann("A006", "ZG-2026-002", TYPE_RESCHEDULE, "跨河桥梁加固工程投标截止时间改期公告（第一次）",
        "跨河桥梁加固工程", "2026-11-05 10:00", "2026-11-26 09:30", based_on="A002"),
    Ann("A007", "ZG-2026-003", TYPE_RESCHEDULE, "排水管网更新工程投标截止时间改期公告（第一次）",
        "排水管网更新工程", "2026-11-05 11:00", "2026-12-01 09:30", based_on="A003"),
    Ann("A008", "ZG-2026-004", TYPE_RESCHEDULE, "城市路灯节能改造投标截止时间改期公告（第一次）",
        "城市路灯节能改造项目", "2026-11-06 09:00", "2026-11-27 09:30", based_on="A004"),
    Ann("A009", "ZG-2026-004", TYPE_RESCHEDULE, "城市路灯节能改造投标截止时间改期公告（第二次）",
        "城市路灯节能改造项目", "2026-11-08 09:00", "2026-12-03 09:30", based_on="A008"),
    Ann("A010", "ZG-2026-001", TYPE_RESCHEDULE, "市政道路改造工程投标截止时间改期公告（第二次）",
        "市政道路改造工程", "2026-11-10 09:00", "2026-11-28 14:00", based_on="A005"),
    Ann("A011", "ZG-2026-002", TYPE_RESCHEDULE, "跨河桥梁加固工程投标截止时间改期公告（第二次）",
        "跨河桥梁加固工程", "2026-11-10 10:00", "2026-11-30 09:30", based_on="A006"),
    Ann("A012", "ZG-2026-003", TYPE_RESCHEDULE, "排水管网更新工程投标截止时间改期公告（第二次·甲）",
        "排水管网更新工程", "2026-11-12 09:00", "2026-12-05 09:30", based_on="A007"),
    Ann("A013", "ZG-2026-003", TYPE_RESCHEDULE, "排水管网更新工程投标截止时间改期公告（第二次·乙）",
        "排水管网更新工程", "2026-11-12 15:00", "2026-12-08 09:30", based_on="A007"),
    Ann("A014", "ZG-2026-004", TYPE_WITHDRAWAL, "城市路灯节能改造改期公告撤回公告",
        "城市路灯节能改造项目", "2026-11-14 09:00", withdraws="A008"),
    Ann("A015", "ZG-2026-001", TYPE_RESCHEDULE, "市政道路改造工程投标截止时间改期公告（第三次）",
        "市政道路改造工程", "2026-11-15 09:00", "2026-12-02 09:30", based_on="A010"),
    Ann("A016", "ZG-2026-002", TYPE_WITHDRAWAL, "跨河桥梁加固工程改期公告撤回公告",
        "跨河桥梁加固工程", "2026-11-16 09:00", withdraws="A011"),
    Ann("A017", "ZG-2026-002", TYPE_RESCHEDULE, "跨河桥梁加固工程投标截止时间改期公告（第三次）",
        "跨河桥梁加固工程", "2026-11-17 09:00", "2026-12-06 09:30", based_on="A011"),
    Ann("A018", "ZG-2026-001", TYPE_RESCHEDULE, "市政道路改造工程投标截止时间改期公告（第四次）",
        "市政道路改造工程", "2026-11-18 09:00", "2026-12-04 09:30", based_on="A015"),
]

PAGE_SIZE = 6

CSS = """
body { font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; margin: 24px; color: #222; }
h1 { font-size: 20px; } table { border-collapse: collapse; width: 720px; margin-top: 12px; }
th, td { border: 1px solid #999; padding: 6px 10px; text-align: left; font-size: 14px; }
th { background: #f0f3f7; width: 130px; }
ul.catalog li { margin: 6px 0; } .pager a { margin-right: 12px; }
.meta-id { color: #666; font-size: 13px; }
"""


def detail_html(a: Ann) -> str:
    rows = [
        ("公告编号", a.aid),
        ("招标编号", a.code),
        ("公告类型", a.atype),
        ("项目名称", a.project),
        ("发布时间", a.published),
    ]
    if a.deadline is not None:
        rows.append(("投标截止时间", a.deadline))
    if a.based_on is not None:
        rows.append(("依据公告", f'<a href="{a.based_on}.html">{a.based_on}</a>'))
    if a.withdraws is not None:
        rows.append(("撤回公告", f'<a href="{a.withdraws}.html">{a.withdraws}</a>'))
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(a.title)}</title>
<style>{CSS}</style>
</head>
<body>
<h1>{html.escape(a.title)}</h1>
<p class="meta-id">公告编号：{a.aid} ｜ 招标编号：{html.escape(a.code)}</p>
<table id="announcement-meta">
{body}
</table>
<p>本页面为离线样例数据，正文内容用于测试公告采集与归集逻辑。</p>
<p><a href="../catalog/page_1.html">返回公告目录</a></p>
</body>
</html>
"""


def catalog_html(page: int, total_pages: int, depth: int = 1) -> str:
    """depth=1 页面位于 catalog/ 下（链接带 ../）；depth=0 位于站点根。"""
    prefix = "../" if depth else ""
    start = (page - 1) * PAGE_SIZE
    items = ANNOUNCEMENTS[start:start + PAGE_SIZE]
    lis = []
    for a in items:
        lis.append(
            '<li><span class="meta-id">'
            f'[{html.escape(a.aid)}] {html.escape(a.published)}</span> '
            f'<a href="{prefix}detail/{a.aid}.html">{html.escape(a.title)}</a>'
            f' （招标编号：{html.escape(a.code)}）</li>'
        )
    pager = []
    for p in range(1, total_pages + 1):
        if p == page:
            pager.append(f"<strong>第 {p} 页</strong>")
        else:
            pager.append(f'<a href="{prefix}catalog/page_{p}.html">第 {p} 页</a>')
    if page < total_pages:
        pager.append(
            f'<a rel="next" href="{prefix}catalog/page_{page + 1}.html">下一页 &raquo;</a>'
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>市政工程招标公告目录 - 第 {page} 页</title>
<style>{CSS}</style>
</head>
<body>
<h1>市政工程招标公告目录（第 {page} / {total_pages} 页）</h1>
<ul class="catalog">
{''.join(lis)}
</ul>
<p class="pager">{''.join(pager)}</p>
</body>
</html>
"""


def main() -> None:
    os.makedirs(CATALOG_DIR, exist_ok=True)
    os.makedirs(DETAIL_DIR, exist_ok=True)
    total_pages = (len(ANNOUNCEMENTS) + PAGE_SIZE - 1) // PAGE_SIZE
    for a in ANNOUNCEMENTS:
        with open(os.path.join(DETAIL_DIR, f"{a.aid}.html"), "w", encoding="utf-8") as f:
            f.write(detail_html(a))
    for p in range(1, total_pages + 1):
        with open(os.path.join(CATALOG_DIR, f"page_{p}.html"), "w", encoding="utf-8") as f:
            f.write(catalog_html(p, total_pages, depth=1))
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(catalog_html(1, total_pages, depth=0))
    print(f"generated {len(ANNOUNCEMENTS)} detail pages, {total_pages} catalog pages under {SITE}")


if __name__ == "__main__":
    main()
