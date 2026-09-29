"""Command-line interface -- the single entry point.

Every subcommand has real `--help` text, works non-interactively (`--json`, `--yes`) for
cron/CI use, and exits non-zero on failure so it can be chained in a shell.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

from . import __version__, archive, config, gitutil, models, parser, render, store, weekly
from .weeks import (current_week, parse_date, parse_week, previous_week,
                    week_bounds, week_of)

PROG = "wreport"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _root() -> str:
    return store.REPO_ROOT


def _load() -> List[models.Entry]:
    return store.load_entries()


def _read_input(args) -> str:
    if getattr(args, "text", None):
        return args.text
    if getattr(args, "file", None):
        with open(args.file, encoding="utf-8") as fh:
            return fh.read()
    if sys.stdin is None or sys.stdin.isatty():
        render.info("请粘贴日报内容，输入完成后按 Ctrl-D 结束：")
    return sys.stdin.read()


def _resolve_week(args) -> str:
    if getattr(args, "week", None):
        return args.week
    if getattr(args, "date", None):
        return week_of(parse_date(args.date))
    return current_week()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    root = _root()
    cfg = config.load_config()
    if not args.yes and not args.non_interactive:
        render.head("初始化 weekly-report")
        render.info("Enter 保持当前值（方括号内为当前值）")
        cfg["owner"] = render.prompt_text("汇报人姓名", cfg.get("owner", ""))
        cfg["week_start"] = render.prompt_select(
            "每周起始日", ["monday", "sunday"], cfg.get("week_start", "monday"))
        cfg["language"] = render.prompt_select(
            "报告语言", ["zh", "en"], cfg.get("language", "zh"))
        enable = render.prompt_confirm(
            "启用 LLM 润色（可选，失败会自动回落到确定性输出）",
            bool(cfg["llm"].get("enabled")))
        cfg["llm"]["enabled"] = enable
        if enable:
            cfg["llm"]["base_url"] = render.prompt_text(
                "LLM base_url", cfg["llm"].get("base_url", ""))
            cfg["llm"]["model"] = render.prompt_text(
                "LLM 模型名", cfg["llm"].get("model", ""))
            cfg["llm"]["api_key_env"] = render.prompt_text(
                "API Key 所在环境变量名", cfg["llm"].get("api_key_env", "WREPORT_API_KEY"))

    config.save_config(cfg)
    for d in ("data", os.path.join(cfg.get("reports_dir", "reports"), "daily"),
              os.path.join(cfg.get("reports_dir", "reports"), "weekly")):
        os.makedirs(os.path.join(root, d), exist_ok=True)

    render.ok("配置已写入 data/config.json")
    render.kv([("汇报人", cfg.get("owner") or "（未设置）"),
               ("周起始", cfg.get("week_start")),
               ("LLM 润色", "启用" if cfg["llm"].get("enabled") else "关闭")])
    if args.json:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# daily
# ---------------------------------------------------------------------------

def cmd_daily_add(args) -> int:
    root = _root()
    cfg = config.load_config()
    date = parse_date(args.date).isoformat() if args.date else parse_date("today").isoformat()

    text = _read_input(args)
    if not text.strip():
        render.err("没有收到任何内容")
        return 2

    entry = parser.parse_report(text, date=date, source=args.source)
    counts = archive.status_counts(entry)

    render.head("解析结果 · %s" % date)
    for it in entry.items:
        pad = "  " * it.level
        if it.is_group:
            # structural header: no status to show
            render.out("%s- [bold]%s[/bold]  [dim](分组)[/dim]" % (pad, it.text))
        else:
            render.out("%s- %s %s" % (pad, models.status_emoji(it.status), it.text))
    render.out("")
    render.out(render.bar(counts))

    if not args.yes:
        if not render.prompt_confirm("归档并写入结构化数据？", True):
            render.warn("已取消，未写入任何内容")
            return 1

    entries = _load()
    action = store.upsert_entry(entries, entry)
    store.save_entries(entries)
    store.rebuild_index(entries)
    path = archive.write_daily(entry, root, cfg)

    render.ok("日报 %s（%s）" % ("已更新" if action == "replaced" else "已归档",
                                os.path.relpath(path, root)))
    render.kv([("条目", "%d 条" % sum(1 for i in entry.items if not i.is_group)),
               ("ISO 周", entry.week),
               ("原文", "已随档案保存")])
    if args.json:
        print(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_daily_list(args) -> int:
    entries = _load()
    if args.week:
        entries = store.entries_for_week(entries, args.week)
    if not entries:
        render.warn("没有日报记录")
        return 0
    rows = []
    for e in entries:
        c = archive.status_counts(e)
        rows.append([e.date, archive.weekday_zh(e.date), e.week,
                     str(sum(c.values())), archive.describe_counts(c)])
    if args.json:
        print(json.dumps([e.to_dict() for e in entries], ensure_ascii=False, indent=2))
        return 0
    render.table(rows, ["日期", "星期", "ISO 周", "条目", "状态"])
    return 0


def cmd_daily_show(args) -> int:
    date = parse_date(args.date).isoformat()
    entry = store.get_entry(_load(), date)
    if entry is None:
        render.err("没有 %s 的日报" % date)
        return 1
    if args.json:
        print(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2))
    else:
        render.out(archive.render_daily(entry, config.load_config()))
    return 0


# ---------------------------------------------------------------------------
# weekly
# ---------------------------------------------------------------------------

def cmd_weekly_build(args) -> int:
    root = _root()
    cfg = config.load_config()
    week = _resolve_week(args)
    entries = store.entries_for_week(_load(), week)

    if not entries:
        render.err("%s 没有任何日报，无法生成周报" % week)
        return 1

    meta = "生成时间：%s" % "-"
    markdown = weekly.build_weekly(entries, week, cfg, owner=cfg.get("owner", ""))
    # A template is optional: `templates/weekly.md` is used only when it exists and
    # carries {{placeholders}}. Applying it unconditionally keeps the output identical
    # whether or not polish runs.
    markdown = weekly.apply_template(markdown, root, cfg, week, meta)

    if args.polish:
        if not config.llm_ready(cfg):
            render.warn("LLM 润色未就绪（未启用或缺凭据），使用确定性输出")
        else:
            try:
                markdown = _polish(markdown, cfg)
                render.ok("已由 LLM 润色")
            except Exception as exc:  # never block the report
                render.warn("LLM 润色失败（%s），使用确定性输出" % exc)

    cov = weekly.coverage(entries, week)
    if args.stdout:
        print(markdown)
        return 0

    path = weekly.weekly_path(root, week, cfg)
    if os.path.exists(path) and not args.force and not args.yes:
        if not render.prompt_confirm("%s 已存在，覆盖？" % os.path.relpath(path, root), False):
            render.warn("已取消")
            return 1

    path = weekly.write_weekly(markdown, root, week, cfg)
    render.ok("周报已写入 %s" % os.path.relpath(path, root))
    rows = weekly.aggregate(entries)
    render.kv([("周次", week), ("日报", "%d 份" % len(entries)),
               ("事项", "%d 条" % len(rows)),
               ("完成", "%d 条" % len([r for r in rows if r.status == models.DONE]))])
    if cov["missing"]:
        render.warn("未覆盖日期：%s" % "、".join(cov["missing"]))
    if args.json:
        print(json.dumps({"week": week, "path": path,
                          "coverage": cov,
                          "items": [vars(r) for r in rows]},
                         ensure_ascii=False, indent=2, default=str))
    return 0


def _polish(markdown: str, cfg: Dict) -> str:
    from . import llm
    return llm.polish(markdown, cfg)


def cmd_weekly_list(args) -> int:
    root = _root()
    cfg = config.load_config()
    weekdir = os.path.join(root, cfg.get("reports_dir", "reports"), "weekly")
    if not os.path.isdir(weekdir):
        render.warn("还没有周报")
        return 0
    files = sorted(f for f in os.listdir(weekdir) if f.endswith(".md"))
    if not files:
        render.warn("还没有周报")
        return 0
    entries = _load()
    rows = []
    for f in files:
        wk = f[:-3]
        n = len(store.entries_for_week(entries, wk))
        rows.append([wk, week_bounds(wk)[0].strftime("%m/%d") + "–" +
                     week_bounds(wk)[1].strftime("%m/%d"), "%d 份" % n,
                     "%d B" % os.path.getsize(os.path.join(weekdir, f))])
    if args.json:
        print(json.dumps(files))
        return 0
    render.table(rows, ["周次", "期间", "日报", "大小"])
    return 0


# ---------------------------------------------------------------------------
# ledger / status / sync / lint
# ---------------------------------------------------------------------------

def cmd_ledger(args) -> int:
    entries = _load()
    if not entries:
        render.warn("还没有任何日报")
        return 0
    weeks = sorted({e.week for e in entries}, reverse=True)[:args.weeks]
    entries = [e for e in entries if e.week in weeks]
    rows = weekly.aggregate(entries)
    if args.json:
        print(json.dumps([vars(r) for r in rows], ensure_ascii=False, indent=2, default=str))
        return 0
    render.head("进展台账（近 %d 周）" % len(weeks))
    table_rows = []
    for r in rows:
        table_rows.append([models.status_emoji(r.status),
                           r.project or "—",
                           r.text,
                           r.timeline or r.last_date[5:].replace("-", "/")])
    render.table(table_rows, ["状态", "项目", "事项", "时间线"])
    return 0


def cmd_status(args) -> int:
    entries = _load()
    cfg = config.load_config()
    if args.json:
        payload = {
            "entries": len(entries),
            "weeks": sorted({e.week for e in entries}),
            "first": entries[0].date if entries else None,
            "last": entries[-1].date if entries else None,
            "config": cfg,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    render.head("weekly-report 状态")
    render.kv([("仓库", _root()),
               ("配置", "已初始化" if config.config_exists() else "未初始化（可跑 init）"),
               ("日报", "%d 份" % len(entries)),
               ("周报", "%d 份" % _count_weekly(cfg)),
               ("覆盖", "%s ~ %s" % (entries[0].date, entries[-1].date) if entries else "—")])
    if entries:
        render.head("近 3 周")
        for wk in sorted({e.week for e in entries}, reverse=True)[:3]:
            wk_entries = store.entries_for_week(entries, wk)
            counts: Dict[str, int] = {}
            for e in wk_entries:
                for k, v in archive.status_counts(e).items():
                    counts[k] = counts.get(k, 0) + v
            render.out("  [bold]%s[/bold]  %d 份日报" % (wk, len(wk_entries)))
            render.out(render.bar(counts, width=16))
    return 0


def _count_weekly(cfg: Dict) -> int:
    d = os.path.join(_root(), cfg.get("reports_dir", "reports"), "weekly")
    return len([f for f in os.listdir(d) if f.endswith(".md")]) if os.path.isdir(d) else 0


def cmd_sync(args) -> int:
    root = _root()
    if not gitutil.is_repo(root):
        render.err("这不是一个 git 仓库")
        return 1
    files = gitutil.status_porcelain(root)
    if not files:
        render.info("工作区干净，没有需要提交的改动")
        return 0
    message = args.message or "chore(reports): 归档日报与周报 [%s]" % \
        __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
    render.head("待提交")
    for f in files:
        render.out("  %s" % f)
    if not args.yes:
        if not render.prompt_confirm("提交这些改动？", True):
            render.warn("已取消")
            return 1
    okc, out = gitutil.commit(root, message)
    if not okc:
        render.err("提交失败：%s" % out)
        return 1
    render.ok("已提交：%s" % gitutil.last_commit_summary(root))
    if args.no_push:
        render.info("已跳过 push（--no-push）")
        return 0
    branch = gitutil.current_branch(root)
    okp, pout = gitutil.push(root, branch)
    if okp:
        render.ok("已推送到 origin/%s" % branch)
    else:
        render.err("push 失败（提交已在本地，未丢失）：%s" % pout)
        return 1
    return 0


def cmd_lint(args) -> int:
    root = _root()
    entries = _load()
    problems: List[str] = []

    for e in entries:
        if not e.raw_text.strip():
            problems.append("%s: 缺少逐字原文" % e.date)
        if e.week != week_of(parse_date(e.date)):
            problems.append("%s: ISO 周标记错误（%s）" % (e.date, e.week))
        dpath = archive.daily_path(root, e, config.load_config())
        if not os.path.exists(dpath):
            problems.append("%s: 缺少归档文件 %s" % (e.date, os.path.relpath(dpath, root)))
        else:
            with open(dpath, encoding="utf-8") as fh:
                if e.raw_text.strip() and e.raw_text.strip() not in fh.read():
                    problems.append("%s: 归档文件里的原文与数据不一致" % e.date)

    cfg = config.load_config()
    wkdir = os.path.join(root, cfg.get("reports_dir", "reports"), "weekly")
    if os.path.isdir(wkdir):
        for f in sorted(os.listdir(wkdir)):
            if not f.endswith(".md"):
                continue
            wk = f[:-3]
            if not store.entries_for_week(entries, wk):
                problems.append("周报 %s 没有对应日报数据" % wk)

    if args.json:
        print(json.dumps({"problems": problems}, ensure_ascii=False, indent=2))
        return 1 if problems else 0
    if problems:
        render.head("发现问题 %d 处" % len(problems))
        for p in problems:
            render.err(p)
        return 1
    render.ok("lint clean — %d 份日报、%d 份周报，0 问题" % (len(entries), _count_weekly(cfg)))
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="把每日报告归档，并生成/维护周报。",
        epilog="示例： wreport daily add < 日报.txt ｜ wreport weekly build --week 2026-W39",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="command", metavar="<命令>")

    s = sub.add_parser("init", help="交互式初始化配置")
    s.add_argument("--yes", "-y", action="store_true", help="用当前值直接写入，不提问")
    s.add_argument("--non-interactive", action="store_true", help="同 --yes")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    s.set_defaults(func=cmd_init)

    d = sub.add_parser("daily", help="日报归档")
    dsub = d.add_subparsers(dest="subcommand", metavar="<子命令>")

    da = dsub.add_parser("add", help="录入一份日报（默认读 stdin）")
    da.add_argument("--date", help="报告日期 YYYY-MM-DD（默认今天）")
    da.add_argument("--file", help="从文件读取")
    da.add_argument("--text", help="直接给定文本")
    da.add_argument("--source", default="manual", help="来源标记（默认 manual）")
    da.add_argument("--yes", "-y", action="store_true", help="不确认，直接写入")
    da.add_argument("--json", action="store_true", help="输出 JSON")
    da.set_defaults(func=cmd_daily_add)

    dl = dsub.add_parser("list", help="列日报")
    dl.add_argument("--week", help="只看某个 ISO 周，如 2026-W39")
    dl.add_argument("--json", action="store_true", help="输出 JSON")
    dl.set_defaults(func=cmd_daily_list)

    ds = dsub.add_parser("show", help="显示某天日报")
    ds.add_argument("date", help="YYYY-MM-DD")
    ds.add_argument("--json", action="store_true", help="输出 JSON")
    ds.set_defaults(func=cmd_daily_show)

    w = sub.add_parser("weekly", help="周报生成")
    wsub = w.add_subparsers(dest="subcommand", metavar="<子命令>")

    wb = wsub.add_parser("build", help="生成某一周的周报")
    wb.add_argument("--week", help="ISO 周，如 2026-W39（默认本周）")
    wb.add_argument("--date", help="按该日期所在周生成")
    wb.add_argument("--polish", action="store_true", help="调用 LLM 润色（可选）")
    wb.add_argument("--force", action="store_true", help="覆盖已存在的周报")
    wb.add_argument("--stdout", action="store_true", help="打到标准输出，不落盘")
    wb.add_argument("--yes", "-y", action="store_true", help="不确认")
    wb.add_argument("--json", action="store_true", help="输出 JSON")
    wb.set_defaults(func=cmd_weekly_build)

    wl = wsub.add_parser("list", help="列周报")
    wl.add_argument("--json", action="store_true", help="输出 JSON")
    wl.set_defaults(func=cmd_weekly_list)

    s = sub.add_parser("ledger", help="进展台账（跨周汇总）")
    s.add_argument("--weeks", type=int, default=4, help="看最近几周（默认 4）")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    s.set_defaults(func=cmd_ledger)

    s = sub.add_parser("status", help="总览")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("sync", help="提交并推送归档改动")
    s.add_argument("-m", "--message", help="提交信息")
    s.add_argument("--no-push", action="store_true", help="只提交不推送")
    s.add_argument("--yes", "-y", action="store_true", help="不确认")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("lint", help="自检数据与归档一致性")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    s.set_defaults(func=cmd_lint)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 0
    if args.command == "daily" and not getattr(args, "subcommand", None):
        p.parse_args(["daily", "--help"])
        return 0
    if args.command == "weekly" and not getattr(args, "subcommand", None):
        p.parse_args(["weekly", "--help"])
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        render.warn("已中断")
        return 130
    except BrokenPipeError:
        return 0
    except Exception as exc:
        render.err("%s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())