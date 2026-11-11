"""按招标编号归集公告，构建有效公告链并计算当前截止时间。

规则：
1. 原公告为链的根；改期公告通过 based_on_id 注明所依据的公告；
   撤回公告通过 withdraws_id 指定被撤回的改期公告。
2. 撤回指定改期后，该改期及其全部后续改期（沿 based_on_id 传递依赖）
   一律失效。
3. 同一有效依据公告下存在多条有效并行改期：
   - 截止时间一致 -> 取该截止时间，附 notes 说明；
   - 截止时间不一致 -> 返回冲突公告，不猜测结果，current_deadline 置空。
4. 原公告缺失（数据不完整）时 status=original_missing。
"""
from __future__ import annotations

from collections import defaultdict

from .models import (
    Announcement,
    AnnouncementType,
    AnnouncementView,
    ConflictItem,
    TenderDetail,
)


def group_by_tender(
    announcements: list[Announcement],
) -> dict[str, list[Announcement]]:
    grouped: dict[str, list[Announcement]] = defaultdict(list)
    for ann in announcements:
        grouped[ann.tender_code].append(ann)
    for items in grouped.values():
        items.sort(key=lambda a: (a.published_at, a.announcement_id))
    return dict(grouped)


def _build_views(
    items: list[Announcement],
) -> tuple[dict[str, AnnouncementView], Announcement | None, list[str]]:
    """构造带 valid/invalid_reason 的视图，并返回原公告与备注。"""
    by_id = {a.announcement_id: a for a in items}
    views: dict[str, AnnouncementView] = {
        a.announcement_id: AnnouncementView(**a.model_dump()) for a in items
    }
    notes: list[str] = []

    original = next(
        (a for a in items if a.type == AnnouncementType.ORIGINAL), None
    )

    # 1) 直接被撤回的改期 -> 失效
    withdrawn_targets: set[str] = set()
    for a in items:
        if a.type != AnnouncementType.WITHDRAWAL:
            continue
        target = a.withdraws_id
        if target not in by_id:
            notes.append(f"撤回公告 {a.announcement_id} 的目标 {target} 不存在，已忽略")
            continue
        if by_id[target].type != AnnouncementType.RESCHEDULE:
            notes.append(
                f"撤回公告 {a.announcement_id} 的目标 {target} 不是改期公告，已忽略"
            )
            continue
        withdrawn_targets.add(target)

    # 2) 沿 based_on_id 做依赖传递：被失效节点的所有后续改期一并失效
    dependents: dict[str, list[str]] = defaultdict(list)
    for a in items:
        if a.type == AnnouncementType.RESCHEDULE and a.based_on_id:
            dependents[a.based_on_id].append(a.announcement_id)

    invalid_reason: dict[str, str] = {}
    stack: list[tuple[str, str]] = [
        (t, f"被撤回公告直接撤回") for t in withdrawn_targets
    ]
    while stack:
        node_id, reason = stack.pop()
        if node_id in invalid_reason:
            continue
        invalid_reason[node_id] = reason
        for child in dependents.get(node_id, []):
            stack.append((child, f"所依据的改期公告 {node_id} 已失效（撤回级联）"))

    # 3) 依据公告本身无效或不存在的改期，也不能成为有效链的一部分
    changed = True
    while changed:
        changed = False
        for a in items:
            if a.type != AnnouncementType.RESCHEDULE or a.announcement_id in invalid_reason:
                continue
            base = a.based_on_id
            if base not in by_id:
                invalid_reason[a.announcement_id] = f"依据公告 {base} 不存在"
                changed = True
            elif base in invalid_reason:
                invalid_reason[a.announcement_id] = (
                    f"依据公告 {base} 已失效（撤回级联）"
                )
                changed = True

    for aid, reason in invalid_reason.items():
        views[aid].valid = False
        views[aid].invalid_reason = reason

    return views, original, notes


def build_tender_detail(code: str, items: list[Announcement]) -> TenderDetail:
    views, original, notes = _build_views(items)
    by_id = {a.announcement_id: a for a in items}
    project_name = items[0].project_name

    if original is None:
        return TenderDetail(
            tender_code=code,
            project_name=project_name,
            status="original_missing",
            current_deadline=None,
            notes=notes + ["缺少招标公告（原公告），无法确定有效截止时间"],
            announcements=list(views.values()),
        )

    # 从原公告出发沿有效改期下行
    current = original.announcement_id
    current_deadline = original.deadline
    conflict: list[ConflictItem] | None = None

    while True:
        children = [
            a
            for a in items
            if a.type == AnnouncementType.RESCHEDULE
            and a.based_on_id == current
            and views[a.announcement_id].valid
        ]
        if not children:
            break
        if len(children) == 1:
            nxt = children[0]
            current = nxt.announcement_id
            current_deadline = nxt.deadline
            continue

        # 并行有效改期：比较截止时间
        deadlines = {c.deadline for c in children}
        if len(deadlines) == 1:
            chosen = min(children, key=lambda c: (c.published_at, c.announcement_id))
            notes.append(
                "公告 "
                + "、".join(c.announcement_id for c in children)
                + f" 为并行改期且截止时间一致（{chosen.deadline}）"
            )
            current = chosen.announcement_id
            current_deadline = chosen.deadline
            continue

        conflict = [
            ConflictItem(
                announcement_id=c.announcement_id,
                deadline=c.deadline or "",
                published_at=c.published_at,
                source_url=c.source_url,
            )
            for c in sorted(children, key=lambda c: (c.published_at, c.announcement_id))
        ]
        current_deadline = None
        break

    status = "conflict" if conflict else "ok"
    if status == "ok":
        # 截止时间最终来源公告（便于核对）
        src = by_id[current]
        notes.append(f"当前截止时间依据有效公告链末端公告 {current}（{src.type.value}）")

    return TenderDetail(
        tender_code=code,
        project_name=project_name,
        status=status,
        current_deadline=current_deadline,
        conflict=conflict,
        notes=notes,
        announcements=list(views.values()),
    )


def build_all(announcements: list[Announcement]) -> list[TenderDetail]:
    grouped = group_by_tender(announcements)
    return [build_tender_detail(code, grouped[code]) for code in sorted(grouped)]
