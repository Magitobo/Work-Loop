"""Collect llama-swap request captures for a finished harness session.

After a session, reads llama-swap's /api/metrics and /api/captures/{id}, keeps the
requests that belong to the session (matched by time window and token counts from the
opencode log), and writes a compact JSONL file next to the session log. Full request
messages are dropped; only sampling params, response text/reasoning and a prompt-prefix
marker (to tell prompt changes from server-side cache drops) are kept.
"""

import base64
import hashlib
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from .utils import _ts

HTTP_TIMEOUT_S = 10
WINDOW_SLACK_S = 5
MAX_TOOL_ARGS_CHARS = 2000
PARAM_KEYS = (
    "temperature", "top_p", "top_k", "min_p", "presence_penalty", "presence_context_size",
    "frequency_penalty", "repetition_penalty", "max_tokens", "chat_template_kwargs", "stream",
)


def capture_path(log_file: Path) -> Path:
    """`x.log` -> `x.llm.jsonl` (not matched by the analyzer's *.log glob)."""
    return log_file.with_name(log_file.stem + ".llm.jsonl")


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as r:
        return json.loads(r.read())


def _parse_ts(s: str) -> datetime | None:
    # Go may emit nanoseconds; fromisoformat accepts at most microseconds.
    s = re.sub(r"(\.\d{6})\d+", r"\1", str(s)).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _step_token_keys(log_file: Path) -> set[tuple[int, int]]:
    """(prompt_tokens, completion_tokens) of every step in an opencode JSON log."""
    keys = set()
    try:
        lines = log_file.read_text(errors="replace").splitlines()
    except OSError:
        return keys
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "step_finish":
            continue
        tokens = (ev.get("part") or {}).get("tokens") or {}
        cache = tokens.get("cache") or {}
        try:
            prompt = int(tokens.get("input", 0)) + int(cache.get("read", 0)) + int(cache.get("write", 0))
            keys.add((prompt, int(tokens.get("output", 0))))
        except (TypeError, ValueError):
            continue
    return keys


def _matches(metric: dict, keys: set[tuple[int, int]]) -> bool:
    t = metric.get("tokens") or {}
    out, inp, cached = t.get("output_tokens"), t.get("input_tokens"), max(t.get("cache_tokens") or 0, 0)
    return any((p, out) in keys for p in (inp, (inp or 0) + cached))


def _decode(b64: str | None) -> str:
    if not b64:
        return ""
    try:
        return base64.b64decode(b64).decode("utf-8", errors="replace")
    except ValueError:
        return ""


def _parse_response(body: str) -> dict:
    """Return content, reasoning, tool calls and finish reason from a JSON or SSE response."""
    content, reasoning, finish, calls = [], [], None, {}
    chunks = []
    if body.lstrip().startswith("{"):
        try:
            chunks = [json.loads(body)]
        except ValueError:
            pass
    else:
        for line in body.splitlines():
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                try:
                    chunks.append(json.loads(line[5:]))
                except ValueError:
                    continue
    for ch in chunks:
        for choice in ch.get("choices") or []:
            part = choice.get("delta") or choice.get("message") or {}
            content.append(part.get("content") or "")
            reasoning.append(part.get("reasoning") or part.get("reasoning_content") or "")
            for tc in part.get("tool_calls") or []:
                c = calls.setdefault(tc.get("index", len(calls)), {"name": "", "arguments": ""})
                fn = tc.get("function") or {}
                c["name"] += fn.get("name") or ""
                c["arguments"] += fn.get("arguments") or ""
            finish = choice.get("finish_reason") or finish
    for c in calls.values():
        c["arguments"] = c["arguments"][:MAX_TOOL_ARGS_CHARS]
    return {"content": "".join(content), "reasoning": "".join(reasoning),
            "tool_calls": list(calls.values()), "finish_reason": finish}


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def collect(base_url: str, log_file: Path, start: datetime, end: datetime) -> Path | None:
    """Write the session's llama-swap captures to capture_path(log_file). Never raises."""
    try:
        base = base_url.rstrip("/")
        keys = _step_token_keys(log_file)
        metrics = _get_json(f"{base}/api/metrics") or []
        lo, hi = start.timestamp() - WINDOW_SLACK_S, end.timestamp() + WINDOW_SLACK_S
        in_window = [m for m in metrics
                     if (ts := _parse_ts(m.get("timestamp", ""))) and lo <= ts.timestamp() <= hi]
        matched = [m for m in in_window if _matches(m, keys)]

        rows, prev_prompt = [], None
        for m in sorted(matched, key=lambda m: m.get("id", 0)):
            row = {"id": m.get("id"), "timestamp": m.get("timestamp"), "model": m.get("model"),
                   "duration_ms": m.get("duration_ms"), "tokens": m.get("tokens"), "captured": False}
            if m.get("has_capture"):
                try:
                    cap = _get_json(f"{base}/api/captures/{m['id']}")
                except Exception:
                    cap = None
                if cap:
                    req = json.loads(_decode(cap.get("req_body")) or "{}")
                    # Tools first, then one line per message, so an append-only turn keeps
                    # the whole previous prompt as its prefix.
                    prompt = "\n".join(json.dumps(x, sort_keys=True, ensure_ascii=False)
                                       for x in [req.get("tools")] + list(req.get("messages") or []))
                    row.update({
                        "captured": True,
                        "params": {k: req[k] for k in PARAM_KEYS if k in req},
                        "n_messages": len(req.get("messages") or []),
                        "tools_hash": hashlib.sha1(json.dumps(req.get("tools"), sort_keys=True).encode()).hexdigest()[:10],
                        "prompt_chars": len(prompt),
                        # == previous prompt_chars: prompt only grew (cache miss is the server's);
                        # smaller: something earlier in the prompt changed.
                        "prefix_match_chars": _common_prefix_len(prev_prompt, prompt) if prev_prompt is not None else None,
                        "response": _parse_response(_decode(cap.get("resp_body"))),
                    })
                    prev_prompt = prompt
            rows.append(row)

        out = capture_path(log_file)
        header = {"type": "header", "source": base, "log": log_file.name, "steps": len(keys),
                  "requests_in_window": len(in_window), "matched": len(matched),
                  "captured": sum(r["captured"] for r in rows)}
        with open(out, "w", encoding="utf-8") as f:
            f.write(json.dumps(header) + "\n")
            for r in rows:
                f.write(json.dumps({"type": "request", **r}, ensure_ascii=False) + "\n")
        return out
    except Exception as e:
        print(f"[{_ts()}] WARNING: llama-swap capture collection failed for {log_file.name}: {e}")
        return None
