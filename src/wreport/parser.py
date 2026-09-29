"""Turn a free-text daily report into structured items.

Rules are deliberately explicit and testable -- no heuristics that "feel" right:

* Section headings (今日完成 / 明日计划 / …) set the **default status** for the lines
  beneath them. That is the whole reason a bare 「服务器部署上线」 lines up under 完成.
* A parenthesised marker the author wrote (「（调试中）」) **overrides** the section
  default -- it is an explicit statement and must win.
* Status is never derived from an item being *missing* from a later report. That kind
  of cross-day inference is deliberately out of scope; this tool behaves like an
  ordinary tracker where status is written down.
* Inline verbs ("上线") only matter when there is no section to speak for the line,
  so 「明日计划：上线新版本」 is not misread as finished.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, List, Optional, Tuple

from . import models
from .models import Entry, Item
from .weeks import week_of

# ---------------------------------------------------------------------------
# Recognisers
# ---------------------------------------------------------------------------

_SECTION_KEYS = {
    "done": ("今日完成", "本日完成", "本周完成", "已完成", "完成事项", "完成情况"),
    "todo": ("明日计划", "次日计划", "下周计划", "本周计划", "后续计划", "计划"),
    "notes": ("问题与思考", "问题与反思", "心得", "反思", "本周小结", "小结", "备注"),
}

# «1.» «1、» «一、»  -> top level
_TOP_RE = re.compile(r"^\s{0,3}(?:\d{1,2}\s*[.、)．]|[一二三四五六七八九十]{1,2}\s*[、.．)])\s*(.+)$")
# «a.» «a)» «-» «*» «•»  -> nested level
_SUB_RE = re.compile(r"^\s+(?:[a-z]\s*[.、)．]|[-*•·])\s*(.+)$")
_SUB_FLUSH_RE = re.compile(r"^\s{0,3}(?:[a-z]\s*[.、)．]|[-*•·])\s*(.+)$")

# Two word lists, deliberately different.

# 1) A marker the author wrote in brackets is an explicit statement, so it may match
#    loosely -- 「（调试）」 means what it says.
_MARKER_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    (models.BLOCKED, ("受阻", "阻塞", "卡住", "卡点", "被依赖", "等待外部", "blocked")),
    (models.TODO, ("未开始", "待开始", "待启动", "待办", "排队", "未启动", "还没", "todo", "pending")),
    (models.DOING, ("调试中", "进行中", "开发中", "修复中", "联调中", "优化中", "处理中",
                    "测试中", "推进中", "在做", "调试", "联调", "wip", "doing")),
    (models.DONE, ("已完成", "完成", "已上线", "上线", "已发布", "已交付", "已修复",
                   "已提交", "已合入", "结项", "done", "finished", "completed")),
]

# 2) Guessing a status from a word *inside the sentence* is far more error-prone, so it
#    only accepts unambiguous wording. Notably the bare nouns 「调试」「联调」 are gone:
#    「添加调试日志」 is a task being done, not a task in progress.
_INLINE_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    (models.BLOCKED, ("受阻", "阻塞", "卡住", "卡点")),
    (models.TODO, ("未开始", "待开始", "待启动", "待办", "未启动")),
    (models.DOING, ("进行中", "开发中", "修复中", "优化中", "处理中", "测试中", "推进中")),
    (models.DONE, ("已完成", "完成", "已上线", "上线", "已发布", "已交付", "已修复",
                   "已提交", "已合入", "结项")),
]

# Annotation markers get stripped from the text: 「（调试中）」 is an annotation,
# whereas a verb inside the sentence is part of the sentence.
_MARKER_RE = re.compile(r"[（(【\[]\s*([^）)】\]]{1,12})\s*[）)】\]]")

# Strip the decoration a heading may carry: markdown ###, bold, and a leading
# enumerator (1. / 1、/ 一、).
_HEADING_DECOR = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?:(?:\d{1,2}|[一二三四五六七八九十]{1,2})\s*[、.．)]\s*)?"
    r"(?:\*\*|__)?\s*(.+?)\s*(?:\*\*|__)?\s*[:：]?\s*$")

_MAX_HEADING = 16


def _status_from_text(text: str) -> Tuple[str, str]:
    """Return (status, raw_marker) based on an explicit marker in the line."""
    for m in _MARKER_RE.finditer(text):
        inner = m.group(1).strip()
        for status, keys in _MARKER_RULES:
            for k in keys:
                if k in inner:
                    return status, inner
    return models.UNKNOWN, ""


def _status_from_inline(text: str) -> str:
    """Last-resort status when no section and no marker speaks for the line.

    Uses the stricter `_INLINE_RULES`: matching a word inside a sentence says much less
    than a word the author deliberately bracketed.
    """
    for status, keys in _INLINE_RULES:
        for k in keys:
            if k in text:
                return status
    return models.UNKNOWN


def _match_section(line: str) -> Optional[Tuple[str, str]]:
    """If the line is a section heading, return (key, matched heading).

    A heading must be a *standalone label*: after decoration is stripped, the body has
    to **end with** the heading word (or equal it). Matching on mere containment made
    「AI Code Review问题修复」 look like a 「问题与思考」 heading and silently swallowed the
    line, so containment alone is not enough.
    """
    m = _HEADING_DECOR.match(line)
    if not m:
        return None
    body = m.group(1).strip()
    if not body or len(body) > _MAX_HEADING:
        return None
    for key, words in _SECTION_KEYS.items():
        for w in words:
            if body == w or body.endswith(w):
                return key, body
    return None


def parse_report(text: str, date: Optional[str] = None,
                 source: str = "manual") -> Entry:
    """Parse a daily report into an Entry.

    `date` defaults to today (local). `text` is preserved verbatim on the Entry.
    """
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if date:
        d = _dt.date(*[int(x) for x in date.split("-")])
    else:
        d = _dt.date.today()
    entry = Entry(date=d.isoformat(), week=week_of(d), raw_text=raw,
                  sections={"done": [], "todo": [], "notes": []},
                  source=source,
                  archived_at=_dt.datetime.now().replace(microsecond=0).isoformat())

    section: Optional[str] = None
    section_status = models.UNKNOWN
    current_project = ""
    last_top_idx: Optional[int] = None
    top_has_child: set = set()
    order = 0

    for line in raw.split("\n"):
        if not line.strip():
            continue

        hit = _match_section(line)
        if hit:
            section = hit[0]
            section_status = {"done": models.DONE,
                              "todo": models.TODO,
                              "notes": models.UNKNOWN}[section]
            current_project = ""
            last_top_idx = None
            continue

        top = _TOP_RE.match(line)
        sub = None if top else (_SUB_RE.match(line) or _SUB_FLUSH_RE.match(line))
        if top is None and sub is None:
            # prose: belongs to whatever section is open
            if section:
                entry.sections.setdefault(section, []).append(line.strip())
            continue
        if section == "notes":
            entry.sections.setdefault("notes", []).append(line.strip())
            continue

        matcher = top if top is not None else sub
        assert matcher is not None  # guarded above
        body = matcher.group(1).strip()
        if not body:
            continue

        status, raw_marker = _status_from_text(body)
        if not raw_marker:
            status = section_status if section_status != models.UNKNOWN \
                else _status_from_inline(body)

        clean = _MARKER_RE.sub("", body).strip().rstrip("。.,，;；")
        level = 0 if top is not None else 1
        project = current_project if level == 1 else ""

        order += 1
        item = Item(text=clean, status=status, raw_status=raw_marker,
                    level=level, project=project, order=order,
                    section=section or "")
        entry.items.append(item)

        if level == 0:
            current_project = clean
            last_top_idx = len(entry.items) - 1
        elif last_top_idx is not None:
            top_has_child.add(last_top_idx)

    # A top-level line that introduced children states no work of its own. It must also
    # carry NO status: otherwise it inherits the section default and a group header
    # renders as "✅ 完成", which reads as if the whole group were finished.
    for idx in top_has_child:
        group = entry.items[idx]
        group.is_group = True
        group.status = models.UNKNOWN

    return entry


def summarize(entry: Entry) -> Dict[str, int]:
    counts: Dict[str, int] = {s: 0 for s in models.STATUS_ORDER}
    for it in entry.items:
        if it.is_group:
            continue
        counts[it.status] = counts.get(it.status, 0) + 1
    return counts