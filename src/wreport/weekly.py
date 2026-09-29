"""Weekly report generation.

Rollup rule (standard tracker behaviour, nothing bespoke): an item is identified by
(project, text); if the same item is written on several days of the week it is merged
into one row whose status is the **latest status the author explicitly wrote**. A
status is never assumed from an item not being repeated later -- if the author stops
writing an item down, the last status they wrote is what stands, and the row still
shows its full per-day history so nothing is hidden.

Coverage is reported honestly: days of the week with no daily report are listed in the
header and in the summary, rather than being silently treated as empty.

Output is **byte-for-byte deterministic** for a given (entries, week, config): no
generation timestamp is embedded, so regenerating an unchanged week produces no diff
and the file is safe to keep under version control.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Dict, List, Optional, Tuple

from .models import (BLOCKED, DONE, DOING, Entry, TODO, UNKNOWN, status_emoji,
                     status_label)
from .weeks import week_bounds, week_dates, week_label

WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@dataclasses.dataclass
class RollupItem:
    text: str
    project: str
    status: str
    first_date: str
    last_date: str
    days: int
    history: List[Tuple[str, str, str]] = dataclasses.field(default_factory=list)
    """(date, status, raw_marker) in chronological order."""

    @property
    def timeline(self) -> str:
        """'09/21 ⏸️ → 09/22 🔧' -- only when the status actually moved."""
        if self.days < 2:
            return ""
        seen: List[str] = []
        for date, status, _raw in self.history:
            mmdd = date[5:].replace("-", "/")
            seen.append("%s %s" % (mmdd, status_emoji(status)))
        # collapse repeats of the same status to keep the line readable
        out: List[str] = []
        for token in seen:
            if not out or out[-1].split()[-1] != token.split()[-1]:
                out.append(token)
        return " → ".join(out) if len(out) > 1 else ""


def aggregate(entries: List[Entry]) -> List[RollupItem]:
    """Merge the week's items into one row per (project, text)."""
    buckets: Dict[Tuple[str, str], RollupItem] = {}
    for entry in sorted(entries, key=lambda e: e.date):
        for it in entry.items:
            if it.is_group or not it.text:
                continue
            key = (it.project or "", it.text)
            row = buckets.get(key)
            if row is None:
                row = RollupItem(text=it.text, project=it.project or "",
                                 status=it.status, first_date=entry.date,
                                 last_date=entry.date, days=0)
                buckets[key] = row
            row.last_date = entry.date
            row.days += 1
            row.status = it.status  # latest explicit status wins
            row.history.append((entry.date, it.status, it.raw_status))

    rows = list(buckets.values())
    rows.sort(key=lambda r: (r.project or "~", r.first_date, r.text))
    return rows


def _by_status(rows: List[RollupItem], statuses: Tuple[str, ...]) -> Dict[str, List[RollupItem]]:
    groups: Dict[str, List[RollupItem]] = {}
    for r in rows:
        if r.status in statuses:
            groups.setdefault(r.project or "", []).append(r)
    return groups


def _row(r: RollupItem) -> str:
    line = "- %s %s" % (status_emoji(r.status), r.text)
    tl = r.timeline
    if tl:
        line += "  `%s`" % tl
    return line


def _render_grouped(groups: Dict[str, List[RollupItem]], multi: bool) -> str:
    """Named projects first, then the top-level lines that belong to no project.

    Blocks are joined with a blank line rather than trailing one after each group --
    trailing blanks produced headings that ran straight into the previous group.
    """
    blocks: List[str] = []
    for project, rows in groups.items():
        if not project:
            continue
        lines: List[str] = []
        if multi:
            lines.append("### %s" % project)
            lines.append("")
        lines.extend(_row(r) for r in rows)
        blocks.append("\n".join(lines))
    unnamed = groups.get("", [])
    if unnamed:
        blocks.append("\n".join(_row(r) for r in unnamed))
    return "\n\n".join(blocks) if blocks else "_（无）_"


def coverage(entries: List[Entry], week: str) -> Dict[str, List[str]]:
    """Which days of the week have a report, and which do not."""
    have = sorted(e.date for e in entries)
    all_days = [d.isoformat() for d in week_dates(week)]
    return {"covered": have, "missing": [d for d in all_days if d not in have]}


def _fmt_days(dates: List[str]) -> str:
    return "、".join(d[5:].replace("-", "/") for d in dates)


def build_weekly(entries: List[Entry], week: str, cfg: Optional[Dict] = None,
                 owner: str = "") -> str:
    cfg = cfg or {}
    rows = aggregate(entries)
    cov = coverage(entries, week)
    multi = len({r.project for r in rows if r.project}) > 0

    done = _by_status(rows, (DONE,))
    doing = _by_status(rows, (DOING,))
    waiting = _by_status(rows, (TODO, BLOCKED))
    untagged = _by_status(rows, (UNKNOWN,))

    out: List[str] = []
    out.append("# 📋 本周工作周报 · %s" % week_label(week))
    if owner:
        out.append("")
        out.append("**汇报人**：%s" % owner)
    out.append("")
    out.append("> 数据来源：%d 份日报（%s）"
               % (len(entries), _fmt_days(cov["covered"]) or "无"))
    if cov["missing"]:
        out.append(">")
        out.append("> ⚠️ **未覆盖日期**：%s（该期间无日报记录，本报告不含其内容）"
                   % _fmt_days(cov["missing"]))
    out.append("")

    out.append("## 一、本周完成 %s" % status_emoji(DONE))
    out.append("")
    out.append(_render_grouped(done, multi))
    out.append("")

    out.append("## 二、进行中 %s" % status_emoji(DOING))
    out.append("")
    out.append(_render_grouped(doing, multi))
    out.append("")

    out.append("## 三、待推进 %s" % "/".join([status_emoji(TODO), status_emoji(BLOCKED)]))
    out.append("")
    out.append(_render_grouped(waiting, multi))
    out.append("")

    if untagged:
        out.append("## 附：未标注状态 %s" % status_emoji(UNKNOWN))
        out.append("")
        out.append(_render_grouped(untagged, multi))
        out.append("")

    # 计划 comes from plan-section lines across the week (「明日计划」 in each daily).
    plans: List[Tuple[str, str]] = []
    for e in sorted(entries, key=lambda x: x.date):
        for it in e.items:
            if it.section == "todo" and it.text:
                plans.append((e.date, it.text))
    out.append("## 四、下周计划 📌")
    out.append("")
    if plans:
        for date, text in plans:
            out.append("- %s  `%s`" % (text, date[5:].replace("-", "/")))
    else:
        out.append("_（日报中未提供计划栏目）_")
    out.append("")

    out.append("## 五、本周小结 🎯")
    out.append("")
    total = len(rows)
    projects = sorted({r.project for r in rows if r.project})
    out.append("- 覆盖 **%d** 天日报，涉及 **%d** 个事项、**%d** 个项目"
               % (len(cov["covered"]), total, len(projects)))
    out.append("- 完成 %s%d ｜ 进行中 %s%d ｜ 待推进 %s%d"
               % (status_emoji(DONE), len([r for r in rows if r.status == DONE]),
                  status_emoji(DOING), len([r for r in rows if r.status == DOING]),
                  status_emoji(TODO), len([r for r in rows if r.status in (TODO, BLOCKED)])))
    if projects:
        out.append("- 涉及项目：%s" % "、".join(projects))
    if cov["missing"]:
        out.append("- ⚠️ %s 无日报，该期间的工作未纳入统计"
                   % _fmt_days(cov["missing"]))
    out.append("")

    return "\n".join(out)


def apply_template(body: str, repo_root: str, cfg: Dict, week: str,
                   meta: str = "") -> str:
    """If templates/weekly.md exists, use it as the outer skeleton."""
    path = os.path.join(repo_root, "templates", "weekly.md")
    if not os.path.exists(path):
        return body
    with open(path, encoding="utf-8") as fh:
        tpl = fh.read()
    if "{{" not in tpl:
        return body
    # strip the generated H1 + meta block back out, the template provides those
    parts = body.split("\n")
    idx = next((i for i, l in enumerate(parts) if l.startswith("## ")), len(parts))
    inner = "\n".join(parts[idx:])
    return (tpl.replace("{{title}}", "📋 本周工作周报 · %s" % week_label(week))
               .replace("{{week}}", week)
               .replace("{{meta}}", meta)
               .replace("{{body}}", inner))


def weekly_path(repo_root: str, week: str, cfg: Optional[Dict] = None) -> str:
    cfg = cfg or {}
    return os.path.join(repo_root, cfg.get("reports_dir", "reports"),
                        "weekly", "%s.md" % week)


def write_weekly(markdown: str, repo_root: str, week: str,
                 cfg: Optional[Dict] = None) -> str:
    path = weekly_path(repo_root, week, cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    return path