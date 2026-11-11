"""链路归集逻辑单元测试（直接构造公告对象，不依赖网络）。"""
from __future__ import annotations

import pytest

from app.chain import build_all, build_tender_detail, group_by_tender
from app.models import Announcement, AnnouncementType as T

URL = "http://test/detail/{}.html"


def ann(aid, code, atype, published, deadline=None, based=None, withdraws=None):
    return Announcement(
        announcement_id=aid,
        tender_code=code,
        project_name="测试项目",
        type=atype,
        title=f"{aid}-title",
        published_at=published,
        deadline=deadline,
        based_on_id=based,
        withdraws_id=withdraws,
        source_url=URL.format(aid),
    )


def view(detail: dict, aid: str) -> dict:
    return next(a for a in detail["announcements"] if a["announcement_id"] == aid)


def test_serial_reschedule_chain_takes_latest_deadline():
    items = [
        ann("O1", "C1", T.ORIGINAL, "2026-11-01 09:00", "2026-11-20 09:30"),
        ann("R1", "C1", T.RESCHEDULE, "2026-11-05 09:00", "2026-11-25 09:30", based="O1"),
        ann("R2", "C1", T.RESCHEDULE, "2026-11-10 09:00", "2026-11-28 14:00", based="R1"),
        ann("R3", "C1", T.RESCHEDULE, "2026-11-15 09:00", "2026-12-02 09:30", based="R2"),
    ]
    detail = build_tender_detail("C1", items).model_dump()
    assert detail["status"] == "ok"
    assert detail["current_deadline"] == "2026-12-02 09:30"
    assert all(a["valid"] for a in detail["announcements"])
    # 每条改期都注明依据公告
    for a in items[1:]:
        assert a.based_on_id


def test_withdrawal_cascades_to_dependent_reschedules():
    items = [
        ann("O2", "C2", T.ORIGINAL, "2026-11-01 09:00", "2026-11-22 09:30"),
        ann("R1", "C2", T.RESCHEDULE, "2026-11-05 09:00", "2026-11-26 09:30", based="O2"),
        ann("R2", "C2", T.RESCHEDULE, "2026-11-10 09:00", "2026-11-30 09:30", based="R1"),
        ann("W1", "C2", T.WITHDRAWAL, "2026-11-16 09:00", withdraws="R2"),
        ann("R3", "C2", T.RESCHEDULE, "2026-11-17 09:00", "2026-12-06 09:30", based="R2"),
    ]
    detail = build_tender_detail("C2", items).model_dump()
    assert detail["status"] == "ok"
    # R2 被撤回，R3 依赖 R2 级联失效；有效链停在 R1
    assert view(detail, "R2")["valid"] is False
    assert "撤回" in view(detail, "R2")["invalid_reason"]
    assert view(detail, "R3")["valid"] is False
    assert "R2" in view(detail, "R3")["invalid_reason"]
    assert view(detail, "R1")["valid"] is True
    assert view(detail, "W1")["valid"] is True
    assert detail["current_deadline"] == "2026-11-26 09:30"


def test_parallel_reschedules_with_different_deadlines_conflict():
    items = [
        ann("O3", "C3", T.ORIGINAL, "2026-11-01 09:00", "2026-11-24 09:30"),
        ann("R1", "C3", T.RESCHEDULE, "2026-11-05 09:00", "2026-12-01 09:30", based="O3"),
        ann("R2", "C3", T.RESCHEDULE, "2026-11-12 09:00", "2026-12-05 09:30", based="R1"),
        ann("R3", "C3", T.RESCHEDULE, "2026-11-12 15:00", "2026-12-08 09:30", based="R1"),
    ]
    detail = build_tender_detail("C3", items).model_dump()
    assert detail["status"] == "conflict"
    assert detail["current_deadline"] is None
    conflict_ids = {c["announcement_id"] for c in detail["conflict"]}
    assert conflict_ids == {"R2", "R3"}
    # 冲突公告必须带来源链接
    assert all(c["source_url"].startswith("http://test/detail/") for c in detail["conflict"])


def test_parallel_reschedules_with_same_deadline_resolve():
    items = [
        ann("O4", "C4", T.ORIGINAL, "2026-11-01 09:00", "2026-11-21 09:30"),
        ann("R1", "C4", T.RESCHEDULE, "2026-11-06 09:00", "2026-11-27 09:30", based="O4"),
        ann("R2", "C4", T.RESCHEDULE, "2026-11-09 09:00", "2026-12-03 09:30", based="R1"),
        ann("R3", "C4", T.RESCHEDULE, "2026-11-09 15:00", "2026-12-03 09:30", based="R1"),
    ]
    detail = build_tender_detail("C4", items).model_dump()
    assert detail["status"] == "ok"
    assert detail["current_deadline"] == "2026-12-03 09:30"
    assert any("并行改期" in n for n in detail["notes"])


def test_partial_withdrawal_removes_conflict():
    # 撤回并行分支之一后，另一分支继续有效，不再冲突
    items = [
        ann("O5", "C5", T.ORIGINAL, "2026-11-01 09:00", "2026-11-21 09:30"),
        ann("R1", "C5", T.RESCHEDULE, "2026-11-06 09:00", "2026-11-27 09:30", based="O5"),
        ann("R2", "C5", T.RESCHEDULE, "2026-11-08 09:00", "2026-12-03 09:30", based="R1"),
        ann("W1", "C5", T.WITHDRAWAL, "2026-11-14 09:00", withdraws="R1"),
    ]
    detail = build_tender_detail("C5", items).model_dump()
    assert view(detail, "R1")["valid"] is False
    assert view(detail, "R2")["valid"] is False  # 级联
    assert detail["status"] == "ok"
    assert detail["current_deadline"] == "2026-11-21 09:30"


def test_missing_original():
    items = [
        ann("R1", "C6", T.RESCHEDULE, "2026-11-05 09:00", "2026-11-26 09:30", based="O9"),
    ]
    detail = build_tender_detail("C6", items).model_dump()
    assert detail["status"] == "original_missing"
    assert detail["current_deadline"] is None


def test_grouping_and_all_scenarios_on_sample_dataset(sample_announcements):
    grouped = group_by_tender(sample_announcements)
    assert set(grouped) == {"ZG-2026-001", "ZG-2026-002", "ZG-2026-003", "ZG-2026-004"}

    details = {d.tender_code: d for d in build_all(sample_announcements)}

    d1 = details["ZG-2026-001"].model_dump()
    assert d1["status"] == "ok"
    assert d1["current_deadline"] == "2026-12-04 09:30"  # A018 第四次改期

    d2 = details["ZG-2026-002"].model_dump()
    assert d2["status"] == "ok"
    assert d2["current_deadline"] == "2026-11-26 09:30"  # A006（A011 被撤回，A017 级联）
    assert not next(a for a in d2["announcements"] if a["announcement_id"] == "A011")["valid"]
    assert not next(a for a in d2["announcements"] if a["announcement_id"] == "A017")["valid"]

    d3 = details["ZG-2026-003"].model_dump()
    assert d3["status"] == "conflict"
    assert {c["announcement_id"] for c in d3["conflict"]} == {"A012", "A013"}

    d4 = details["ZG-2026-004"].model_dump()
    assert d4["status"] == "ok"
    assert d4["current_deadline"] == "2026-11-21 09:30"  # 回到原公告（A008 撤回，A009 级联）
