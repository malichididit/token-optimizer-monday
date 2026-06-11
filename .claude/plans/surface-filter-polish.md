# Implementation Plan: Surface Filter Polish & Completeness

## Overview

- **Feature**: Fix positioning, filtering gaps, and content overlap in the surface filter
- **User Story**: As a user switching between Claude Code and Cowork views, I want each surface to show only its relevant data — with no bleed-through from other surfaces — and I want the filter to be prominently positioned.
- **Problem**: Four issues with the initial surface filter implementation:
  1. Filter pills are buried below nav items instead of being prominently placed under the brand title
  2. Trends tab still shows Code-specific data (daily breakdown, skills, model mix) when Cowork is selected
  3. Medium/Deep/Habits tabs have no Cowork-specific content — they show nothing or Code content
  4. Coach tab has sections (Issues Detected, Working Well, Compaction Guide, Subagent Spend, Costly Prompts) that are Code-specific but don't hide when Cowork is selected
- **Solution**: Reposition the filter, gate all Trends sub-sections by surface, generate Cowork-specific recommendations for Medium/Deep/Habits, and conditionally show/hide Coach sections by surface.

## Feature Metadata

| Field | Value |
|-------|-------|
| Type | Enhancement (polish pass) |
| Complexity | Medium |
| Project Type | Standard (Python stdlib + HTML/JS dashboard) |
| Systems Affected | `dashboard.html` (layout, renderTrends, renderSectionViews, renderCoach), `measure.py` (auto-recommendations) |
| Dependencies | None |
| monday.com Packages | N/A |
| Estimated Tasks | 8 |

## Context References

### Relevant Codebase Files

| File | Lines | Relevance |
|------|-------|-----------|
| `skills/token-optimizer/assets/dashboard.html` | L1706–1732 | Nav HTML — surface filter position needs to move up |
| `skills/token-optimizer/assets/dashboard.html` | L206–240 | CSS for `.surface-filter` — may need style adjustments |
| `skills/token-optimizer/assets/dashboard.html` | L3315–3520 | `renderTrends()` — surface breakdown, model mix, daily breakdown, skills used, never-used skills — all need surface gating |
| `skills/token-optimizer/assets/dashboard.html` | L4365–4560 | `renderCoach()` — pattern cards, compaction guide, subagent spend, costly prompts — Code-specific sections |
| `skills/token-optimizer/assets/dashboard.html` | L2939–3034 | `renderSectionViews()` — renders Quick Wins/Medium/Deep/Habits from `items` array (from auto_plan) |
| `skills/token-optimizer/scripts/measure.py` | L5555–5700 | `generate_auto_recommendations()` — rules engine that produces the plan items; needs Cowork-specific rules |
| `skills/token-optimizer/scripts/measure.py` | L5553 | `_compute_behavioral_insights()` — already computed, can be used for recommendation generation |

### Design Decisions

**Issue 1 — Filter position**: Move `<div class="surface-filter">` and `<div class="surface-badge">` from below `.nav-menu` to directly below `.brand` (before `.nav-menu`). This makes it the first thing you see after the title.

**Issue 2 — Trends bleed-through**: The following sections in `renderTrends` should be hidden when `activeSurface === 'cowork'`:
- Model Mix (uses `t.model_mix` which is Code-only aggregated data)
- Daily Breakdown (uses `t.daily` which contains Code sessions)
- Skills Used (Code-only concept)
- Never-Used Skills (Code-only concept)

For Cowork surface, show instead: model distribution from `behavioral_insights.cowork.model_usage` and top tools from `behavioral_insights.cowork.top_tools`.

**Issue 3 — Empty Medium/Deep/Habits for Cowork**: The `items` array comes from `parsePlan(data.plan)` which only has Code-focused auto-recommendations. Two options:
- Option A: Generate Cowork-specific `auto_plan_cowork` in `measure.py` and conditionally use it
- Option B: Show the behavioral insight cards in those tabs when Cowork is selected (similar to Quick Wins)

**Chosen: Option A** — Generate a separate Cowork auto_plan with recommendations like "Auto-approve trusted MCP tools", "Consider Sonnet for scheduled tasks", "Batch tool calls to reduce rate limit pressure". Display these items when Cowork is selected.

**Issue 4 — Coach overlap**: These Coach sections are Code-specific and should hide when `activeSurface === 'cowork'`:
- "Issues Detected" / "Working Well" / "Setup Summary" (from `c.patterns_bad/good` — these are about CLAUDE.md, skills, MCP config)
- "When to Compact" (Code concept, Cowork doesn't have /compact)
- "Subagent Spend" (Code concept)
- "Most Expensive Prompts" (Code concept)

When Cowork is selected, show instead: a Cowork-specific summary card with session stats, tool efficiency, and scheduling patterns.

## Implementation Plan

### Phase 1: Filter Repositioning
**Goal**: Move surface filter to prominent position below brand.

- [x] **Task 1.1**: UPDATE `dashboard.html` — move surface filter HTML above nav-menu
  - **IMPLEMENT**: Move `<div class="surface-filter hidden" id="surface-filter">` and `<div class="surface-badge hidden" id="surface-badge-chat">` from their current position (after `.nav-menu` closes) to directly after the `.brand` div and before `.nav-menu` opens. The HTML structure should be: `.brand` → `.surface-filter` → `.surface-badge` → `.nav-menu`.
  - **PATTERN**: `dashboard.html:L1710` — brand div
  - **STYLE**: Add `margin-bottom: 8px;` to `.surface-filter` for breathing room before the nav items. Remove the `border-top` from `.surface-filter` CSS since it's no longer below the menu — and add `margin-top: 6px` instead.
  - **VALIDATE**: Surface filter pills appear directly below "Token Optimizer" title, above the nav tab links.

### Phase 2: Trends Surface Gating
**Goal**: Hide Code-specific Trends sections when Cowork is selected; show Cowork-relevant data instead.

- [x] **Task 2.1**: UPDATE `dashboard.html` `renderTrends` — gate Model Mix by surface
  - **IMPLEMENT**: Wrap the Model Mix section (starts at `if (modelTotal > 0)`) with a surface check: only render when `activeSurface !== 'cowork'`. When `activeSurface === 'cowork'`, render a "Model Usage" card using `data.behavioral_insights.cowork.model_usage` showing a bar chart of model distribution from Cowork sessions.
  - **PATTERN**: `dashboard.html:L3367–3405` — model mix rendering
  - **GOTCHA**: `model_mix` from `t` is the combined/Code-only mix. Cowork model data comes from `data.behavioral_insights.cowork.model_usage` which is `{model_name: session_count}`.
  - **VALIDATE**: Switching to "Cowork" shows Cowork model distribution; switching to "Code" or "All" shows the original model mix.

- [x] **Task 2.2**: UPDATE `dashboard.html` `renderTrends` — gate Daily Breakdown by surface
  - **IMPLEMENT**: Wrap the Daily Breakdown section (`if (daily.length > 0)`) with: only render when `activeSurface !== 'cowork'`. For Cowork, show a simpler "Session Summary" card with total sessions, avg duration, and a note that Cowork sessions don't have per-day granularity in the same format.
  - **PATTERN**: `dashboard.html:L3407–3425` — daily breakdown
  - **GOTCHA**: Cowork `per_surface_trends.cowork.daily` exists but has fewer entries. Show it if available, otherwise show the summary card.
  - **VALIDATE**: Switching to "Cowork" hides the Claude Code daily table.

- [x] **Task 2.3**: UPDATE `dashboard.html` `renderTrends` — gate Skills sections by surface
  - **IMPLEMENT**: Wrap both "Skills Used" and "Never Used" sections with `if (activeSurface !== 'cowork')`. When Cowork is selected, replace with a "Top MCP Tools" card showing `data.behavioral_insights.cowork.top_tools` as a bar chart (tool name → call count).
  - **PATTERN**: `dashboard.html:L3427–3520` — skills sections
  - **GOTCHA**: Skills are a Claude Code concept. Cowork has "tools" (MCP tool calls) instead.
  - **VALIDATE**: Switching to "Cowork" shows top tools instead of skills.

### Phase 3: Cowork Recommendations
**Goal**: Generate actionable Cowork-specific items for Medium/Deep/Habits tabs.

- [x] **Task 3.1**: ADD `measure.py` — `_generate_cowork_auto_recommendations()` function
  - **IMPLEMENT**: Add a function that takes `behavioral_insights` and returns `(plan_markdown, count)` in the same format as `generate_auto_recommendations`. Generate items based on:
    - **Quick Wins**: (already handled by behavioral insight cards)
    - **Medium**: "Auto-approve trusted tools" if avg_per_session permissions > 5. "Use Sonnet for scheduled tasks" if Opus dominates model usage (>70%).
    - **Deep**: "Reduce rate-limit pressure with tool batching" if rate_limit_events > 20. "Consolidate MCP tool sources" if >10 distinct tools used.
    - **Habits**: "Check session duration" if avg > 60min. "Review scheduled vs manual ratio" based on session patterns. "Monitor rate limit trajectory".
  - **PATTERN**: `measure.py:L5555–5553` — `generate_auto_recommendations` format
  - **GOTCHA**: Must return the same markdown format (`## Quick Wins\n\n- [ ] **bold title**: description`) so `parsePlan()` in the dashboard can parse it.
  - **VALIDATE**: Function returns non-empty plan with correct section headings.

- [x] **Task 3.2**: UPDATE `measure.py` `generate_standalone_dashboard` — include Cowork plan
  - **IMPLEMENT**: After computing `behavioral_insights`, also call `_generate_cowork_auto_recommendations(behavioral_insights)` and store the result in `data["cowork_plan"]`. This is a separate field from `data["plan"]` (which is the Code plan).
  - **PATTERN**: `measure.py:L5228–5253` — data dict assembly
  - **VALIDATE**: Dashboard JSON contains `cowork_plan` key with markdown.

- [x] **Task 3.3**: UPDATE `dashboard.html` `renderSectionViews` — use cowork_plan when Cowork selected
  - **IMPLEMENT**: At the top of `renderSectionViews`, check `window.__activeSurface`. If `'cowork'`, parse `data.cowork_plan` instead of `data.plan` for the `items` array. The parsed items then flow through the same rendering logic. If `cowork_plan` is empty/null, show a friendly "Cowork doesn't generate optimization items yet" message in Medium/Deep, and show the behavioral cards in Habits.
  - **PATTERN**: `dashboard.html:L2939–2945` — section rendering entry
  - **GOTCHA**: The `items` variable is module-scoped. Either re-parse locally or use a separate `coworkItems` variable for rendering.
  - **VALIDATE**: Switching to "Cowork" shows Cowork-specific recommendations in Medium/Deep/Habits.

### Phase 4: Coach Surface Isolation
**Goal**: Hide Code-specific Coach content when Cowork is selected; show Cowork summary instead.

- [x] **Task 4.1**: UPDATE `dashboard.html` `renderCoach` — gate Code-specific sections
  - **IMPLEMENT**: Wrap the following sections with `if (activeSurface !== 'cowork')`:
    - "Issues Detected" (`patterns_bad`) — these are about CLAUDE.md, MCP, skills
    - "Working Well" / "Setup Summary" (`patterns_good`) — same
    - "When to Compact" (`compaction_guide`) — Code-only concept
    - "Subagent Spend" (`subagent_costs`) — Code-only
    - "Most Expensive Prompts" (`costly_prompts`) — Code-only
  When `activeSurface === 'cowork'`, render instead:
    - A "Cowork Health Summary" card showing: session count, avg duration, permission rate, rate limit status, top 3 tools used (from `data.behavioral_insights.cowork`)
    - A "Cowork Tips" card with static guidance: "Cowork doesn't have CLAUDE.md/skills overhead — its efficiency is driven by model choice, permission flow, and tool selection."
  - **PATTERN**: `dashboard.html:L4465–4560` — coach section blocks
  - **GOTCHA**: The Health Score hero + Snapshot Summary + Behavioral Scores at the top should still show (they're already surface-aware from Task 3.4 of the previous plan). Only the lower sections need gating.
  - **VALIDATE**: Switching to "Cowork" shows only: health score, behavioral scores, and Cowork health summary. No Code-specific pattern cards, compaction guide, or subagent spend.

### Phase 5: Sync
**Goal**: Keep plugin mirror in sync.

- [x] **Task 5.1**: MIRROR — sync all changes to `plugins/token-optimizer/`
  - **IMPLEMENT**: Copy `dashboard.html`, `measure.py` to `plugins/token-optimizer/skills/token-optimizer/`.
  - **VALIDATE**: `diff` shows no differences.

## Out of Scope

- Cowork per-day session table (Cowork has fewer sessions, a daily breakdown table adds little value)
- Cowork cost estimation (audit.jsonl doesn't expose per-turn cost; we'd have to estimate from model + tokens which is unreliable without knowing cache tier)
- Re-computing Coach health score per surface (the setup score is surface-agnostic — it measures CLAUDE.md/skills/MCP config)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Moving filter position breaks CSS alignment on narrow screens | Visual glitch | Test at 900px width; filter pills are small and wrap naturally |
| `cowork_plan` parsing fails silently | Empty Medium/Deep tabs | Use try/catch + show friendly "no items" state, same as current empty state |
| Coach sections reference variables that don't exist in Cowork context | JS error | All gating uses `if (activeSurface !== 'cowork')` which prevents the Code path from running |

## Testing Strategy

### Manual Verification
- Click "All" → all tabs show combined/current behavior (no regression)
- Click "Code" → Trends shows Code model mix, daily breakdown, skills. Coach shows full Code content.
- Click "Cowork" → Trends shows Cowork model distribution + top tools. No daily table or skills. Coach shows behavioral scores + Cowork summary only. Medium/Deep/Habits show Cowork recommendations.
- Refresh page → filter persists
- Single-surface user (Code-only) → filter pills hidden

### Edge Cases
- `cowork_plan` is null/empty → graceful "no items" state
- `behavioral_insights.cowork` is empty → Cowork Trends sections show "Not enough data"
- All pills work correctly on refresh after being set to any value

## Validation Commands

**Level 1 — Syntax**
```bash
cd skills/token-optimizer/scripts && python3 -c "import measure; import duckdb_bridge; import cowork_session; print('ok')"
```

**Level 2 — Cowork Plan Generation**
```bash
cd skills/token-optimizer/scripts && python3 -c "
from measure import _compute_behavioral_insights, _generate_cowork_auto_recommendations
bi = _compute_behavioral_insights()
plan, count = _generate_cowork_auto_recommendations(bi)
print(f'Cowork recommendations: {count} items')
print(plan[:300])
"
```

**Level 3 — Full Dashboard**
```bash
cd skills/token-optimizer/scripts && python3 measure.py dashboard
# Open and verify each surface filter state
```

## Acceptance Criteria

- [ ] Surface filter pills positioned directly below "Token Optimizer" brand title
- [ ] Switching to "Cowork" hides: Model Mix, Daily Breakdown, Skills Used, Never-Used Skills in Trends
- [ ] Cowork Trends shows: model distribution card and top tools card instead
- [ ] Medium/Deep/Habits tabs show Cowork-specific recommendations when Cowork filter active
- [ ] Coach tab hides Code-specific sections (patterns, compaction, subagents, costly prompts) for Cowork
- [ ] Coach tab shows Cowork health summary when Cowork selected
- [ ] "All" view is identical to current behavior (no regression)
- [ ] No JS errors in any filter state
- [ ] Both `skills/` and `plugins/token-optimizer/` copies in sync

## Completion Checklist

- [ ] All tasks above are checked off
- [ ] All validation levels pass
- [ ] All acceptance criteria met
- [ ] Code follows project patterns (verified against Context References)
- [ ] No temporary code, debug logs, or TODOs left behind
- [ ] Both `skills/` and `plugins/token-optimizer/` copies kept in sync
