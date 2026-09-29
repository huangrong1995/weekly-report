"""Configuration: `data/config.json`, created interactively by `wreport init`.

Defaults are chosen so the tool is useful with zero configuration -- an uninitialised
repo still archives and generates reports. `init` only exists to capture the things a
tool cannot guess: whose reports these are, which weekday the week starts on, and
whether an LLM is allowed to polish the prose.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from .store import CONFIG_PATH, _read_json, _write_json

DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "owner": "",
    "week_start": "monday",
    "language": "zh",
    "reports_dir": "reports",
    # Status given to a line that carries no marker, sits under no section, and
    # contains no outcome word. Stays "unknown" unless the author explicitly opts in:
    # the default must never invent a status. Set it to "done" if your reports are
    # plain lists of what you finished today.
    "unmarked_status": "unknown",
    "auto_commit": False,
    "llm": {
        # Polish is optional and off by default: the deterministic path must always
        # work, and an unreachable model must never block a report from being written.
        "enabled": False,
        "provider": "openai-compatible",
        "base_url": "",
        "model": "",
        "api_key_env": "WREPORT_API_KEY",
        "timeout_s": 60,
    },
    "weekly_sections": ["done", "doing", "todo", "plan", "summary"],
}


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    cfg["llm"] = dict(DEFAULTS["llm"])
    stored = _read_json(CONFIG_PATH, {})
    if isinstance(stored, dict):
        for k, v in stored.items():
            if k == "llm" and isinstance(v, dict):
                cfg["llm"].update(v)
            else:
                cfg[k] = v
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    _write_json(CONFIG_PATH, cfg)


def config_exists() -> bool:
    return os.path.exists(CONFIG_PATH)


def llm_ready(cfg: Dict[str, Any]) -> bool:
    """True only when polish is switched on AND credentials look present."""
    llm = cfg.get("llm", {})
    if not llm.get("enabled"):
        return False
    if not llm.get("base_url"):
        return False
    return bool(os.environ.get(llm.get("api_key_env", ""), "").strip())