"""Terminal output.

Uses rich/questionary when they are importable and degrades to plain text when they are
not -- the tool must keep working in a bare shell, a CI job, or a pipe. All human-facing
formatting lives here so the logic modules stay pure.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, Iterable, List, Optional, Sequence

try:
    from rich.console import Console as _Console
    _RICH = True
except Exception:  # pragma: no cover - optional dependency
    _RICH = False

from .models import STATUS_META, status_emoji, status_label

_console = _Console() if _RICH else None

_STATUS_COLOR = {
    "done": "green",
    "doing": "yellow",
    "todo": "cyan",
    "blocked": "red",
    "unknown": "dim",
}


def _no_color() -> bool:
    return bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()


def out(text: str = "") -> None:
    if _RICH and not _no_color():
        _console.print(text, highlight=False)
    else:
        print(_strip(text))


def _strip(text: str) -> str:
    import re
    return re.sub(r"\[/?[a-zA-Z0-9_# .]+\]", "", text)


def ok(msg: str) -> None:
    out("[green]✅[/green] %s" % msg)


def warn(msg: str) -> None:
    out("[yellow]⚠️ [/yellow] %s" % msg)


def err(msg: str) -> None:
    out("[red]❌[/red] %s" % msg)


def info(msg: str) -> None:
    out("[cyan]ℹ️ [/cyan] %s" % msg)


def head(msg: str) -> None:
    out("")
    out("[bold]%s[/bold]" % msg)


def bar(counts: Dict[str, int], width: int = 24) -> str:
    """■ bar per status, proportional to the largest count."""
    if not counts:
        return "_（无条目）_"
    top = max(counts.values()) or 1
    lines: List[str] = []
    for key in ("done", "doing", "todo", "blocked", "unknown"):
        n = counts.get(key, 0)
        if not n:
            continue
        filled = max(1, round(n / top * width))
        color = _STATUS_COLOR.get(key, "white")
        mark = "■" * filled
        if _RICH and not _no_color():
            lines.append("[%s]%s[/%s]  %s %s  %d"
                         % (color, mark, color, status_emoji(key),
                            status_label(key), n))
        else:
            lines.append("%s  %s %s  %d" % (mark, status_emoji(key),
                                            status_label(key), n))
    return "\n".join(lines)


def table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> None:
    if not rows:
        out("_（无数据）_")
        return
    if _RICH and not _no_color():
        from rich.table import Table
        t = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        for h in headers:
            t.add_column(h)
        for r in rows:
            t.add_row(*[str(c) for c in r])
        _console.print(t)
        return
    widths = [len(str(h)) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    out("  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)))
    out("  ".join("-" * w for w in widths))
    for r in rows:
        out("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


def kv(pairs: Iterable[tuple]) -> None:
    for k, v in pairs:
        out("  [bold]%s[/bold]  %s" % (k, v))


def prompt_text(label: str, default: str = "", echo: bool = True) -> str:
    """Ask for a value; Enter keeps the current one (shown in the prompt)."""
    try:
        import questionary
        ans = questionary.text("%s" % label,
                               default=default or "",
                               qmark="◈").ask()
        return (ans if ans is not None else default) or default
    except Exception:
        shown = " [%s]" % default if default else ""
        try:
            raw = input("%s%s: " % (label, shown)).strip()
        except EOFError:
            return default
        value = raw or default
        if echo:
            out("  → %s" % value)
        return value


def prompt_select(label: str, choices: Sequence[str], default: str = "") -> str:
    """Arrow-key menu (questionary) with a plain numbered fallback."""
    try:
        import questionary
        ans = questionary.select(label, choices=list(choices),
                                 default=default or None,
                                 pointer="●", qmark="◈").ask()
        if ans:
            return ans
    except Exception:
        pass
    out("%s" % label)
    for i, c in enumerate(choices, 1):
        marker = "●" if c == default else "○"
        out("  %s %d) %s" % (marker, i, c))
    try:
        raw = input("选择 [1-%d]: " % len(choices)).strip()
    except EOFError:
        return default or choices[0]
    if not raw:
        return default or choices[0]
    try:
        return choices[int(raw) - 1]
    except (ValueError, IndexError):
        return default or choices[0]


def prompt_confirm(label: str, default: bool = True) -> bool:
    try:
        import questionary
        ans = questionary.confirm(label, default=default, qmark="◈").ask()
        return default if ans is None else bool(ans)
    except Exception:
        suffix = "Y/n" if default else "y/N"
        try:
            raw = input("%s [%s]: " % (label, suffix)).strip().lower()
        except EOFError:
            return default
        if not raw:
            return default
        return raw in ("y", "yes", "是", "1")