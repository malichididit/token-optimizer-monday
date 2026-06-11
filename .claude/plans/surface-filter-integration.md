# Implementation Plan: Surface Filter — Full Dashboard Integration

## Overview

- **Feature**: Global surface filter that lets users view the entire dashboard scoped to a specific Claude surface (Code, Cowork, or All) with rich behavioral insights per surface
- **User Story**: As a monday.com engineer, I want to filter the dashboard by surface so I can see usage trends, cost, and behavioral diagnostics specific to each tool I use — rather than only getting a combined view.
- **Problem**: The surface breakdown currently only appears in the Trends tab as a summary table. Other tabs show Claude Code setup diagnostics that don't differentiate between main sessions and sub-agents, and provide no Cowork-specific insights. Desktop Chat data is server-side only (not locally available for analysis).
- **Solution**: Add a global surface selector in the nav bar. When a surface is selected, all tabs filter to that surface. For Claude Code, show rich behavioral diagnostics (model routing waste, session marathon detection, sub-agent cost, context growth). For Cowork, show behavioral insights (permission interrupts, rate limits, tool efficiency, model choice).

## Data Availability (Investigation Results)

| Surface | Data Source | What's Available |
|---------|------------|-----------------|
| **Claude Code** | `~/.claude/analytics.duckdb` (tables: `messages`, `entities`, `tool_uses`, `user_messages`, `history`, `tasks`) | Per-turn: model, tokens (input/output/cache_read/cache_write/ephemeral), cost, stop_reason, tool_count, thinking, web_search. Per-session: duration, version, num_messages, tool_calls. Per-tool: name, skill, spawned_agent. |
| **Cowork** | `~/Library/Application Support/Claude/local-agent-mode-sessions/*/audit.jsonl` + `local_*.json` | Per-turn: model, tokens, tools, permissions. Per-session: rate_limit_events, permission_requests, duration, tool names. |
| **Desktop Chat** | `buddy-tokens.json` (daily aggregate only) | Single daily total token count. **No per-session data locally.** Conversations stored server-side. |

### Key Classification Discovery

`analytics.duckdb` `is_agent` field does NOT mean "Chat vs Code":
- `is_agent=false` → **Main user session** (the parent Claude Code session) — $861 total spend
- `is_agent=true` → **Sub-agents** (spawned Explore, Plan, guardrail-evaluator) — $118 total spend

**ALL sessions in DuckDB are Claude Code.** There is no Claude.ai/Desktop Chat data here.

## Feature Metadata

| Field | Value |
|-------|-------|
| Type | Enhancement |
| Complexity | Medium |
| Project Type | Standard (Python stdlib + HTML/JS dashboard) |
| Systems Affected | `measure.py` (trends query, insights computation), `dashboard.html` (filter UI, conditional rendering, insight cards) |
| Dependencies | None (existing infrastructure) |
| monday.com Packages | N/A (backend Python tooling) |
| Estimated Tasks | 12 |

## Context References

### Relevant Codebase Files

| File | Lines | Relevance |
|------|-------|-----------|
| `skills/token-optimizer/assets/dashboard.html` | L1676–1688 | Nav bar — where surface selector goes |
| `skills/token-optimizer/assets/dashboard.html` | L2925–3023 | `renderTrends()` — stat rows that should filter by surface |
| `skills/token-optimizer/assets/dashboard.html` | L3870–3930 | `renderHealth()` — Code-specific, needs sub-agent view |
| `skills/token-optimizer/assets/dashboard.html` | L4074–4150 | `renderCoach()` — setup health, needs behavioral insights |
| `skills/token-optimizer/assets/dashboard.html` | L2815–2860 | `renderSectionViews()` — Quick Wins/Habits |
| `skills/token-optimizer/scripts/measure.py` | L9102–9460 | `_query_trends_db()` — returns trends dict |
| `skills/token-optimizer/scripts/measure.py` | L5021–5130 | `generate_standalone_dashboard()` — data assembly |
| `skills/token-optimizer/scripts/measure.py` | L5555–5595 | `generate_auto_recommendations()` — existing diagnostics |
| `skills/token-optimizer/scripts/duckdb_bridge.py` | full file | DuckDB query layer — needs new insight queries |
| `skills/token-optimizer/scripts/cowork_session.py` | full file | Cowork audit.jsonl parsing — needs insight extraction |

### Design Decisions

**What makes sense per surface:**

| Tab | Claude Code | Cowork |
|-----|-------------|--------|
| Overview | Full (startup overhead, context usage, sub-agent breakdown) | Cost summary, session count, model usage, rate limit status |
| Quick Wins | **Behavioral**: Model routing waste ($120 saveable), session marathon alerts | **Behavioral**: Permission automation suggestions, model downgrade opportunities |
| Habits | Data-driven habits: model switching, session splitting, sub-agent efficiency | Task scoping, tool batching, rate limit awareness |
| Trends | Sessions, tokens, cost, model mix, daily chart | Sessions, tokens, duration, tool usage |
| Health | Running sessions, version, hooks | N/A (hide) |
| Coach | Behavioral score: model efficiency + session hygiene + cache effectiveness | Behavioral score: permission overhead + rate limit risk + tool efficiency |
| Manage | Feature toggles | N/A (hide) |

**Key insight**: Both surfaces have rich behavioral data. Claude Code insights come from DuckDB (`messages`, `entities`, `tool_uses`). Cowork insights come from audit.jsonl events. Desktop Chat is limited to a daily counter — show it as a simple stat only, not a filterable surface.

### Derivable Behavioral Insights (Proven from Data)

**Claude Code (from DuckDB):**
| Insight | Query Logic | Dollar Impact |
|---------|-------------|--------------|
| Opus for short answers | `model LIKE '%opus%' AND output_tokens < 200 AND stop_reason = 'end_turn'` | $56 → ~$11 with Sonnet |
| Opus for simple tool dispatch | `model LIKE '%opus%' AND output_tokens < 100 AND stop_reason = 'tool_use'` | $43 → ~$9 with Sonnet |
| Marathon sessions (context bloat) | Sessions with `msgs > 50` and peak context `> 200K` | $256 in 28 sessions |
| Model inertia | `COUNT(DISTINCT model) = 1` per session with `msgs > 5` | 80% never switch |
| Sub-agent overspend | `entities.agent_type` join on messages cost | $118 total (12%) |
| PR guardrail cost | guardrail-evaluator spawns | $23 across 100 evaluators |
| Hourly burn pattern | `EXTRACT(HOUR FROM timestamp)` | Peak 9-15 UTC |
| Cache efficiency | `cache_read_tokens / (cache_read + cache_write + input)` | 94.5% hit rate |
| Thinking mode ROI | `has_thinking` + output length | $403 thinking vs $458 non |

**Cowork (from audit.jsonl):**
| Insight | Source | Value |
|---------|--------|-------|
| Permission interrupts | `system:permission_request` events | 383 total, 7.5/session avg |
| Rate limit proximity | `rate_limit_event` type | 58 events, 0 blocked |
| Model usage | `assistant.message.model` per turn | Opus in 73% of sessions |
| Session duration | `_audit_timestamp` first/last | Longest: 74 min |
| Tool efficiency | `tool_use` content blocks | Top: slack_read_thread (140x) |
| Scheduled vs manual | `sessionType` field | 46 scheduled, 5 manual |

## Implementation Plan

### Phase 1: Surface Filter Infrastructure
**Goal**: Add a global surface filter and per-surface data in the trends payload.

- [x] **Task 1.1**: ADD `dashboard.html` — surface selector UI in nav bar
  - **IMPLEMENT**: Add a segmented control (pill buttons) below the nav tabs with options: "All", "Claude Code", "Cowork". Default to "All". Store the active filter in a global `window.__activeSurface` variable. On click, re-render all visible tabs with the filter applied. Show a small "Desktop Chat: Xk tokens today" badge if `buddy-tokens.json` data exists (informational only, not filterable).
  - **PATTERN**: `dashboard.html:L2949–2960` — pricing tier selector pattern
  - **STYLE**: Use existing `.nav-item` and `.label` CSS patterns. Pill style with `border-radius: 4px`, active state uses `--c-accent-cyan`.
  - **GOTCHA**: Must survive tab switches — store in window global, not DOM state. Only show the filter when multi-surface data exists (don't clutter for Code-only users).
  - **VALIDATE**: Clicking a surface pill updates `window.__activeSurface` and triggers re-render.

- [x] **Task 1.2**: UPDATE `measure.py` `_query_trends_db` — add per-surface trends data
  - **IMPLEMENT**: In addition to `surface_breakdown`, add `per_surface_trends` dict:
    ```python
    "per_surface_trends": {
        "claude-code": {"session_count": N, "total_tokens": N, "total_cost_usd": N, "model_mix": {...}, "daily": [...]},
        "cowork": {"session_count": N, "total_tokens": N, "duration_avg_min": N, "model_mix": {...}}
    }
    ```
    Compute by partitioning `session_rows` by `_classify_surface(jsonl_path)`.
  - **PATTERN**: `measure.py:L9238–9375` — existing session_rows aggregation
  - **GOTCHA**: "All" uses existing combined data. Per-surface `daily` only for Claude Code (Cowork has fewer sessions, daily chart less useful).
  - **VALIDATE**: `trends["per_surface_trends"]["cowork"]["session_count"]` matches Cowork audit file count.

- [x] **Task 1.3**: UPDATE `dashboard.html` `renderTrends` — filter stats by active surface
  - **IMPLEMENT**: Check `window.__activeSurface`. If not "all", use `t.per_surface_trends[surface]` for hero stat cards. Keep surface breakdown table visible in "all" mode only.
  - **PATTERN**: `dashboard.html:L3014–3023` — stat cards
  - **GOTCHA**: Show "No data for this surface" instead of zeros.
  - **VALIDATE**: Selecting "Cowork" shows only Cowork session stats.

### Phase 2: Behavioral Insights Engine
**Goal**: Compute actionable, dollar-denominated behavioral insights from DuckDB and Cowork data.

- [x] **Task 2.1**: ADD `duckdb_bridge.py` — behavioral insight queries
  - **IMPLEMENT**: Add functions to `duckdb_bridge.py`:
    - `model_routing_waste()`: Returns cost of Opus messages where `output_tokens < 200 AND stop_reason = 'end_turn'`, plus Sonnet-equivalent estimate.
    - `marathon_sessions()`: Returns sessions with `msgs > 50`, their peak context size, and total cost.
    - `model_inertia_rate()`: Returns % of sessions (>5 msgs) that never switch models.
    - `subagent_cost_breakdown()`: Returns cost per `agent_type` from entities join.
    - `hourly_spend_pattern()`: Returns cost per hour-of-day.
  - **PATTERN**: Existing `recent_sessions()` function in `duckdb_bridge.py`
  - **GOTCHA**: All queries must handle empty results. Use `is_available()` check before calling.
  - **VALIDATE**: `model_routing_waste()` returns `{"opus_short_cost": 55.94, "sonnet_equiv": 11.19, "savings": 44.75, "msg_count": 583}`

- [x] **Task 2.2**: ADD `cowork_session.py` — behavioral insight extraction
  - **IMPLEMENT**: Add functions:
    - `aggregate_cowork_insights(audit_files)`: Scans all audit.jsonl files and returns:
      - `total_rate_limit_events`, `rate_limit_blocked_count`
      - `total_permission_requests`, `avg_per_session`
      - `model_distribution` (model → session count)
      - `top_tools` (tool_name → use count)
      - `session_durations` (list of durations in minutes)
  - **PATTERN**: Existing `parse_audit_jsonl()` function
  - **GOTCHA**: Handle malformed JSON lines. Skip files with 0 assistant messages.
  - **VALIDATE**: Returns dict with permission_requests=383, rate_limit_events=58.

- [x] **Task 2.3**: ADD `measure.py` — `_compute_behavioral_insights()` orchestrator
  - **IMPLEMENT**: Orchestrate DuckDB and Cowork insight functions into a unified dict:
    ```python
    {
        "claude-code": {
            "model_routing_waste": {...},  # from duckdb_bridge
            "marathon_sessions": {...},
            "model_inertia_pct": N,
            "subagent_breakdown": {...},
            "hourly_pattern": [...],
            "total_spend": N,
            "cache_hit_rate": N
        },
        "cowork": {
            "permission_interrupts": {...},  # from cowork_session
            "rate_limit_status": {...},
            "model_usage": {...},
            "top_tools": {...},
            "session_count": N,
            "avg_duration_min": N
        }
    }
    ```
  - **PATTERN**: `generate_auto_recommendations()` pattern
  - **GOTCHA**: Either source may be unavailable (no DuckDB CLI, no Cowork dir). Return empty sub-dict gracefully.
  - **VALIDATE**: Full dict with both surfaces populated.

- [x] **Task 2.4**: UPDATE `measure.py` `generate_standalone_dashboard` — include behavioral insights
  - **IMPLEMENT**: Call `_compute_behavioral_insights()` and add to dashboard data as `data.behavioral_insights`.
  - **PATTERN**: `measure.py:L5079–5105` — data assembly
  - **VALIDATE**: Dashboard JSON contains `behavioral_insights.claude-code.model_routing_waste`.

### Phase 3: Dashboard Behavioral UI
**Goal**: Display behavioral insights in the dashboard with actionable recommendations.

- [x] **Task 3.1**: UPDATE `dashboard.html` — Claude Code behavioral Quick Wins
  - **IMPLEMENT**: When `window.__activeSurface` is "claude-code" or "all", add a "Behavioral Insights" section to Quick Wins showing:
    - **"Model Routing Waste"**: "583 Opus messages with short answers cost $56. Using Sonnet: ~$11. Save ~$45/month." (from `behavioral_insights.claude-code.model_routing_waste`)
    - **"Marathon Sessions"**: "28 sessions exceeded 50 messages (peak 330K context). Consider splitting with /clear." (from `marathon_sessions`)
    - **"Model Inertia"**: "80% of sessions never switch models. Try /model for simple follow-ups." (from `model_inertia_pct`)
    - **"Sub-Agent Cost"**: "Sub-agents cost $118 (12%). PR guardrails: $23 for 100 runs." (from `subagent_breakdown`)
  - **PATTERN**: `dashboard.html:L2470–2524` — existing recommendation card pattern
  - **STYLE**: Use existing card styles with dollar amounts highlighted in accent color.
  - **VALIDATE**: Quick Wins tab shows model routing waste card with real dollar savings.

- [x] **Task 3.2**: UPDATE `dashboard.html` — Cowork behavioral insights
  - **IMPLEMENT**: When `window.__activeSurface` is "cowork", show in Quick Wins:
    - **"Permission Overhead"**: "383 permission requests (7.5/session avg). Consider auto-approve for trusted tools." (from `behavioral_insights.cowork.permission_interrupts`)
    - **"Rate Limit Status"**: "58 rate checks, 0 blocked. You're approaching limits but not hitting them yet." (from `rate_limit_status`)
    - **"Model Choice"**: "Opus used in 73% of Cowork sessions. Sonnet handles most scheduled tasks well." (from `model_usage`)
    - **"Top Tools"**: Show top 5 MCP tools used in Cowork with call counts. (from `top_tools`)
  - **PATTERN**: Same card pattern as 3.1
  - **VALIDATE**: Cowork filter shows permission overhead card with real numbers.

- [x] **Task 3.3**: UPDATE `dashboard.html` — hide irrelevant tabs per surface
  - **IMPLEMENT**: When `window.__activeSurface` is "cowork", hide: Health, Manage. When "all" or "claude-code", show everything.
  - **GOTCHA**: Auto-navigate to Trends if user is on a hidden tab when switching.
  - **VALIDATE**: Switching to "Cowork" hides Health/Manage tabs.

- [x] **Task 3.4**: UPDATE `dashboard.html` — Coach tab surface-specific scoring
  - **IMPLEMENT**: When surface is "cowork", replace Token Health Score with:
    - "Permission Efficiency": score based on avg permissions per session (lower = better)
    - "Model Efficiency": score based on % of sessions using appropriate model for task type
  - When surface is "claude-code", add behavioral sub-scores alongside existing setup score:
    - "Model Routing": score based on % of Opus messages with short outputs (lower = better)
    - "Session Hygiene": score based on % of sessions under 50 msgs (higher = better)
  - **PATTERN**: `dashboard.html:L4093–4117` — coach hero cards
  - **VALIDATE**: Coach shows behavioral scores for Code, permission/model scores for Cowork.

### Phase 4: Polish & Sync
**Goal**: Persistence, edge cases, and keeping copies in sync.

- [x] **Task 4.1**: UPDATE `dashboard.html` — persist surface filter in localStorage
  - **IMPLEMENT**: Save to `localStorage.setItem('to_surface_filter', value)` on change. Restore on load. Default to "all". Wrap in try/catch for file:// mode.
  - **VALIDATE**: Refresh page, filter persists.

- [x] **Task 4.2**: MIRROR — sync all changes to `plugins/token-optimizer/`
  - **IMPLEMENT**: Copy modified `measure.py`, `duckdb_bridge.py`, `cowork_session.py`, and `dashboard.html` to `plugins/token-optimizer/skills/token-optimizer/`.
  - **VALIDATE**: `diff` shows no differences between both copies.

## Out of Scope

- **Desktop Chat per-session analysis** — data is server-side only. We show the daily `buddy-tokens.json` count as informational. Full Chat analytics would require an Anthropic API for usage history.
- **Topic drift detection** — no message content stored in DuckDB, only metadata. Can't analyze conversation topics.
- **Quality/satisfaction signals** — no way to know if output quality justified model choice.
- **Real-time filtering** — dashboard is static HTML with embedded JSON. All filtering is client-side.
- **Hermes surface** — 0 sessions on this machine; infrastructure supports it if data appears.
- **CCD (Claude Code in Desktop)** — only 2 sessions exist locally, too new to analyze.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| DuckDB insight queries are slow | Dashboard generation takes >30s | Add timeout per query (5s). Cache results. Each query is simple aggregate — should be fast. |
| Behavioral insights feel prescriptive/wrong | User ignores recommendations | Ground every insight in actual dollar amounts from THEIR data. Show raw numbers, not just advice. |
| Dashboard HTML grows large with insight data | Slow page load | Insight data is small (a few KB of aggregates). No full session dumps in payload. |
| Cowork audit.jsonl parsing is slow (51 files) | Measure.py takes too long | Each file is small (<2.5MB). Full scan takes <2s even on cold disk. |
| Surface filter confuses Code-only users | UI clutter | Default to "All". Filter pills only appear when multi-surface data exists. |
| Model routing advice is wrong for complex tasks | Bad recommendations | Qualify: "583 short-answer Opus messages" — user can judge if those were truly simple. Show msg count + avg output length. |

## Testing Strategy

### Unit Tests
- `model_routing_waste()` with mock DuckDB data
- `aggregate_cowork_insights()` with synthetic audit.jsonl files
- `_compute_behavioral_insights()` with both sources unavailable (graceful empty)
- `_classify_surface()` edge cases

### Integration Tests
- `generate_standalone_dashboard()` includes `per_surface_trends` and `behavioral_insights`
- Dashboard HTML renders without JS errors in all filter states
- Tab hiding/showing works when switching surfaces
- Dollar amounts in insights match raw DuckDB queries

### Edge Cases
- User has only Claude Code sessions (Cowork empty) — filter shows only "All" and "Claude Code", Cowork pill hidden or greyed
- User has 0 DuckDB data but Cowork exists — Code insights empty, Cowork works
- DuckDB CLI not installed — all Code behavioral insights gracefully empty
- Cowork dir doesn't exist — Cowork insights gracefully empty
- Very few sessions (<5) in a surface — show "Not enough data for reliable insights"
- First-time user — no data at all, show helpful "Run some sessions first" message

## Validation Commands

**Level 1 — Syntax**
```bash
cd skills/token-optimizer/scripts && python3 -c "import measure; import duckdb_bridge; import cowork_session; print('ok')"
```

**Level 2 — Insight Data**
```bash
cd skills/token-optimizer/scripts && python3 -c "
from duckdb_bridge import model_routing_waste, marathon_sessions, is_available
if is_available():
    w = model_routing_waste()
    print(f'Model routing waste: {w[\"msg_count\"]} msgs, \${w[\"savings\"]:.2f} saveable')
    m = marathon_sessions()
    print(f'Marathon sessions: {len(m)} sessions, \${sum(s[\"cost\"] for s in m):.2f} total')
from cowork_session import aggregate_cowork_insights
ci = aggregate_cowork_insights()
print(f'Cowork: {ci[\"total_permission_requests\"]} permissions, {ci[\"total_rate_limit_events\"]} rate limits')
"
```

**Level 3 — Full Dashboard**
```bash
cd skills/token-optimizer/scripts && python3 measure.py dashboard
# Open in browser, click each surface filter:
# - "All" shows combined view (current behavior, no regression)
# - "Claude Code" shows behavioral insights in Quick Wins + Coach
# - "Cowork" shows permission/rate-limit insights, hides Health/Manage
```

## Acceptance Criteria

- [ ] Global surface filter (All / Claude Code / Cowork) visible in dashboard nav
- [ ] Filter pills hidden when only one surface has data
- [ ] Trends tab stats filter correctly when a surface is selected
- [ ] Claude Code Quick Wins shows: model routing waste ($), marathon session alerts, model inertia %, sub-agent cost breakdown
- [ ] Cowork Quick Wins shows: permission interrupt count, rate limit status, model usage, top tools
- [ ] Coach tab shows behavioral scores per surface (not just setup health)
- [ ] Health/Manage tabs hidden when Cowork is selected
- [ ] Desktop Chat daily token count shown as informational badge (not a filterable surface)
- [ ] All dollar amounts match actual DuckDB data
- [ ] Filter persists across page refreshes (localStorage)
- [ ] "All" view is identical to current behavior (no regression)
- [ ] No JS errors in any filter state
- [ ] Graceful handling when DuckDB/Cowork unavailable
- [ ] Both `skills/` and `plugins/token-optimizer/` copies in sync

## Completion Checklist

- [ ] All tasks above are checked off
- [ ] All validation levels pass
- [ ] All acceptance criteria met
- [ ] Code follows project patterns (verified against Context References)
- [ ] No temporary code, debug logs, or TODOs left behind
- [ ] Both `skills/` and `plugins/token-optimizer/` copies kept in sync
