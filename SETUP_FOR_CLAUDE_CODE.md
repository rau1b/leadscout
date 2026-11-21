# Set up LeadScout on a new Windows PC (instructions for Claude Code)

Paste this file into Claude Code, or say "follow SETUP_FOR_CLAUDE_CODE.md", and it will set up LeadScout for you.
It does what it can by itself and stops to ask you whenever a step needs your browser or your details.

---

## For Claude Code: follow these steps in order

You're setting up LeadScout for a new user on Windows. Read `CLAUDE.md`, `README.md` and `docs/INDIA_RULES.md` first. They hold the hard rules: ₹0 budget, no paid APIs, no automated WhatsApp/SMS/calls, and every send checks the suppression list.
Do every step you can yourself. When a step needs the user's browser or personal details, stop, tell them exactly what to click, and wait. Never put the user's details, keys or `data/` files in git.

### 1. Get the code
- If the repo isn't cloned yet, ask the user for the GitHub URL and run `git clone <url> leadscout`, then work inside that folder.
- Check Python: `python --version` must be 3.12 or newer. If it's missing or older, ask the user to install it from python.org (tick "Add python.exe to PATH") and then restart Claude Code.

### 2. Install
Run these from the project root:
```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\leadscout init
.venv\Scripts\python -m pytest -q
```
All tests must pass. If any fail, fix the cause before you continue.

### 3. Sender details (ask the user)
Ask for their name, business/studio name, city, phone (+91...), Gmail address, and portfolio link (leave it blank if they don't have one).
Write the answers into `[sender]` in `config.toml`. Don't leave any template values like "Your Name" or "+91 90000 00000" behind, because they go into every pitch.

### 4. PageSpeed key (optional, free, no card)
Give the user these steps:
1. Open https://console.cloud.google.com, create a project, and search for "PageSpeed Insights API". Click Enable.
2. Go to APIs & Services > Credentials > Create credentials > API key, and copy the key.
Then copy `.env.example` to `.env` and set `GOOGLE_API_KEY=<their key>`.

### 5. Gmail (needed for sending)
Ask the user which option they want:
- **A. Their own Google Cloud setup (recommended).** In the same Cloud project:
  1. Enable "Gmail API".
  2. Go to OAuth consent screen > External, and add their own Gmail under Test users.
  3. Go to Credentials > Create OAuth client ID > Desktop app, download the JSON, and save it as `data\gmail_credentials.json`.
- **B. The other partner's setup.** The partner adds this user's Gmail as a test user and sends them `gmail_credentials.json` privately (not through GitHub). Save it as `data\gmail_credentials.json`.

Then tell the user to type `! .venv\Scripts\leadscout gmail-login` in Claude Code. It opens a browser to sign in. Google will warn that the app isn't verified; that's expected, so click Continue.

### 6. Desktop shortcut and first check
```
.venv\Scripts\leadscout shortcut
.venv\Scripts\leadscout stats
```
Tell the user to double-click **LeadScout** on their desktop. The dashboard opens at http://127.0.0.1:8000.

### 7. Explain the daily routine
Go through the "Daily routine" section of `README.md` with the user: Find leads > draft pitches (`leadscout pitch --templates 50`, or `--prepare 50` and then `/pitch-today`) > approve on the Pitches page > `leadscout send` during 10:00–17:00 IST > Replies > Deals.
Mention that sending starts at a small daily cap and grows slowly (warm-up), which protects the Gmail account.

### 8. Working as two people (tell the user this)
Each person has a separate database, so neither sees the other's leads or opt-outs.
- Split cities or areas between you so you don't both pitch the same business.
- If anyone asks either of you to stop contacting them, **both** of you run `.venv\Scripts\leadscout optout <email or phone>`.
- Never commit or share `data\` (it holds people's contact details), `config.toml` or `.env`. `.gitignore` already excludes them.
- To get updates later, run `git pull` and then `.venv\Scripts\pip install -e ".[dev]"`.

Once every step is done, give the user a short summary of what's set up and what's still left (for example, if they skipped Gmail).
