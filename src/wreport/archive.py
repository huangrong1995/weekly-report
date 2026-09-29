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
    "": "事项（原文未分栏目）",
}


def weekday_zh(date: str) -> str:
    d = _dt.date(*[int(x) for x in date.split("-")])
    return _WEEKDAY_ZH[d.weekday()]


def render_item(item: Item, indent: int = 0) -> str:
    pad = "  " * indent
    emoji = status_emoji(item.status)
    return "%s- %s %s" % (pad, emoji, item.text)


def render_daily(entry: Entry, cfg: Optional[Dict] = None) -> str:
    """Render an archive file.

    Deterministic: no archive timestamp is written, so re-importing an unchanged report
    produces identical bytes. `archived_at` still lives in `data/entries.json` as
    metadata -- it is simply not part of the rendered document.

    Section headings are only emitted for sections the author actually used. A report
    written without a 「今日完成」 heading is NOT given one: inventing a heading the
    author never wrote would misrepresent their input.
    """
    cfg = cfg or {}
    week = entry.week or ""
    out: List[str] = []
    out.append("# 日报 · %s（%s）" % (entry.date, weekday_zh(entry.date)))
    out.append("")
    out.append("> ISO 周：%s ｜ 来源：%s" % (week, entry.source))
    out.append("")

    # Group by the section the author actually wrote.
    by_section: Dict[str, List[Item]] = {}
    for it in entry.items:
        by_section.setdefault(it.section if it.section in SECTION_TITLES else "", []).append(it)

    for key in ("done", "todo", "", "notes"):
        items = by_section.get(key, [])
        prose = entry.sections.get(key, []) if key else []
        if not items and not prose:
            continue
        out.append("## %s" % SECTION_TITLES[key])
        out.append("")
        for it in items:
            if it.is_group:
                out.append("- **%s**" % it.text)
            else:
                out.append(render_item(it, indent=1 if it.level == 1 else 0))
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