# Token Optimizer — monday.com

Internal fork of [Token Optimizer](https://github.com/alexgreensh/token-optimizer) for monday.com engineering. Audits agent context waste, survives compaction, and tracks token spend locally.

## What it does

- **Audit** — scans Claude/Cursor setup for bloated configs, unused skills, MCP overhead
- **Optimize** — smart compaction checkpoints, read deduplication, output compression
- **Measure** — local dashboard with tokens, cost estimates, quality scores
- **Coach** — session history analysis for token-efficient habits

Runs fully local. No telemetry. No network calls (except optional localhost dashboard).

## Quick start

### Claude Code (recommended)

```
/plugin marketplace add malichididit/token-optimizer-monday
/plugin install token-optimizer@monday-token-optimizer
```

Then run `/token-optimizer` once after install.

Enable auto-update: `/plugin` → **Marketplaces** → `monday-token-optimizer` → **Enable auto-update**.

### Cursor

Install the VS Code extension from `vscode-extension/` (see [vscode-extension/README.md](vscode-extension/README.md)). Requires the Claude Code plugin hooks running locally.

### Script install (macOS / Linux)

```bash
git clone https://github.com/malichididit/token-optimizer-monday.git ~/.claude/token-optimizer
bash ~/.claude/token-optimizer/install.sh
```

## Commands

| Command | Purpose |
|---------|---------|
| `/token-optimizer` | Full audit + fix workflow |
| `/token-optimizer quick` | 10-second health check |
| `/token-coach` | 30-day session habit analysis |
| `/token-dashboard` | Open local usage dashboard |

## Repo layout

| Path | Purpose |
|------|---------|
| `skills/` | Agent skills (audit, coach, dashboard) |
| `plugins/token-optimizer/` | Claude Code plugin package |
| `hooks/` | Session hooks (compaction, quality, read-cache) |
| `vscode-extension/` | Cursor/VS Code status bar companion |
| `openclaw/`, `opencode/`, `hermes/` | Platform-specific plugins (optional) |
| `docs/MONDAY.md` | monday.com adaptation notes |

## monday.com focus

This fork prioritizes **Claude Code** and **Cursor** for monday Trident microfrontends and microservices. See [docs/MONDAY.md](docs/MONDAY.md) for adaptation roadmap and conventions.

## License

Upstream code is licensed under [PolyForm Noncommercial 1.0.0](LICENSE). **Commercial use at monday.com requires a separate license from the upstream author** — see [ATTRIBUTION.md](ATTRIBUTION.md).

## Docs

- [docs/MONDAY.md](docs/MONDAY.md) — adaptation guide
- [ATTRIBUTION.md](ATTRIBUTION.md) — upstream credit
- [HOOKS.md](HOOKS.md) — hook reference
- [docs/archive/UPSTREAM-README.md](docs/archive/UPSTREAM-README.md) — original upstream docs
