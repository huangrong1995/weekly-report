"""Optional LLM polish.

Design constraint borrowed from my-daily-news: collection and generation are
deterministic scripts; the model is only ever asked to *reword* something that has
already been produced. Therefore:

* This module never invents facts -- it receives finished markdown and returns reworded
  markdown.
* Any failure (no key, no network, bad response) is swallowed by the caller and the
  deterministic text is used instead. Polishing must never be a single point of failure.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, Optional

SYSTEM_PROMPT = (
    "You are a technical editor for a Chinese engineering weekly report. "
    "Rewrite the report so it reads crisply and professionally. Rules: "
    "never add facts, never drop an item, never change a status marker or emoji, "
    "keep every markdown heading and bullet, keep the language Chinese. "
    "Return only the rewritten markdown."
)


def polish(markdown: str, cfg: Dict, timeout: Optional[int] = None) -> str:
    """Return reworded markdown, or raise. Callers must fall back on failure."""
    llm = cfg.get("llm", {})
    base = (llm.get("base_url") or "").rstrip("/")
    model = llm.get("model") or ""
    if not base or not model:
        raise RuntimeError("llm.base_url / llm.model not configured")

    import os
    key = os.environ.get(llm.get("api_key_env", "WREPORT_API_KEY"), "").strip()
    if not key:
        raise RuntimeError("API key env %r is empty" % llm.get("api_key_env"))

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": markdown},
        ],
        "temperature": 0.2,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        base + "/chat/completions", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout or llm.get("timeout_s", 60)) as resp:
        body = json.loads(resp.read().decode("utf-8", "replace"))
    text = body["choices"][0]["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("empty completion")
    return text.strip()