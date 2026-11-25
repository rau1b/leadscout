# LeadScout

Private tool for two people selling websites to **Indian local businesses**. ₹0 budget: only free services (Overture Maps, Nominatim, PageSpeed with a free key, Gmail API, Claude Code on the user's Pro plan). Never add a paid API or the Anthropic API.

- Stack, pipeline, commands: `docs/STACK.md`. Setup: `README.md`.
- Outreach and privacy rules the code must enforce: `docs/INDIA_RULES.md`.
- Product record and dashboard design contract: `PRODUCT.md`, `.impeccable/surfaces/src-leadscout-web.md` (Bahi-khata direction).
- Run things with `.venv/Scripts/leadscout ...` from the project root; tests with `.venv/Scripts/python -m pytest`.

Hard rules:
- Never automate WhatsApp sends, phone calls or SMS. Generate `wa.me` / `mailto:` links for a human.
- Every send and export checks the hashed suppression list first.
- Pitches cite only measured facts; no invented numbers, reviews or claims.
- Respect warm-up caps, IST sending window and the bounce pause in `mailer/sender.py`.
- Tests never hit the network or send email.
- Stop the dashboard before `pip install` (`leadscout stop` for the desktop icon, or Ctrl+C in the terminal running `leadscout serve`); on Windows a running dashboard locks .venv\Scripts\leadscout.exe.

## Working in parallel

Two tracks, two people: see `docs/TRACKS.md` (who owns what) and `docs/CONTRACTS.md` (the interfaces between them).
- Work only in your track's modules. Reach the other track only through a contract in `docs/CONTRACTS.md`; change a contract only with the other person's OK.
- Each new dashboard area is its own `web/<area>.py`. It registers routes on the shared `app` with one import line at the end of `web/app.py`, and has its own templates and `tests/test_<area>.py`. Don't add to `test_core.py` or `test_fixes.py`.
- Each track's settings go in its own `[section]` of `config.example.toml`.
- Shared files (`db.py`, `migrations/`, `web/app.py`, the nav in `base.html`, `config.example.toml`, this file) change only in small, separate PRs.
- Migrations take the next free number at merge time. Renumber yours if another one landed first. Never edit a migration after it has merged. `tests/test_migrations.py` checks the numbers run 1..N with no gaps or duplicates.
- Open small PRs into `main` every few days, after merging `origin/main` and passing ruff and the full test suite.
