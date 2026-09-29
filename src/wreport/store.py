"""Persistence: everything durable lives in `data/` as plain JSON.

Two files, deliberately separate:

* `entries.json` -- the structured facts. One record per day. This is what reports are
  *generated from*, so it must survive any change to rendering.
* `index.json`  -- a derived lookup (week -> dates, counts, last update). Cheap to
  rebuild, handy for fast listings without walking every entry.

Keeping the raw text inside each entry means a report can always be re-rendered, and a
parser fix can be re-applied to history without re-asking the user for anything.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Dict, List, Optional

from .models import Entry, dump_json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))  # .../weekly-report

DATA_DIR = os.path.join(REPO_ROOT, "data")
ENTRIES_PATH = os.path.join(DATA_DIR, "entries.json")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("cannot read %s: %s" % (path, exc)) from exc


def _write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(dump_json(payload))
    os.replace(tmp, path)  # atomic: never leave a half-written data file behind


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

def load_entries() -> List[Entry]:
    raw = _read_json(ENTRIES_PATH, {"entries": []})
    return [Entry.from_dict(d) for d in raw.get("entries", [])]


def save_entries(entries: List[Entry]) -> None:
    ordered = sorted(entries, key=lambda e: e.date)
    _write_json(ENTRIES_PATH, {
        "version": 1,
        "updated_at": _dt.datetime.now().replace(microsecond=0).isoformat(),
        "entries": [e.to_dict() for e in ordered],
    })


def get_entry(entries: List[Entry], date: str) -> Optional[Entry]:
    for e in entries:
        if e.date == date:
            return e
    return None


def upsert_entry(entries: List[Entry], entry: Entry) -> str:
    """Insert or replace by date. Returns 'added' or 'replaced'."""
    for i, e in enumerate(entries):
        if e.date == entry.date:
            entries[i] = entry
            return "replaced"
    entries.append(entry)
    return "added"


def entries_for_week(entries: List[Entry], week: str) -> List[Entry]:
    return sorted([e for e in entries if e.week == week], key=lambda e: e.date)


# ---------------------------------------------------------------------------
# Derived index
# ---------------------------------------------------------------------------

def rebuild_index(entries: List[Entry]) -> Dict:
    weeks: Dict[str, Dict] = {}
    for e in entries:
        w = weeks.setdefault(e.week, {"dates": [], "items": 0})
        w["dates"].append(e.date)
        w["items"] += sum(1 for i in e.items if not i.is_group)
    index = {
        "version": 1,
        "rebuilt_at": _dt.datetime.now().replace(microsecond=0).isoformat(),
        "entry_count": len(entries),
        "first_date": entries[0].date if entries else "",
        "last_date": entries[-1].date if entries else "",
        "weeks": {k: {**v, "dates": sorted(v["dates"])}
                  for k, v in sorted(weeks.items())},
    }
    _write_json(INDEX_PATH, index)
    return index


def load_index() -> Dict:
    return _read_json(INDEX_PATH, {"version": 1, "weeks": {}, "entry_count": 0})