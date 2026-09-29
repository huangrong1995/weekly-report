"""Data model for weekly-report.

Deliberately plain dataclasses with explicit JSON (de)serialisation: the on-disk
`data/entries.json` is the durable record, so its shape must stay stable and readable
by hand. Keep this module free of I/O and of any reporting logic.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------
# Statuses are EXPLICIT. They come from a marker the author wrote (「（调试中）」,
# 「完成」) or from the section the line sits under (「今日完成」 => done).
# Nothing is ever inferred from an item *disappearing* between reports -- the tool
# stays consistent with how ordinary issue trackers work.

DONE = "done"
DOING = "doing"
TODO = "todo"
BLOCKED = "blocked"
UNKNOWN = "unknown"

STATUS_ORDER = [DONE, DOING, TODO, BLOCKED, UNKNOWN]

STATUS_META: Dict[str, Dict[str, str]] = {
    DONE: {"emoji": "✅", "label": "完成"},
    DOING: {"emoji": "🔧", "label": "进行中"},
    TODO: {"emoji": "⏸️", "label": "未开始"},
    BLOCKED: {"emoji": "🚧", "label": "受阻"},
    UNKNOWN: {"emoji": "⬜", "label": "未标注"},
}


def status_emoji(status: str) -> str:
    return STATUS_META.get(status, STATUS_META[UNKNOWN])["emoji"]


def status_label(status: str) -> str:
    return STATUS_META.get(status, STATUS_META[UNKNOWN])["label"]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

SECTION_DONE = "done"
SECTION_TODO = "todo"
SECTION_NOTES = "notes"
SECTION_OTHER = "other"

# Section heading -> (canonical key, default status for items inside it).
# The heading text is what the user actually writes; match loosely on the
# distinctive part so 「今日完成」「本周完成」「一、今日完成」 all land the same place.
SECTION_RULES = [
    (("今日完成", "本周完成", "已完成", "完成事项"), SECTION_DONE, DONE),
    (("明日计划", "下周计划", "本周计划", "计划"), SECTION_TODO, TODO),
    (("问题与思考", "问题", "思考", "反思", "小结"), SECTION_NOTES, UNKNOWN),
]


@dataclass
class Item:
    """One line of work extracted from a report."""

    text: str
    """Item text with the leading bullet/number and any status marker stripped."""

    status: str = UNKNOWN
    raw_status: str = ""
    """The marker as written, e.g. 「调试中」. Empty when nothing was written."""

    level: int = 0
    """0 = top-level (1. 2. 3.), 1 = nested (a. b. c. / - )."""

    project: str = ""
    """Title of the enclosing top-level item, when this line is nested."""

    section: str = ""
    """Which section the line sat under: 'done' | 'todo' | 'notes' | ''."""

    is_group: bool = False
    """True when this top-level line only introduces children and states no work itself."""

    order: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Item":
        known = {f.name for f in dataclasses.fields(Item)}
        return Item(**{k: v for k, v in d.items() if k in known})


@dataclass
class Entry:
    """One day's report."""

    date: str
    """ISO date, YYYY-MM-DD. Also the archive filename stem."""

    week: str
    """ISO week label, YYYY-Www."""

    raw_text: str = ""
    """The report exactly as submitted -- never rewritten."""

    items: List[Item] = field(default_factory=list)
    sections: Dict[str, List[str]] = field(default_factory=dict)
    """Canonical section key -> prose lines for that section (notes etc.)."""

    source: str = "manual"
    archived_at: str = ""

    def items_by_project(self) -> Dict[str, List[Item]]:
        """Group work items by project, preserving first-seen order."""
        groups: Dict[str, List[Item]] = {}
        for it in self.items:
            if it.is_group:
                continue
            groups.setdefault(it.project or "", []).append(it)
        return groups

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "week": self.week,
            "raw_text": self.raw_text,
            "items": [i.to_dict() for i in self.items],
            "sections": self.sections,
            "source": self.source,
            "archived_at": self.archived_at,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Entry":
        return Entry(
            date=d["date"],
            week=d.get("week", ""),
            raw_text=d.get("raw_text", ""),
            items=[Item.from_dict(i) for i in d.get("items", [])],
            sections=d.get("sections", {}),
            source=d.get("source", "manual"),
            archived_at=d.get("archived_at", ""),
        )


def dump_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n"