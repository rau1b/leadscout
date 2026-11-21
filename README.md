# LeadScout

Finds Indian local businesses with no website or a weak one, audits them, drafts honest pitches, and sends the ones you approve from Gmail at a safe pace. Costs ₹0.

- How it works: [docs/STACK.md](docs/STACK.md)
- Outreach rules it follows: [docs/INDIA_RULES.md](docs/INDIA_RULES.md)

## First-time setup (Windows, PowerShell, in this folder)

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\leadscout init        # creates config.toml: fill in [sender]
```

Optional but recommended, free, no card: a PageSpeed API key.
Google Cloud console > new project > enable "PageSpeed Insights API" > Credentials > Create API key. Copy `.env.example` to `.env` and paste it as `GOOGLE_API_KEY=...`.

Gmail sending, free, no card:
1. Google Cloud console > enable "Gmail API".
2. OAuth consent screen > External > add your Gmail as a test user.
3. Credentials > Create OAuth client ID > Desktop app > download the JSON to `data\gmail_credentials.json`.
4. `.venv\Scripts\leadscout gmail-login`

## Daily routine

Double-click **LeadScout** on your desktop. It opens the dashboard in your browser (http://127.0.0.1:8000).
(Made with `.venv\Scripts\leadscout shortcut`; run that again if you move or rename this folder. `leadscout stop` closes the dashboard.)

1. **Find leads** page: pick a city, optionally a neighbourhood, tick business types, press Find. It searches, checks websites and scores in the background (1 to 5 minutes). Any city or town in India works.
2. Draft pitches (in a second PowerShell window): `.venv\Scripts\leadscout pitch --templates 50`, or `--prepare 50` and type `/pitch-today` in Claude Code.
3. **Pitches** page: filter by area, read, edit, approve. Press **Wrong category** to hide a business that isn't what it claims to be.
4. Send: `.venv\Scripts\leadscout send` and leave it running during 10:00-17:00 IST.
5. **Replies** page: press **Check inbox**, open a reply, pick a ready answer (Price, Send mockup, Call, Examples, Not now), edit it and send. Fill in anything in [square brackets] first.
6. **Deals**: on a lead, record what you quoted and what's been paid. The Deals page totals what you've won, received and are still owed.

Your own ready answers: add them to `config.toml` under `[quick_replies]`, e.g. `"Timeline" = "Most sites go live in a week, {name}."`

Pitches say "here in <your city>" only for leads in your own city; for other cities they say you're based in your city and work across India online.

Run tests with `.venv\Scripts\pytest`.
