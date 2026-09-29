"""Daily report archiving.

Two rules carried over from how these reports have always been kept:

1. **Format only, never rewrite.** The author's wording, and any marker they wrote
   such as 「（调试中）」, is preserved exactly. The status emoji is derived *from* that
   marker, so the two never disagree.
2. **Keep the raw text verbatim** at the bottom of every archive file. If parsing ever
   gets something wrong, the source of truth is still in the file.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Dict, List, Optional

from .models import Entry, Item, status_emoji, status_label
from .weeks import week_label

_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

SECTION_TITLES = {
    "done": "今日完成",
    "todo": "明日计划",
    "notes": "问题与思考",
}


def weekday_zh(date: str) -> str:
    d = _dt.date(*[int(x) for x in date.split("-")])
    return _WEEKDAY_ZH[d.weekday()]


def render_item(item: Item, indent: int = 0) -> str:
    pad = "  " * indent
    emoji = status_emoji(item.status)
    return "%s- %s %s" % (pad, emoji, item.text)


def render_daily(entry: Entry, cfg: Optional[Dict] = None) -> str:
    cfg = cfg or {}
    week = entry.week or ""
    out: List[str] = []
    out.append("# 日报 · %s（%s）" % (entry.date, weekday_zh(entry.date)))
    out.append("")
    out.append("> ISO 周：%s ｜ 归档时间：%s ｜ 来源：%s"
               % (week, entry.archived_at or "-", entry.source))
    out.append("")

    # Group by section, in the order the sections were written.
    by_section: Dict[str, List[Item]] = {}
    for it in entry.items:
        key = _section_of(it)
        by_section.setdefault(key, []).append(it)

    for key in ("done", "todo", "notes"):
        items = by_section.get(key, [])
        prose = entry.sections.get(key, [])
        if not items and not prose:
            continue
        out.append("## %s" % SECTION_TITLES[key])
        out.append("")
        current_project = ""
        for it in items:
            if it.level == 0:
                if it.is_group:
                    current_project = it.text
                    out.append("- **%s**" % it.text)
                    continue
                current_project = ""
                out.append(render_item(it))
            else:
                out.append(render_item(it, indent=1))
        for line in prose:
            out.append("- %s" % line)
        out.append("")

    if not entry.items and not any(entry.sections.values()):
        out.append("_（未提供任何条目）_")
        out.append("")

    out.append("---")
    out.append("")
    out.append("## 逐字原文（备查）")
    out.append("")
    out.append("```text")
    out.append(entry.raw_text.rstrip("\n"))
    out.append("```")
    out.append("")
    return "\n".join(out)


def _section_of(item: Item) -> str:
    """Which section an item belongs to, using the order it was parsed in."""
    if item.status == "todo":
        return "todo"
    return "done"


def daily_path(repo_root: str, entry: Entry, cfg: Optional[Dict] = None) -> str:
    cfg = cfg or {}
    sub = cfg.get("reports_dir", "reports")
    return os.path.join(repo_root, sub, "daily", "%s.md" % entry.date)


def write_daily(entry: Entry, repo_root: str, cfg: Optional[Dict] = None) -> str:
    cfg = cfg or {}
    path = daily_path(repo_root, entry, cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_daily(entry, cfg))
    return path


def status_counts(entry: Entry) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for it in entry.items:
        if it.is_group:
            continue
        counts[it.status] = counts.get(it.status, 0) + 1
    return counts


def describe_counts(counts: Dict[str, int]) -> str:
    parts = ["%s%s %d" % (status_emoji(k), status_label(k), v)
             for k, v in counts.items() if v]
    return " ｜ ".join(parts) if parts else "无条目"