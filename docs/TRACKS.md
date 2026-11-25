# Two tracks

LeadScout 2.0 is built by two people in parallel. Each owns a track: its modules, its dashboard areas, its tests and its config section. The interfaces between the tracks are in [CONTRACTS.md](CONTRACTS.md). The rules are in `CLAUDE.md` under "Working in parallel".

| Track | Owner | Owns | Plan phases |
|---|---|---|---|
| **Find & qualify** | Jason | `sources/`, `enrich/`, `audit/`, `scoring.py`, `pitch/`, `mailer/` (outreach), `compliance.py` | 1, 3 |
| **Show & close** | rau1b | `demos/`, `crm/`, `billing/`, the preview host | 2, 4 |
| Both | together | Phase 5 | 5 |

`pitch/` is in Find & qualify because pitches are built from the audit and scoring facts. `enrich/`, `demos/`, `crm/` and `billing/` don't exist yet; whoever owns the folder creates it.

## Shared files

Change these only in small, separate PRs, and say what you changed in the PR description:

- `src/leadscout/db.py`
- `src/leadscout/migrations/` (see the numbering rule below)
- `src/leadscout/web/app.py`: one import line per dashboard area, nothing else
- `src/leadscout/web/templates/base.html`: the nav (one link per area)
- `config.example.toml`: one `[section]` per track
- `CLAUDE.md`
- Also shared today: `cli.py` (each track adds its own commands) and `web/extras.py` (replies and deals). Move these into a track's own files when that track next changes them.

## Rules (summary)

1. Work only in your track's modules. Anything you need from the other track goes through a contract in [CONTRACTS.md](CONTRACTS.md). Change a contract only with the other person's OK.
2. Each new dashboard area is its own `web/<area>.py`. It registers its routes on the shared `app`, with one import line at the end of `web/app.py`, as `extras.py` and `settings_page.py` do. Its templates and its `tests/test_<area>.py` are its own; don't add to `test_core.py` or `test_fixes.py`.
3. Your settings live in your own `[section]` of `config.example.toml`.
4. Migrations take the next free number when they merge. If the other track's migration landed first, renumber yours before merging. A migration is never edited after it has merged. `tests/test_migrations.py` fails if the numbers have a gap or a duplicate.
5. Open small PRs into `main` every few days, after merging `origin/main` into your branch and passing ruff and the full test suite.
