# monday.com Adaptation Guide

## Goal

Adapt Token Optimizer for monday.com engineering: reduce agent token waste across Claude Code and Cursor sessions on Trident repos.

## Priority surfaces

| Surface | Status | Notes |
|---------|--------|-------|
| Claude Code plugin | Ready | Primary install path for engineers |
| Cursor extension | Ready | Status bar + dashboard; needs plugin hooks |
| Codex | Optional | Keep if monday adopts Codex |
| OpenCode / OpenClaw / Hermes | Deprioritized | Upstream parity; enable if needed |

## Customization checklist

### Branding (done)

- [x] Fresh git history
- [x] monday marketplace name: `monday-token-optimizer`
- [x] Lean README + CLAUDE.md
- [x] Upstream docs archived to `docs/archive/`

### monday-specific (todo)

- [ ] Audit defaults tuned for Trident repos (CLAUDE.md, skills, MCP patterns)
- [ ] monday org GitHub URL when repo moves to `mondaycom/`
- [ ] Internal marketplace hosting (if not using personal GitHub)
- [ ] Commercial license resolution (see ATTRIBUTION.md)
- [ ] monday-specific waste detectors (Ignite flags, Vibe MCP bloat, Trident config)
- [ ] Integration with monday agent rules (BigBrain MCP, pr-guardrails)

### Keep from upstream

- Hook architecture (`hooks/`, `measure.py`)
- Smart compaction + checkpoint/restore
- Quality scoring (dual ResourceHealth + SessionEfficiency)
- Local dashboard (no telemetry)
- Detector registry pattern

### Safe to remove later

- `openclaw/`, `hermes/` — if monday doesn't use these platforms
- `docs/archive/UPSTREAM-README.md` — reference only
- `CHECKSUMS.sha256` / release signing — replaced by monday CI when ready

## Install for monday engineers

```
/plugin marketplace add malichididit/token-optimizer-monday
/plugin install token-optimizer@monday-token-optimizer
/token-optimizer
```

## Contact

Repo maintainer: malichididit (amitmali@monday.com)
