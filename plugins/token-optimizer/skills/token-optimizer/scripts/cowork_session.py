#!/usr/bin/env python3
"""Cowork (Claude Desktop agent-mode) session adapter for Token Optimizer.

Claude Desktop's Cowork feature stores sessions under:
  macOS: ~/Library/Application Support/Claude/local-agent-mode-sessions/
  Linux: ~/.config/Claude/local-agent-mode-sessions/

Each session lives in a folder like:
  {accountId}/{orgId}/local_{uuid}/audit.jsonl

This module discovers those files and parses them into the canonical session
dict expected by measure.py's collect_sessions pipeline.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _cowork_sessions_base() -> Path:
    """Return the platform-appropriate Cowork sessions root directory."""
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "local-agent-mode-sessions"
        )
    return Path.home() / ".config" / "Claude" / "local-agent-mode-sessions"


def is_cowork_audit_path(path: str | Path) -> bool:
    """True if path is a Cowork audit.jsonl under local-agent-mode-sessions."""
    p = Path(path) if not isinstance(path, Path) else path
    try:
        parts = p.resolve(strict=False).parts
        return "local-agent-mode-sessions" in parts and p.name == "audit.jsonl"
    except (OSError, ValueError):
        return False


def find_all_audit_files(days: int = 30) -> list[tuple[Path, float, str]]:
    """Find all Cowork audit.jsonl files within the given day window.

    Returns list of (path, mtime, project_label) matching the shape used by
    measure.py's _find_all_jsonl_files.
    """
    base = _cowork_sessions_base()
    if not base.exists():
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    results: list[tuple[Path, float, str]] = []

    for audit_file in base.rglob("audit.jsonl"):
        try:
            mtime = audit_file.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        project = _project_label_from_path(audit_file)
        results.append((audit_file, mtime, project))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _project_label_from_path(audit_path: Path) -> str:
    """Extract a project label from the Cowork directory structure.

    Path shape: .../local-agent-mode-sessions/{accountId}/{orgId}/local_{uuid}/audit.jsonl
    Returns: 'cowork:{uuid}' or 'cowork:unknown'
    """
    parent_name = audit_path.parent.name
    if parent_name.startswith("local_"):
        uuid_part = parent_name[len("local_"):]
        if uuid_part:
            return f"cowork:{uuid_part}"
    return f"cowork:{parent_name}"


def _parse_iso_timestamp(ts_str: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        ts_str = ts_str.rstrip("Z")
        if "+" not in ts_str and "-" not in ts_str[10:]:
            ts_str += "+00:00"
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def parse_audit_jsonl(filepath: str | Path) -> dict[str, Any] | None:
    """Parse a Cowork audit.jsonl file into the canonical session dict.

    Returns the same shape as measure.py's _parse_session_jsonl:
    {total_input_tokens, total_output_tokens, total_cache_read, cache_hit_rate,
     model_usage, duration_minutes, message_count, api_calls, ...}
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return None

    session_id: str | None = None
    tools_list: list[str] = []
    model_set: dict[str, int] = {}
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_create = 0
    total_cache_create_1h = 0
    total_cache_create_5m = 0
    message_count = 0
    api_calls = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                rec_type = record.get("type", "")
                rec_subtype = record.get("subtype", "")

                # Track timestamps for duration
                ts_str = record.get("_audit_timestamp")
                ts = _parse_iso_timestamp(ts_str)
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                # system/init: extract session_id, tools, model
                if rec_type == "system" and rec_subtype == "init":
                    session_id = record.get("session_id") or session_id
                    tools_raw = record.get("tools")
                    if isinstance(tools_raw, list):
                        tools_list = tools_raw
                    continue

                # user messages: count for message_count
                if rec_type == "user":
                    message_count += 1
                    continue

                # assistant messages: extract per-turn usage
                if rec_type == "assistant":
                    message_count += 1
                    api_calls += 1
                    msg = record.get("message") or {}
                    model = msg.get("model", "")
                    usage = msg.get("usage") or {}

                    inp = int(usage.get("input_tokens") or 0)
                    out = int(usage.get("output_tokens") or 0)
                    cr = int(usage.get("cache_read_input_tokens") or 0)
                    cc = int(usage.get("cache_creation_input_tokens") or 0)

                    cache_creation = usage.get("cache_creation") or {}
                    cc_1h = int(cache_creation.get("ephemeral_1h_input_tokens") or 0)
                    cc_5m = int(cache_creation.get("ephemeral_5m_input_tokens") or 0)

                    total_input += inp
                    total_output += out
                    total_cache_read += cr
                    total_cache_create += cc
                    total_cache_create_1h += cc_1h
                    total_cache_create_5m += cc_5m

                    if model:
                        billable = inp + cc + out
                        model_set[model] = model_set.get(model, 0) + billable
                    continue

    except (OSError, UnicodeDecodeError):
        return None

    if api_calls == 0 and message_count == 0:
        return None

    # Full input = uncached + cache reads + cache creation
    total_full_input = total_input + total_cache_read + total_cache_create

    # Cache hit rate
    cache_hit_rate = 0.0
    if total_full_input > 0:
        cache_hit_rate = total_cache_read / total_full_input

    # Duration
    duration_minutes = 0.0
    if first_ts and last_ts:
        delta = (last_ts - first_ts).total_seconds()
        duration_minutes = max(0.0, delta / 60.0)

    # Build tool_calls dict (just presence, count=0 since we don't track per-call)
    tool_calls: dict[str, int] = {}
    for t in tools_list:
        tool_calls[t] = 0

    slug = session_id or _project_label_from_path(filepath)
    topic = "Cowork session"

    return {
        "version": "cowork-v1",
        "slug": slug,
        "topic": topic,
        "duration_minutes": duration_minutes,
        "total_input_tokens": total_full_input,
        "total_output_tokens": total_output,
        "total_cache_read": total_cache_read,
        "total_cache_create": total_cache_create,
        "total_cache_create_1h": total_cache_create_1h,
        "total_cache_create_5m": total_cache_create_5m,
        "cache_hit_rate": cache_hit_rate,
        "avg_call_gap_seconds": None,
        "max_call_gap_seconds": None,
        "p95_call_gap_seconds": None,
        "model_usage": model_set,
        "model_usage_breakdown": {},
        "skills_used": {},
        "subagents_used": {},
        "tool_calls": tool_calls,
        "message_count": message_count,
        "api_calls": api_calls,
        "first_ts": first_ts.isoformat() if first_ts else None,
    }


def parse_session_turns(filepath: str | Path) -> list[dict[str, Any]]:
    """Parse a Cowork audit.jsonl returning per-turn token data.

    Returns a list of dicts per API call:
      {turn_index, role, input_tokens, output_tokens, cache_read,
       cache_creation, cache_creation_1h, cache_creation_5m,
       model, timestamp, tools_used, cost_usd, estimated}
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return []

    turns: list[dict[str, Any]] = []
    turn_index = 0
    prev_ts: datetime | None = None

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                rec_type = record.get("type", "")

                if rec_type != "assistant":
                    continue

                msg = record.get("message") or {}
                usage = msg.get("usage") or {}
                model = msg.get("model", "unknown")
                ts_str = record.get("_audit_timestamp")
                ts = _parse_iso_timestamp(ts_str)

                inp = int(usage.get("input_tokens") or 0)
                out = int(usage.get("output_tokens") or 0)
                cr = int(usage.get("cache_read_input_tokens") or 0)
                cc = int(usage.get("cache_creation_input_tokens") or 0)

                cache_creation = usage.get("cache_creation") or {}
                cc_1h = int(cache_creation.get("ephemeral_1h_input_tokens") or 0)
                cc_5m = int(cache_creation.get("ephemeral_5m_input_tokens") or 0)

                gap: float | None = None
                if prev_ts and ts:
                    gap = (ts - prev_ts).total_seconds()
                if ts:
                    prev_ts = ts

                turns.append({
                    "turn_index": turn_index,
                    "role": "assistant",
                    "input_tokens": inp + cr + cc,
                    "output_tokens": out,
                    "cache_read": cr,
                    "cache_creation": cc,
                    "cache_creation_1h": cc_1h,
                    "cache_creation_5m": cc_5m,
                    "model": model,
                    "timestamp": ts_str,
                    "gap_since_prev_seconds": gap,
                    "tools_used": [],
                    "cost_usd": 0.0,
                    "estimated": False,
                })
                turn_index += 1

    except (OSError, UnicodeDecodeError):
        return []

    return turns



def aggregate_cowork_insights(days: int = 30) -> dict[str, Any]:
    """Scan all Cowork audit.jsonl files and extract behavioral insights.

    Returns:
        {
            total_rate_limit_events: int,
            rate_limit_blocked_count: int,
            total_permission_requests: int,
            avg_per_session: float,
            model_distribution: {model: session_count},
            top_tools: {tool_name: use_count},
            session_durations: [float],  # minutes
            session_count: int,
        }
    """
    audit_files = find_all_audit_files(days=days)
    if not audit_files:
        return {
            "total_rate_limit_events": 0,
            "rate_limit_blocked_count": 0,
            "total_permission_requests": 0,
            "avg_per_session": 0.0,
            "model_distribution": {},
            "top_tools": {},
            "session_durations": [],
            "session_count": 0,
        }

    total_rate_limit = 0
    rate_limit_blocked = 0
    total_permissions = 0
    model_sessions: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    durations: list[float] = []
    valid_sessions = 0

    for audit_path, _, _ in audit_files:
        session_permissions = 0
        session_models: set[str] = set()
        session_tools: dict[str, int] = {}
        first_ts: datetime | None = None
        last_ts: datetime | None = None
        has_assistant = False

        try:
            with open(audit_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    rec_type = record.get("type", "")
                    rec_subtype = record.get("subtype", "")

                    ts_str = record.get("_audit_timestamp")
                    ts = _parse_iso_timestamp(ts_str)
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts

                    if rec_type == "system" and rec_subtype == "permission_request":
                        session_permissions += 1
                        total_permissions += 1
                        continue

                    if rec_type == "rate_limit_event" or rec_subtype == "rate_limit":
                        total_rate_limit += 1
                        if record.get("blocked"):
                            rate_limit_blocked += 1
                        continue

                    if rec_type == "assistant":
                        has_assistant = True
                        msg = record.get("message") or {}
                        model = msg.get("model", "")
                        if model:
                            session_models.add(model)
                        content = msg.get("content") or []
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "tool_use":
                                    tool_name = block.get("name", "unknown")
                                    session_tools[tool_name] = session_tools.get(tool_name, 0) + 1
                        continue

        except (OSError, UnicodeDecodeError):
            continue

        if not has_assistant:
            continue

        valid_sessions += 1
        for m in session_models:
            model_sessions[m] = model_sessions.get(m, 0) + 1
        for tool, cnt in session_tools.items():
            tool_counts[tool] = tool_counts.get(tool, 0) + cnt

        if first_ts and last_ts:
            dur = (last_ts - first_ts).total_seconds() / 60.0
            durations.append(round(max(0.0, dur), 1))

    top_tools = dict(sorted(tool_counts.items(), key=lambda x: -x[1])[:20])

    return {
        "total_rate_limit_events": total_rate_limit,
        "rate_limit_blocked_count": rate_limit_blocked,
        "total_permission_requests": total_permissions,
        "avg_per_session": round(total_permissions / max(valid_sessions, 1), 1),
        "model_distribution": dict(sorted(model_sessions.items(), key=lambda x: -x[1])),
        "top_tools": top_tools,
        "session_durations": durations,
        "session_count": valid_sessions,
    }
