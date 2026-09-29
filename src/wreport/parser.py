"""Turn a free-text daily report into structured items.

Two invariants drive everything here:

1. **No line is silently dropped.** Every non-empty line either becomes an item, a
   section heading, a project label, or is kept as prose. Losing a line because it did
   not match a pattern is the one failure mode an archive must never have.
2. **Status is read, never guessed.** Precedence is: a marker the author bracketed >
   the default of the section they put the line under > an unambiguous outcome word in
   the line itself > the configured fallback for unmarked lines > unknown.

Status is never derived from an item being *missing* from a later report: that kind of
cross-day inference is deliberately out of scope, so the tool behaves like an ordinary
tracker where status is written down.

Reports arrive in more than one shape, all supported:

    今日完成                    代码门禁
    1. 甲事项                   1. 甲事项
    a. 子事项                   EMV自动化流水线
                                1. 乙事项

-- i.e. a bracketed status marker, a section heading, or a bare label line acting as a
project grouping.
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

_SECTION_DEFAULT_STATUS = {"done": models.DONE, "todo": models.TODO,
                           "notes": models.UNKNOWN}

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
    (models.TODO, ("未开始", "待开始", "待启动", "待办", "排队", "未启动", "还没",
                   "搁置", "暂缓", "todo", "pending")),
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
    (models.TODO, ("未开始", "待开始", "待启动", "待办", "未启动", "搁置", "暂缓")),
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
_MAX_PROJECT_LABEL = 32

_SENTENCE_PUNCT = "。！？；!?;"


def _status_from_text(text: str) -> Tuple[str, str]:
    """Return (status, raw_marker) based on an explicit marker in the line."""
    for m in _MARKER_RE.finditer(text):
        inner = m.group(1).strip()
        for status, keys in _MARKER_RULES:
            for k in keys:
                if k in inner:
                    return status, inner
    return models.UNKNOWN, ""


def _ends_with_progressive(text: str) -> bool:
    """「定位并修复部分问题中」 -- a trailing 中 marks work still going on.

    Deliberately narrow: the character must be *final* (after punctuation is stripped),
    which is what separates the progress suffix from 中 as an ordinary character
    (「支持中文」 does not end with it).
    """
    body = text.rstrip("。.,，;； ")
    return len(body) >= 3 and body.endswith("中")


def _status_from_inline(text: str) -> str:
    """Status from a word inside the line, when nothing more explicit exists.

    Uses the stricter `_INLINE_RULES`: matching a word inside a sentence says much less
    than a word the author deliberately bracketed.
    """
    for status, keys in _INLINE_RULES:
        for k in keys:
            if k in text:
                return status
    if _ends_with_progressive(text):
        return models.DOING
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


def _is_bullet(line: str) -> bool:
    return bool(_TOP_RE.match(line) or _SUB_RE.match(line) or _SUB_FLUSH_RE.match(line))


def _looks_like_project_label(line: str, next_line: str) -> bool:
    """A bare, short line that introduces bulleted items is a project grouping label.

    Requiring the *next* line to be a bullet is what keeps a stray bare sentence from
    being promoted to a heading.
    """
    body = line.strip()
    if not body or len(body) > _MAX_PROJECT_LABEL:
        return False
    if any(ch in body for ch in _SENTENCE_PUNCT):
        return False
    if _match_section(line):
        return False
    if _is_bullet(line):
        return False
    return _is_bullet(next_line)


def parse_report(text: str, date: Optional[str] = None, source: str = "manual",
                 unmarked: str = models.UNKNOWN) -> Entry:
    """Parse a daily report into an Entry.

    `date` defaults to today (local). `text` is preserved verbatim on the Entry.
    `unmarked` is the status to fall back to when nothing at all indicates one -- it is
    `unknown` unless the caller explicitly configures otherwise, so the default never
    invents a status.
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

    lines = [l for l in raw.split("\n") if l.strip()]

    section: Optional[str] = None
    section_status = models.UNKNOWN
    bare_project = ""      # text of an open bare-label project, "" when none
    current_project = ""   # what a nested line inherits
    cand_idx: Optional[int] = None   # top-level line that becomes a group if it gets children
    order = 0

    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""

        hit = _match_section(line)
        if hit:
            section = hit[0]
            section_status = _SECTION_DEFAULT_STATUS[section]
            bare_project = ""
            current_project = ""
            cand_idx = None
            continue

        top = _TOP_RE.match(line)
        sub = None if top else (_SUB_RE.match(line) or _SUB_FLUSH_RE.match(line))

        # --- bare line: a project label, or prose -----------------------------
        if top is None and sub is None:
            if _looks_like_project_label(line, nxt):
                order += 1
                label = line.strip().rstrip(":：")
                entry.items.append(Item(text=label, status=models.UNKNOWN, level=0,
                                        project="", section=section or "", order=order,
                                        is_group=True))
                bare_project = label
                current_project = label
                cand_idx = None
                continue
            # prose is kept, never dropped
            key = section if section else ""
            entry.sections.setdefault(key, []).append(line.strip())
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
            if section_status != models.UNKNOWN:
                status = section_status
            else:
                status = _status_from_inline(body)
                if status == models.UNKNOWN:
                    status = unmarked

        clean = _MARKER_RE.sub("", body).strip().rstrip("。.,，;；")
        level = 0 if top is not None else 1

        if level == 1:
            project = current_project
        elif bare_project:
            project = bare_project          # numbered item inside a labelled project
        else:
            project = ""
            current_project = clean
            cand_idx = len(entry.items)      # may become a group if children follow

        order += 1
        entry.items.append(Item(text=clean, status=status, raw_status=raw_marker,
                                level=level, project=project, order=order,
                                section=section or ""))

        if level == 1 and cand_idx is not None:
            entry.items[cand_idx].is_group = True
            entry.items[cand_idx].status = models.UNKNOWN
            cand_idx = None

    return entry


def summarize(entry: Entry) -> Dict[str, int]:
    counts: Dict[str, int] = {s: 0 for s in models.STATUS_ORDER}
    for it in entry.items:
        if it.is_group:
            continue
        counts[it.status] = counts.get(it.status, 0) + 1
    return counts