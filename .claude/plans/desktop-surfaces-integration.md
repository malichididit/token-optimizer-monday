# Implementation Plan: Claude Desktop Surfaces Integration (Cowork + analytics.duckdb)

## Overview

- **Feature**: Extend Token Optimizer to cover Cowork sessions and Claude Desktop analytics (Chat + Code + Cowork) via `analytics.duckdb`
- **User Story**: As a monday.com engineer, I want Token Optimizer to show me token spend and waste across all Claude Desktop surfaces — not just CLI sessions — so I have full visibility into my AI usage.
- **Problem**: Token Optimizer only scans `~/.claude/projects/*.jsonl` (CLI sessions). Cowork sessions (51 found) live under `~/Library/Application Support/Claude/local-agent-mode-sessions/` in a different JSONL format. Regular Claude Chat sessions (~$861 spend) are locked in IndexedDB but their token data is available in `~/.claude/analytics.duckdb`.
- **Solution**: Add a Cowork session adapter (like the existing Codex/Hermes adapters) + a DuckDB analytics reader that imports cross-surface token data into trends.db.

## Feature Metadata

| Field | Value |
|-------|-------|
| Type | Feature |
| Complexity | Medium |
| Project Type | Standard (Python stdlib + DuckDB CLI) |
| Systems Affected | `runtime_env.py`, `measure.py`, new `cowork_session.py`, new `duckdb_bridge.py` |
| Dependencies | `duckdb` CLI (already installed on this machine) |
| monday.com Packages | N/A (backend Python tooling) |
| Estimated Tasks | 14 |

## Context References

### Relevant Codebase Files

| File | Lines | Relevance |
|------|-------|-----------|
| `skills/token-optimizer/scripts/runtime_env.py` | L26–49, L152–185 | Runtime detection — needs `desktop` and `cowork` signals |
| `skills/token-optimizer/scripts/measure.py` | L184–191 | Adapter dispatch helpers — add `_use_cowork_session_adapter()` |
| `skills/token-optimizer/scripts/measure.py` | L6806–6828 | `_find_all_jsonl_files` — add Cowork scan |
| `skills/token-optimizer/scripts/measure.py` | L7107–7349 | `_parse_session_jsonl` — reference for parser output dict shape |
| `skills/token-optimizer/scripts/measure.py` | L8659–8759 | `_collect_hermes_sessions` — template for non-JSONL adapter in `collect_sessions` |
| `skills/token-optimizer/scripts/measure.py` | L8770–8930 | `collect_sessions` — main orchestrator, add Cowork + DuckDB branches |
| `skills/token-optimizer/scripts/measure.py` | L7607–7704 | trends.db schema — `session_log` columns |
| `skills/token-optimizer/scripts/measure.py` | L5014–5279 | `generate_standalone_dashboard` — add surface breakdown tab data |
| `skills/token-optimizer/scripts/codex_session.py` | L208–238, L284–458 | Codex adapter — structural template for Cowork adapter |
| `skills/token-optimizer/scripts/hermes_session.py` | full | Hermes adapter — template for DB-sourced sessions |

### New Files to Create

| File | Purpose |
|------|---------|
| `skills/token-optimizer/scripts/cowork_session.py` | Cowork `audit.jsonl` discovery + parser, returns canonical session dict |
| `skills/token-optimizer/scripts/duckdb_bridge.py` | Reads `~/.claude/analytics.duckdb` via `duckdb` CLI subprocess, returns aggregated per-session data |

### Patterns to Follow

**Pattern: Adapter dispatch**
Found in: `measure.py` (lines 184–191)
```python
def _use_codex_session_adapter(filepath=None):
    return detect_runtime() == "codex" or (filepath is not None and codex_session.is_codex_session_path(filepath))

def _use_hermes_session_adapter():
    return detect_runtime() == "hermes"
```
Apply to: Add `_use_cowork_session_adapter()` that detects Cowork audit.jsonl by path pattern.

**Pattern: Session file discovery**
Found in: `codex_session.py` (lines 208–238)
```python
def find_all_jsonl_files(days=30, max_files=500):
    cutoff = datetime.now().timestamp() - (days * 86400)
    results = []
    for root in session_roots():
        for jf in itertools.islice(root.rglob("*.jsonl"), max_files):
            mtime = jf.stat().st_mtime
            if mtime >= cutoff:
                results.append((jf, mtime, project))
    results.sort(key=lambda x: x[1], reverse=True)
    return results
```
Apply to: `cowork_session.find_all_audit_files()` scanning `local-agent-mode-sessions/**/audit.jsonl`.

**Pattern: Hermes DB-sourced collection**
Found in: `measure.py` (lines 8659–8759)
```python
def _collect_hermes_sessions(days=90, quiet=False, rebuild=False):
    rows = _hs.recent_sessions(days=days)
    for row in rows:
        parsed = hermes_session.normalize_session(row)
        dedup_key = f"hermes:{slug}"
        if _is_file_collected(conn, dedup_key):
            continue
        conn.execute("INSERT OR IGNORE INTO session_log ...", (...))
```
Apply to: `_collect_duckdb_sessions()` importing from analytics.duckdb with `duckdb:` dedup prefix.

**Pattern: Canonical session dict**
Found in: `measure.py` (lines 7326–7349)
```python
return {
    "total_input_tokens": total_full_input,
    "total_output_tokens": total_output,
    "total_cache_read": total_cache_read,
    "cache_hit_rate": cache_hit_rate,
    "model_usage": model_usage,
    "duration_minutes": duration_minutes,
    "message_count": message_count,
    "api_calls": api_calls,
    "skills_used": {}, "subagents_used": {}, "tool_calls": {},
    "version": version, "slug": slug, "topic": topic,
}
```
Apply to: Both `cowork_session.parse_audit_jsonl()` and `duckdb_bridge.normalize_session()` must return this shape.

### Data Sources Discovered on This Machine

| Source | Path | Format | Sessions | Token data |
|--------|------|--------|----------|------------|
| Claude Code CLI | `~/.claude/projects/*/*.jsonl` | JSONL | 672 | Per-message `usage` |
| Cowork | `~/Library/Application Support/Claude/local-agent-mode-sessions/{accountId}/{orgId}/local_*/audit.jsonl` | JSONL | 51 (109 JSONL total) | `usage` in `result/success` messages |
| analytics.duckdb | `~/.claude/analytics.duckdb` | DuckDB | 257 sessions, 11,314 messages | `input_tokens`, `output_tokens`, `cache_*`, `est_cost_usd`, `model`, `is_agent` |

### analytics.duckdb Schema (messages table)

```
entity_id         varchar     session_id            uuid
project           varchar     is_agent              boolean
model             varchar     timestamp             varchar
input_tokens      bigint      output_tokens         bigint
cache_read_tokens bigint      cache_creation_tokens bigint
cache_ephemeral_5m bigint     cache_ephemeral_1h    bigint
web_search_requests bigint    web_fetch_requests    bigint
service_tier      varchar     stop_reason           varchar
has_thinking      boolean     tool_count            bigint
msg_id            varchar     request_id            varchar
total_tokens      bigint      est_cost_usd          double
```

### Cowork audit.jsonl Format

Records have `type` field: `user`, `assistant`, `system/init`, `system/status`, `system/permission_request`, `system/permission_response`, `result/success`, `rate_limit_event`.

Token usage lives in `result/success` messages:
```json
{
  "type": "result",
  "subtype": "success",
  "usage": {
    "input_tokens": 20,
    "cache_creation_input_tokens": 71640,
    "cache_read_input_tokens": 952504,
    "output_tokens": 13090,
    "service_tier": "standard"
  }
}
```

Session metadata from `system/init`:
```json
{
  "type": "system",
  "subtype": "init",
  "cwd": "...",
  "session_id": "f7f83a88-...",
  "tools": ["Task", "Edit", "Glob", ...]
}
```

## Implementation Plan

### Phase 1: Cowork Session Adapter
**Goal**: Discover and parse Cowork `audit.jsonl` files into the canonical session dict format.

- [x] **Task 1.1**: CREATE `cowork_session.py` — session discovery
  - **IMPLEMENT**: Create `skills/token-optimizer/scripts/cowork_session.py` with:
    - `COWORK_SESSIONS_BASE` = `Path.home() / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"` (macOS) with Linux fallback `~/.config/Claude/local-agent-mode-sessions`
    - `find_all_audit_files(days=30)` → walks `{base}/**/audit.jsonl`, filters by mtime, returns `list[(Path, float, str)]` matching `_find_all_jsonl_files` return type. The `project` string should be the Cowork session UUID extracted from the parent dir name (`local_{uuid}` → `cowork:{uuid}`).
    - `is_cowork_audit_path(path)` → True if path is under `local-agent-mode-sessions/` and named `audit.jsonl`
  - **PATTERN**: `codex_session.py:L208–238` — same `find_all_jsonl_files` shape
  - **IMPORTS**: `pathlib.Path`, `datetime`, `json`, `sys`, `platform`
  - **GOTCHA**: macOS uses `~/Library/Application Support/Claude/`, Linux uses `~/.config/Claude/`. Check `sys.platform`.
  - **VALIDATE**: `python3 -c "import cowork_session; print(len(cowork_session.find_all_audit_files(90)))"` prints ~51

- [x] **Task 1.2**: ADD `cowork_session.py` — audit.jsonl parser
  - **IMPLEMENT**: Add `parse_audit_jsonl(filepath)` that:
    1. Streams lines, parses JSON
    2. Extracts `session_id` from `system/init` record
    3. Counts `user` and `assistant` messages for `message_count`
    4. Extracts `usage` dict from `result/success` records — sum `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` across all result messages (multiple API calls per session)
    5. Extracts tools list from `system/init` → `tools` array for `tool_calls` dict
    6. Computes `duration_minutes` from first/last `_audit_timestamp` fields
    7. Extracts `model` from assistant messages (field `message.model` or default `claude-sonnet-4-6`)
    8. Returns canonical dict matching `measure.py:L7326–7349` shape
  - **PATTERN**: `measure.py:L7107–7349` — same streaming JSONL parse + dedup logic
  - **IMPORTS**: `json`, `pathlib`, `datetime`
  - **GOTCHA**: Cowork uses `cache_read_input_tokens` and `cache_creation_input_tokens` (matching Claude Code naming), but may have multiple `result/success` per session — sum them all. Also handle the case where `_audit_timestamp` is missing.
  - **VALIDATE**: Parse a known Cowork audit.jsonl and verify `total_input_tokens > 0` and `message_count > 0`

- [x] **Task 1.3**: ADD `cowork_session.py` — per-turn parser
  - **IMPLEMENT**: Add `parse_session_turns(filepath)` returning a list of dicts with `role`, `tokens`, `model`, `cost_usd`, `timestamp` per message — needed for the dashboard Sessions tab detail view.
  - **PATTERN**: `codex_session.py:L461+` — same return shape
  - **GOTCHA**: Cowork has `assistant` records without inline usage — correlate with the subsequent `result/success` record that carries the `usage` block for that turn.
  - **VALIDATE**: Returns list with len > 0 for a non-empty audit.jsonl

### Phase 2: DuckDB Analytics Bridge
**Goal**: Read `analytics.duckdb` to import cross-surface session data (Chat, Code, Cowork) into trends.db.

- [x] **Task 2.1**: CREATE `duckdb_bridge.py` — DuckDB reader via CLI subprocess
  - **IMPLEMENT**: Create `skills/token-optimizer/scripts/duckdb_bridge.py` with:
    - `ANALYTICS_DB` = `Path.home() / ".claude" / "analytics.duckdb"`
    - `_query_duckdb(sql)` → runs `duckdb -json -c "{sql}" {db_path}` via `subprocess.run`, parses JSON output. Returns `list[dict]`. Handles `FileNotFoundError` (no `duckdb` CLI) gracefully.
    - `is_available()` → True if both the DB file and `duckdb` CLI exist
  - **IMPORTS**: `subprocess`, `json`, `pathlib`, `shutil` (for `shutil.which("duckdb")`)
  - **GOTCHA**: Use `subprocess.run` with `capture_output=True, text=True, timeout=30`. The DuckDB CLI outputs JSON arrays. Must open DB as read-only to avoid lock conflicts with the running Claude Desktop app — use `duckdb -readonly`.
  - **VALIDATE**: `python3 -c "import duckdb_bridge; print(duckdb_bridge.is_available())"` prints `True`

- [x] **Task 2.2**: ADD `duckdb_bridge.py` — session aggregation query
  - **IMPLEMENT**: Add `recent_sessions(days=30)` that queries:
    ```sql
    SELECT
      session_id,
      is_agent,
      model,
      MIN(timestamp) as first_ts,
      MAX(timestamp) as last_ts,
      COUNT(*) as message_count,
      SUM(input_tokens) as input_tokens,
      SUM(output_tokens) as output_tokens,
      SUM(cache_read_tokens) as cache_read_tokens,
      SUM(cache_creation_tokens) as cache_creation_tokens,
      SUM(cache_ephemeral_1h) as cache_ephemeral_1h,
      SUM(cache_ephemeral_5m) as cache_ephemeral_5m,
      SUM(est_cost_usd) as est_cost_usd,
      SUM(total_tokens) as total_tokens,
      SUM(tool_count) as tool_count,
      project
    FROM messages
    WHERE timestamp >= '{cutoff_iso}'
    GROUP BY session_id, is_agent, project
    ORDER BY first_ts DESC
    ```
    Returns list of row dicts. Each row is one session.
  - **GOTCHA**: `timestamp` is ISO string in DuckDB, cutoff must be formatted as ISO. The `is_agent` boolean separates Chat (`false`) from Code/Cowork (`true`).
  - **VALIDATE**: Returns > 0 rows; sum of `est_cost_usd` across all rows should be ~$979

- [x] **Task 2.3**: ADD `duckdb_bridge.py` — normalize to canonical session dict
  - **IMPLEMENT**: Add `normalize_session(row)` that maps a DuckDB aggregated row to the canonical dict:
    - `total_input_tokens` = `input_tokens + cache_read_tokens + cache_creation_tokens`
    - `total_output_tokens` = `output_tokens`
    - `total_cache_read` = `cache_read_tokens`
    - `total_cache_create_1h` = `cache_ephemeral_1h`
    - `total_cache_create_5m` = `cache_ephemeral_5m`
    - `cache_hit_rate` = `cache_read_tokens / (input_tokens + cache_read_tokens)` if denominator > 0
    - `duration_minutes` = delta between `first_ts` and `last_ts`
    - `model_usage` = `{model: total_tokens}`
    - `slug` = `"chat"` if `not is_agent` else `"agent"`
    - `topic` = `project` or `"Claude Chat"`
    - `version` = `"duckdb-import"`
    - Zero out: `skills_used`, `subagents_used`, `tool_calls` (not available from DuckDB)
  - **PATTERN**: `hermes_session.py` `normalize_session()` — same shape transformation
  - **VALIDATE**: `normalize_session(row)` returns dict with all required keys; `total_input_tokens > 0`

### Phase 3: Integration into measure.py
**Goal**: Wire both new adapters into the collect/dashboard pipeline.

- [x] **Task 3.1**: UPDATE `runtime_env.py` — add `cowork` and `desktop` runtime constants
  - **IMPLEMENT**: Add to `_VALID_RUNTIMES`: no change needed — Cowork runs as a sub-mode of Claude Desktop, not a separate runtime. Instead add a helper `cowork_sessions_dir()` that returns the macOS/Linux `local-agent-mode-sessions` path. Export it.
  - **PATTERN**: `runtime_env.py:L73–80` — `_safe_home_from_env` pattern for safe path resolution
  - **GOTCHA**: Don't make Cowork a full runtime — it co-exists with Claude Code on the same machine. The adapter should always run when the directory exists, regardless of `detect_runtime()`.
  - **VALIDATE**: `python3 -c "from runtime_env import cowork_sessions_dir; print(cowork_sessions_dir())"` prints the correct path

- [x] **Task 3.2**: UPDATE `measure.py` — import new adapters
  - **IMPLEMENT**: Add at line ~99 (alongside existing adapter imports):
    ```python
    import cowork_session
    import duckdb_bridge
    ```
    Add dispatch helpers alongside existing ones at ~L191:
    ```python
    def _use_cowork_session_adapter(filepath=None):
        return filepath is not None and cowork_session.is_cowork_audit_path(filepath)
    ```
  - **PATTERN**: `measure.py:L96–99, L184–191`
  - **VALIDATE**: No import errors when running `python3 -c "import measure"`

- [x] **Task 3.3**: UPDATE `measure.py` `_find_all_jsonl_files` — include Cowork sessions
  - **IMPLEMENT**: After the existing Claude Code project scan (L6811–6828), append Cowork audit files:
    ```python
    # Also scan Cowork (Claude Desktop agent-mode) sessions
    cowork_files = cowork_session.find_all_audit_files(days)
    results.extend(cowork_files)
    results.sort(key=lambda x: x[1], reverse=True)
    ```
    This ensures Cowork sessions flow through the same `collect_sessions` → `_parse_session_jsonl` pipeline.
  - **PATTERN**: How Codex adapter is dispatched at L6808–6809 (early return), but Cowork should be additive (both Claude Code + Cowork on same machine)
  - **GOTCHA**: Don't early-return for Cowork — it's additive, not exclusive. Cowork files should go through `_parse_session_jsonl` with the Cowork adapter, not the default Claude Code parser.
  - **VALIDATE**: `_find_all_jsonl_files(90)` returns > 672 (existing) + some Cowork files

- [x] **Task 3.4**: UPDATE `measure.py` `_parse_session_jsonl` — dispatch to Cowork parser
  - **IMPLEMENT**: At the top of `_parse_session_jsonl(filepath)` (L7107), add:
    ```python
    if cowork_session.is_cowork_audit_path(filepath):
        return cowork_session.parse_audit_jsonl(filepath)
    ```
    Same pattern as the existing Codex dispatch.
  - **PATTERN**: `measure.py:L7107` — existing Codex adapter check
  - **VALIDATE**: Parsing a Cowork audit.jsonl via `_parse_session_jsonl` returns the canonical dict

- [x] **Task 3.5**: ADD `measure.py` — `_collect_duckdb_sessions` function
  - **IMPLEMENT**: Add a new function (near `_collect_hermes_sessions` at ~L8659) that:
    1. Checks `duckdb_bridge.is_available()` — return 0 if not
    2. Calls `duckdb_bridge.recent_sessions(days)`
    3. For each row, normalize via `duckdb_bridge.normalize_session(row)`
    4. Dedup key: `duckdb:{session_id}` (same pattern as `hermes:{slug}`)
    5. Skip if `_is_file_collected(conn, dedup_key)` OR if the session_id already exists in trends.db from a JSONL parse (avoid double-counting Code sessions)
    6. Insert into `session_log` with the same 28-column INSERT
    7. Return new_count
  - **PATTERN**: `measure.py:L8659–8759` — `_collect_hermes_sessions` is the exact template
  - **GOTCHA**: DuckDB sessions overlap with Claude Code JSONL sessions (is_agent=true). Must cross-check `session_uuid` column in existing `session_log` rows to avoid double-counting. Only insert DuckDB rows for sessions NOT already collected from JSONL. Chat sessions (`is_agent=false`) will always be new since they have no JSONL.
  - **VALIDATE**: After running, `session_log` has new rows with `jsonl_path` starting with `duckdb:`

- [x] **Task 3.6**: UPDATE `measure.py` `collect_sessions` — call DuckDB collector
  - **IMPLEMENT**: At the end of `collect_sessions` (after L8920 `_rebuild_aggregate_tables`), add:
    ```python
    # Also collect from analytics.duckdb (Chat + any sessions missed by JSONL)
    duckdb_count = _collect_duckdb_sessions(days=days, quiet=quiet, rebuild=rebuild)
    if duckdb_count and not quiet:
        print(f"[Token Optimizer] Imported {duckdb_count} sessions from analytics.duckdb")
    if duckdb_count:
        _rebuild_aggregate_tables(conn)
        conn.commit()
    ```
    Note: need to re-open `conn` or restructure slightly since `conn.close()` is called at L8925. Move `conn.close()` to after the DuckDB collection.
  - **PATTERN**: How Hermes is dispatched as an early return at L8777–8778
  - **GOTCHA**: DuckDB collection is additive (runs after JSONL), not exclusive (unlike Hermes). Must restructure the conn lifecycle: move `conn.close()` to after DuckDB import.
  - **VALIDATE**: `collect_sessions(days=90)` now prints both JSONL and DuckDB collection counts

### Phase 4: Dashboard Surface Breakdown
**Goal**: Show per-surface spend breakdown in the dashboard.

- [x] **Task 4.1**: UPDATE `measure.py` — add surface tag to session_log rows
  - **IMPLEMENT**: Add a `source` field to the data passed to the dashboard:
    - In `_collect_trends_data` or `_query_trends_db`, classify sessions by `jsonl_path` prefix:
      - `duckdb:` + `is_agent=false` → `"chat"`
      - `duckdb:` + `is_agent=true` → `"desktop-agent"`
      - `hermes:` → `"hermes"`
      - Path contains `local-agent-mode-sessions` → `"cowork"`
      - Everything else → `"claude-code"`
    - Add a `surface_breakdown` dict to the dashboard data: `{"claude-code": {"sessions": N, "tokens": N, "cost": N}, "cowork": {...}, "chat": {...}}`
  - **PATTERN**: `measure.py:L8947` — `_collect_trends_from_db` query pattern
  - **GOTCHA**: Don't modify the `session_log` schema (no new columns). Classify at query time based on `jsonl_path`.
  - **VALIDATE**: Dashboard data includes `surface_breakdown` with non-zero values for at least `claude-code`

- [x] **Task 4.2**: UPDATE dashboard.html — add surface breakdown display
  - **IMPLEMENT**: In the Overview tab of `skills/token-optimizer/assets/dashboard.html`, add a "Spend by Surface" section that renders the `surface_breakdown` data as a horizontal stacked bar or simple table showing sessions, tokens, and cost per surface (Claude Code, Cowork, Chat).
  - **PATTERN**: Existing dashboard tab rendering in `dashboard.html` (search for `renderOverview`)
  - **GOTCHA**: Must also update `plugins/token-optimizer/skills/token-optimizer/assets/dashboard.html` (the plugin copy). Keep them in sync.
  - **VALIDATE**: Open dashboard, see surface breakdown with real data

## Out of Scope

- **Claude Chat transcript parsing** — IndexedDB (LevelDB binary) has no documented schema and no hook surface. Cost data from `analytics.duckdb` is sufficient.
- **Cowork waste detection** — Phase 1 covers data collection only. Waste pattern detectors for Cowork-specific patterns (VM overhead, permission churn, scheduled task waste) is a follow-up.
- **Live Cowork hooks** — Cowork runs in a sandboxed VM. Injecting hooks at runtime requires Desktop Extension integration, which is a separate effort.
- **Windows support** — Cowork path discovery is macOS/Linux only initially.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| DuckDB CLI not available on all monday machines | DuckDB bridge silently does nothing | `is_available()` check + graceful fallback; document `brew install duckdb` in MONDAY.md |
| analytics.duckdb locked by running Claude Desktop | Read fails or hangs | Use `-readonly` flag in DuckDB CLI; subprocess timeout of 30s |
| Double-counting: same session in both JSONL and DuckDB | Inflated token counts in dashboard | Cross-check `session_uuid` in trends.db before inserting DuckDB rows |
| Cowork audit.jsonl format changes in future Desktop updates | Parser breaks silently | Defensive parsing with try/except per record; version detection from `system/init` |

## Testing Strategy

### Unit Tests
- `cowork_session.parse_audit_jsonl()` with a fixture `audit.jsonl` (copy a real one, redact sensitive content)
- `duckdb_bridge.normalize_session()` with mock DuckDB row dicts
- Dedup logic: verify a session already in trends.db from JSONL is NOT re-inserted from DuckDB

### Integration Tests
- `collect_sessions(days=90)` on this machine should increase trends.db row count by ~50+ (Cowork) and ~100+ (DuckDB Chat sessions)
- Dashboard generation should succeed and include `surface_breakdown`

### Edge Cases
- Empty `analytics.duckdb` (new install)
- No Cowork sessions (engineer hasn't used Cowork)
- Cowork session with 0 `result/success` records (cancelled early)
- DuckDB CLI missing from PATH
- Concurrent DuckDB access while Claude Desktop is running

## Validation Commands

**Level 1 — Syntax**
```bash
python3 -c "import cowork_session; import duckdb_bridge; print('imports ok')"
```

**Level 2 — Unit**
```bash
python3 -c "
from cowork_session import find_all_audit_files, parse_audit_jsonl
files = find_all_audit_files(90)
print(f'Found {len(files)} Cowork sessions')
if files:
    parsed = parse_audit_jsonl(files[0][0])
    print(f'Parsed: {parsed[\"message_count\"]} msgs, {parsed[\"total_input_tokens\"]} input tokens')
"
```

```bash
python3 -c "
from duckdb_bridge import is_available, recent_sessions
print(f'DuckDB available: {is_available()}')
if is_available():
    rows = recent_sessions(90)
    print(f'Found {len(rows)} sessions in analytics.duckdb')
"
```

**Level 3 — Integration**
```bash
cd ~/.claude/skills/token-optimizer/scripts  # or plugin cache path
python3 measure.py collect --quiet
python3 measure.py trends --days 30
```

**Level 4 — Dashboard**
```bash
python3 measure.py dashboard
# Verify surface breakdown appears in Overview tab
```

## Acceptance Criteria

- [ ] `collect_sessions` discovers and parses Cowork `audit.jsonl` files alongside Claude Code JSONL
- [ ] `collect_sessions` imports Chat session data from `analytics.duckdb` without double-counting Code sessions
- [ ] Dashboard shows per-surface breakdown (Claude Code / Cowork / Chat) with session counts, tokens, and cost
- [ ] `trends --days 30` output includes Cowork and Chat sessions
- [ ] No errors when `analytics.duckdb` is missing or `duckdb` CLI is not installed (graceful degradation)
- [ ] No errors when Cowork sessions directory doesn't exist
- [ ] Zero new runtime dependencies (uses `duckdb` CLI via subprocess, not a pip package)
- [ ] Both `skills/` and `plugins/token-optimizer/skills/` copies are updated

## Completion Checklist

- [ ] All tasks above are checked off
- [ ] All validation levels pass
- [ ] All acceptance criteria met
- [ ] Code follows project patterns (verified against Context References)
- [ ] No temporary code, debug logs, or TODOs left behind
- [ ] Both `skills/` and `plugins/token-optimizer/` copies kept in sync
