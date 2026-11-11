"""Pydantic 数据模型。"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class AnnouncementType(str, Enum):
    ORIGINAL = "招标公告"
    RESCHEDULE = "改期公告"
    WITHDRAWAL = "撤回公告"


class CollectRequest(BaseModel):
    catalog_url: HttpUrl = Field(..., description="公告目录第一页 URL")


class Announcement(BaseModel):
    """采集并解析后的单条公告（原始链路口径，不做失效判断）。"""

    announcement_id: str
    tender_code: str
    project_name: str
    type: AnnouncementType
    title: str
    published_at: str
    deadline: Optional[str] = None
    based_on_id: Optional[str] = None     # 改期公告所依据的公告 ID
    withdraws_id: Optional[str] = None    # 撤回公告所针对的改期公告 ID
    source_url: str


class CollectResult(BaseModel):
    catalog_url: str
    total_pages: int
    total_announcements: int
    collected_at: str
    announcements: list[Announcement]


# ---- 查询侧视图模型 ----

class AnnouncementView(BaseModel):
    announcement_id: str
    type: AnnouncementType
    title: str
    published_at: str
    deadline: Optional[str] = None
    based_on_id: Optional[str] = None
    withdraws_id: Optional[str] = None
    valid: bool = True
    invalid_reason: Optional[str] = None
    source_url: str


class ConflictItem(BaseModel):
    announcement_id: str
    deadline: str
    published_at: str
    source_url: str


class TenderSummary(BaseModel):
    tender_code: str
    project_name: str
    status: str  # ok | conflict | original_missing
    current_deadline: Optional[str] = None
    conflict: Optional[list[ConflictItem]] = None
    notes: list[str] = Field(default_factory=list)


class TenderDetail(TenderSummary):
    announcements: list[AnnouncementView]


class CollectResponse(BaseModel):
    status: str
    catalog_url: str
    total_pages: int
    total_announcements: int
    collected_at: str
    replaced_previous: bool
