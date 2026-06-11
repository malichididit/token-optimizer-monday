#!/usr/bin/env python3
"""DuckDB analytics bridge for Token Optimizer.

Reads ~/.claude/analytics.duckdb via the `duckdb` CLI subprocess to import
cross-surface session data (Chat, Code, Cowork) into the trends pipeline.

Uses subprocess + JSON output to avoid any pip dependency on duckdb.
Opens the database in read-only mode to prevent lock conflicts with
the running Claude Desktop app.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

ANALYTICS_DB = Path.home() / ".claude" / "analytics.duckdb"


def _duckdb_cli() -> str | None:
    """Return the path to the duckdb CLI binary, or None if not found."""
    return shutil.which("duckdb")


def is_available() -> bool:
    """True if both the analytics DB file and the duckdb CLI exist."""
    return ANALYTICS_DB.exists() and _duckdb_cli() is not None


def _query_duckdb(sql: str) -> list[dict[str, Any]]:
    """Run a SQL query against analytics.duckdb via CLI and return parsed rows.

    Returns an empty list on any failure (missing CLI, timeout, parse error).
    """
    cli = _duckdb_cli()
    if not cli:
        return []
    if not ANALYTICS_DB.exists():
        return []

    try:
        proc = subprocess.run(
            [cli, "-readonly", "-json", "-c", sql, str(ANALYTICS_DB)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return []
        output = proc.stdout.strip()
        if not output:
            return []
        rows = json.loads(output)
        if isinstance(rows, list):
            return rows
        return []
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []


def recent_sessions(days: int = 30) -> list[dict[str, Any]]:
    """Query analytics.duckdb for per-session aggregated token data.

    Groups by session_id, is_agent, and project. Returns a list of row dicts
    with totals suitable for normalize_session().
    """
    if not is_available():
        return []

    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    sql = f"""
        SELECT
            session_id,
            is_agent,
            MODE(model) as model,
            MIN(timestamp) as first_ts,
            MAX(timestamp) as last_ts,
            COUNT(*) as message_count,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
            COALESCE(SUM(cache_creation_tokens), 0) as cache_creation_tokens,
            COALESCE(SUM(cache_ephemeral_1h), 0) as cache_ephemeral_1h,
            COALESCE(SUM(cache_ephemeral_5m), 0) as cache_ephemeral_5m,
            COALESCE(SUM(est_cost_usd), 0) as est_cost_usd,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(tool_count), 0) as tool_count,
            project
        FROM messages
        WHERE timestamp >= '{cutoff}'
        GROUP BY session_id, is_agent, project
        ORDER BY first_ts DESC
    """

    return _query_duckdb(sql)


def normalize_session(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map a DuckDB aggregated row to the canonical session dict.

    Returns the same shape as cowork_session.parse_audit_jsonl /
    measure.py _parse_session_jsonl.
    """
    if not row:
        return None

    input_tokens = int(row.get("input_tokens") or 0)
    output_tokens = int(row.get("output_tokens") or 0)
    cache_read = int(row.get("cache_read_tokens") or 0)
    cache_create = int(row.get("cache_creation_tokens") or 0)
    cache_1h = int(row.get("cache_ephemeral_1h") or 0)
    cache_5m = int(row.get("cache_ephemeral_5m") or 0)
    total_tokens = int(row.get("total_tokens") or 0)
    message_count = int(row.get("message_count") or 0)
    model = row.get("model") or "unknown"
    is_agent = str(row.get("is_agent", "false")).lower() in ("true", "1", "t")
    project = row.get("project") or ""
    session_id = row.get("session_id") or ""

    total_full_input = input_tokens + cache_read + cache_create

    cache_hit_rate = 0.0
    denom = input_tokens + cache_read
    if denom > 0:
        cache_hit_rate = cache_read / denom

    # Duration from first_ts / last_ts
    duration_minutes = 0.0
    first_ts = row.get("first_ts")
    last_ts = row.get("last_ts")
    if first_ts and last_ts:
        from datetime import datetime

        try:
            ft = first_ts.rstrip("Z")
            lt = last_ts.rstrip("Z")
            if "+" not in ft[10:]:
                ft += "+00:00"
            if "+" not in lt[10:]:
                lt += "+00:00"
            dt_first = datetime.fromisoformat(ft)
            dt_last = datetime.fromisoformat(lt)
            delta = (dt_last - dt_first).total_seconds()
            duration_minutes = max(0.0, delta / 60.0)
        except (ValueError, TypeError):
            pass

    model_usage = {model: total_tokens} if model and total_tokens else {}

    slug = f"chat:{session_id}" if not is_agent else f"agent:{session_id}"
    topic = project or ("Claude Chat" if not is_agent else "Claude Agent")

    return {
        "version": "duckdb-import",
        "slug": slug,
        "topic": topic,
        "duration_minutes": duration_minutes,
        "total_input_tokens": total_full_input,
        "total_output_tokens": output_tokens,
        "total_cache_read": cache_read,
        "total_cache_create": cache_create,
        "total_cache_create_1h": cache_1h,
        "total_cache_create_5m": cache_5m,
        "cache_hit_rate": cache_hit_rate,
        "avg_call_gap_seconds": None,
        "max_call_gap_seconds": None,
        "p95_call_gap_seconds": None,
        "model_usage": model_usage,
        "model_usage_breakdown": {},
        "skills_used": {},
        "subagents_used": {},
        "tool_calls": {},
        "message_count": message_count,
        "api_calls": message_count,
        "first_ts": first_ts,
        "est_cost_usd": float(row.get("est_cost_usd") or 0),
        "is_agent": is_agent,
        "session_id": session_id,
    }



def model_routing_waste(days: int = 30) -> dict[str, Any]:
    """Find Opus messages with short outputs that could have used Sonnet.

    Returns {opus_short_cost, sonnet_equiv, savings, msg_count} or empty dict.
    """
    if not is_available():
        return {}

    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    sql = f"""
        SELECT
            COUNT(*) as msg_count,
            COALESCE(SUM(est_cost_usd), 0) as total_cost
        FROM messages
        WHERE timestamp >= '{cutoff}'
          AND model LIKE '%opus%'
          AND output_tokens < 200
          AND (stop_reason = 'end_turn' OR stop_reason = 'tool_use')
    """
    rows = _query_duckdb(sql)
    if not rows or not rows[0].get("msg_count"):
        return {"opus_short_cost": 0, "sonnet_equiv": 0, "savings": 0, "msg_count": 0}

    msg_count = int(rows[0]["msg_count"])
    opus_cost = float(rows[0]["total_cost"] or 0)
    sonnet_equiv = opus_cost * 0.2
    return {
        "opus_short_cost": round(opus_cost, 2),
        "sonnet_equiv": round(sonnet_equiv, 2),
        "savings": round(opus_cost - sonnet_equiv, 2),
        "msg_count": msg_count,
    }


def marathon_sessions(days: int = 30) -> list[dict[str, Any]]:
    """Find sessions with >50 messages indicating context bloat.

    Returns list of {session_id, message_count, total_tokens, cost}.
    """
    if not is_available():
        return []

    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    sql = f"""
        SELECT
            session_id,
            COUNT(*) as message_count,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(est_cost_usd), 0) as cost
        FROM messages
        WHERE timestamp >= '{cutoff}' AND is_agent = false
        GROUP BY session_id
        HAVING COUNT(*) > 50
        ORDER BY cost DESC
    """
    rows = _query_duckdb(sql)
    return [
        {
            "session_id": r.get("session_id", ""),
            "message_count": int(r.get("message_count", 0)),
            "total_tokens": int(r.get("total_tokens", 0)),
            "cost": round(float(r.get("cost", 0)), 2),
        }
        for r in rows
    ]


def model_inertia_rate(days: int = 30) -> dict[str, Any]:
    """Percentage of sessions (>5 msgs) that never switch models.

    Returns {single_model_sessions, total_sessions, inertia_pct}.
    """
    if not is_available():
        return {}

    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    sql = f"""
        SELECT
            session_id,
            COUNT(DISTINCT model) as model_count
        FROM messages
        WHERE timestamp >= '{cutoff}' AND is_agent = false
        GROUP BY session_id
        HAVING COUNT(*) > 5
    """
    rows = _query_duckdb(sql)
    if not rows:
        return {"single_model_sessions": 0, "total_sessions": 0, "inertia_pct": 0}

    total = len(rows)
    single = sum(1 for r in rows if int(r.get("model_count", 0)) == 1)
    return {
        "single_model_sessions": single,
        "total_sessions": total,
        "inertia_pct": round(100 * single / max(total, 1), 1),
    }


def subagent_cost_breakdown(days: int = 30) -> dict[str, Any]:
    """Cost breakdown by agent type from entities + messages.

    Returns {total_agent_cost, total_main_cost, pct_of_total}.
    """
    if not is_available():
        return {}

    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    sql = f"""
        SELECT
            is_agent,
            COALESCE(SUM(est_cost_usd), 0) as cost
        FROM messages
        WHERE timestamp >= '{cutoff}'
        GROUP BY is_agent
    """
    rows = _query_duckdb(sql)
    if not rows:
        return {}

    main_cost = 0.0
    agent_cost = 0.0
    for r in rows:
        is_agent_val = str(r.get("is_agent", "false")).lower() in ("true", "1", "t")
        c = float(r.get("cost", 0))
        if is_agent_val:
            agent_cost = c
        else:
            main_cost = c

    total = main_cost + agent_cost
    return {
        "total_agent_cost": round(agent_cost, 2),
        "total_main_cost": round(main_cost, 2),
        "pct_of_total": round(100 * agent_cost / max(total, 0.01), 1),
    }


def hourly_spend_pattern(days: int = 30) -> list[dict[str, Any]]:
    """Cost per hour-of-day for identifying peak usage hours.

    Returns list of {hour, cost, message_count} for hours 0-23.
    """
    if not is_available():
        return []

    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    sql = f"""
        SELECT
            EXTRACT(HOUR FROM CAST(timestamp AS TIMESTAMP)) as hour,
            COALESCE(SUM(est_cost_usd), 0) as cost,
            COUNT(*) as message_count
        FROM messages
        WHERE timestamp >= '{cutoff}'
        GROUP BY EXTRACT(HOUR FROM CAST(timestamp AS TIMESTAMP))
        ORDER BY hour
    """
    rows = _query_duckdb(sql)
    return [
        {
            "hour": int(r.get("hour", 0)),
            "cost": round(float(r.get("cost", 0)), 2),
            "message_count": int(r.get("message_count", 0)),
        }
        for r in rows
    ]
