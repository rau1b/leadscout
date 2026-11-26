# LeadScout: stack and architecture (₹0 version)

LeadScout finds Indian local businesses with no website or a weak one, audits them, scores them, drafts honest pitches and sends approved emails through Gmail at a safe pace. A human approves every message. It never sends WhatsApp messages, calls or SMS (see `INDIA_RULES.md`).

It runs on one laptop and costs nothing.

## Stack

| Part | Choice | Cost |
|---|---|---|
| Language | Python 3.12+ (venv + pip) | Free |
| Command line | Typer (`leadscout ...`) | Free |
| Business data | **Overture Maps** places (Meta, Microsoft, Foursquare data; open licence) via the `overturemaps` package + DuckDB | Free, no key, no limits |
| Area lookup | OpenStreetMap Nominatim (area name to map box) | Free |
| Your own lists | CSV import (`leadscout import-csv`) | Free |
| Website checks | httpx + BeautifulSoup | Free |
| Speed test | Google PageSpeed Insights API, mobile | Free; needs a free API key (no card) for real volume |
| Google reviews (optional, off) | Google Places API (New): place id stored, details fetched live | Off by default; capped per month |
| Email check | DNS MX lookup (dnspython) | Free |
| Phone numbers | phonenumbers (+91 format, mobile vs landline) | Free |
| Storage | SQLite file `data/leadscout.db` (stdlib sqlite3) | Free |
| Pitches | Built-in templates, or Claude Code `/pitch-today` on your existing Pro plan | ₹0 extra |
| Sending | Gmail API from a free Gmail account, OAuth desktop app | Free |
| Dashboard | FastAPI + Jinja2 + HTMX, self-hosted Mukta font | Free |
| Tests | pytest | Free |

Measured on Kukatpally, Hyderabad (21 Nov 2026): 7,644 places in the area; 80% have a phone, 50% a website, 36% an email address.

## Pipeline

```
leadscout find "dental,interior design" --area "Kukatpally, Hyderabad"
leadscout audit                  # classify site, fetch up to 5 pages (robots.txt obeyed), HTML and tech checks,
                                 # domain dates (RDAP) and certificate expiry, PageSpeed
leadscout pagespeed              # re-run PageSpeed later (e.g. after adding a key)
leadscout score                  # 0-100 score, reasons, best deliverable email, dedupe, chains out
leadscout enrich [--area ...]    # optional: match the best leads on Google Places (see below)
leadscout pitch --templates 50   # or: --prepare 50, then /pitch-today in Claude Code, then --import
leadscout serve                  # dashboard: review, edit, approve
leadscout gmail-login            # one time
leadscout send                   # sends approved emails inside the IST window, warm-up caps
leadscout check-replies          # replies, "no thanks" opt-outs, bounces
leadscout optout <email|phone>   # never contact again
leadscout forget <email|phone>   # delete everything, keep hashed opt-out
leadscout purge                  # delete never-contacted data older than 90 days
leadscout backup                 # copy the database to data/backups/ now
leadscout restore <backup-file>  # put a backup back (dashboard stopped)
leadscout export leads.csv
```

Website classes: none, social_only, directory_only, dead_google_site (business.site), free_subdomain, broken (expired domain = `fetch_error: dns`, HTTP errors, parked pages), real. Bot-protected sites (403/429/503) count as real.

## Searching by city

The dashboard's **Find leads** page queues area searches (city + optional neighbourhood + business types) and runs find, audit and score in a background thread, one search at a time (`searches.py`). Each business stores its `area` and `city`; Leads and Pitches filter by area. A neighbourhood search covers 4 to 7 km; a city without a neighbourhood covers about 13 km around its centre. Places mapped as a single point are widened automatically.

## Google Places (optional)

Off until you turn it on. When on, the best leads get Google's review count and open status in their score, and the lead page gets a **Show Google details** button (rating, reviews, opening hours), shown live with "Data from Google Maps" and never saved.

Google's terms allow keeping only a place's `place_id`. So LeadScout stores just that id (in `source_records`, source `google`). Ratings, review counts, phone numbers, websites, hours and coordinates from Google are fetched when needed and dropped; a test scans every table to check. The score keeps only its own reason, such as "Well reviewed on Google", never Google's numbers.

To turn it on:
1. In Google Cloud console, on the project that has your PageSpeed key, enable **Places API (New)**. The key goes in `.env` as `GOOGLE_API_KEY`, as for PageSpeed.
2. Also in Cloud console, set a quota on Places API (New), for example requests per day, and check Google's current Places pricing. LeadScout's own cap below is a second guard, not a replacement.
3. In **Settings > Data**, tick "Look up review counts and open status on Google". Set the monthly request cap (default 1,000) and the lowest score to look up (default 50). Settings also shows this month's count.

How it works: after each area search is scored, leads at or above the minimum score with no Google id get one Text Search (IDs only: the name and locality, biased to 500 m around our coordinates). The id is kept only when exactly one place comes back. Leads without coordinates (most CSV imports) are skipped. Then scoring fetches Place Details (rating, review count, open status, hours) for matched leads it rescores, in memory only. A place Google marks closed for good is excluded; 20 or more reviews adds 5 points. Every request counts towards `[enrich] monthly_request_cap`; at the cap, lookups stop until the 1st and the search, the CLI and the lead page say so. `leadscout enrich` runs the matching by hand.

## Sending safety

- Warm-up caps from first send: 15/day week 1, 30/day week 2, 50/day from week 3 (Settings page, saved in `config.toml`).
- Only 10:00 to 17:00 IST, Monday to Saturday; 3 to 6 minutes between emails.
- One follow-up after 4 days, in the same Gmail thread.
- Pauses itself if more than 5% of the last 40 first emails bounced.
- Every send checks the hashed opt-out list first.

## Database migrations

The schema lives in numbered SQL files in `src/leadscout/migrations/`. A database records each migration it has had by name, the file name without its number (`0004_demos.sql` is `demos`), in the `schema_migrations` table. `db.connect()` applies every file whose name isn't recorded yet, in number order, once per process, each in its own transaction. So renumbering a file after the two tracks clash never runs it twice, and a file that lands with a lower number than one already applied still runs. `pragma user_version` keeps the highest number applied, for older code and for backup names.

To change the schema, add the next file, for example `0006_add_lead_tags.sql`, holding plain SQL (`create table`, `alter table ... add column`, `create index`). The name after the number must be new and must never change. Never edit a migration that has already shipped; write a new one. Add a test in `tests/test_migrations.py` if the migration moves data.

The first time this code opens a database migrated before `schema_migrations` existed, it records the files up to its `user_version` as applied, by name. A database from before numbered migrations (version 0) gets the old `_migrate()` fix-ups once, in the same transaction as `0001_baseline`. Each migration runs under `BEGIN IMMEDIATE` and checks `schema_migrations` inside it, so when two processes start together only one of them applies it.

## Backups

`backups.py` copies the database into `data/backups/` with sqlite's backup API (a plain file copy can miss recent writes while WAL is on):

- `leadscout-<YYYYmmdd-HHMMSS>-v<old version>.db` before every migration;
- `...-nightly.db` once per IST day while the dashboard runs (it checks at start and every hour);
- `...-manual.db` whenever you run `leadscout backup`;
- `...-pre-restore.db` before every restore.

Copies older than `[backups] keep_days` (14 by default) are deleted after each backup and by the daily purge; the age comes from the timestamp in the name. `leadscout forget` also removes the person from every backup and adds the hashed opt-out entry to it; any backup it can't open is named in its message. Deleted rows are overwritten in the live database too (`secure_delete`).

### Restoring a backup

1. List the backups: open `data\backups` in File Explorer, or run `dir data\backups` (PowerShell: `ls data/backups`). The name says when each was taken.
2. Stop the dashboard: `leadscout stop` for the desktop icon, or Ctrl+C in the terminal running `leadscout serve`. Restore refuses to run while a dashboard answers.
3. `leadscout restore leadscout-20261124-093000-nightly.db` (a name from that folder, or a full path).

Restore first saves the current database as `...-pre-restore.db`, so you can undo it by restoring that file. An older-version backup is migrated. Then the opt-out list is re-applied as the live rules do: the hashed entries from the current database and the backup are merged (keeping the stronger reason), businesses that asked to be forgotten are deleted, opted-out leads are marked opted out with their history kept (a won lead is left for you to decide), and bounced addresses are left alone. So a restore never brings back someone who opted out or asked to be forgotten.

## Preview host (demo pages online)

Demo pages go online on a free Cloudflare Worker, on a subdomain of your studio domain such as `demo.yourstudio.in`. The Worker serves only the static demo pages and stores no lead data. A view is a demo's slug and a time; an unsubscribe is a token and a time. It keeps no IP addresses and sets no cookies. The code is in `preview/` (`src/index.js`, tests in `test/`).

| Command | What it does |
|---|---|
| `leadscout demo <id>` | builds the page locally in `data/demos/<slug>/` |
| `leadscout demos publish` | deploys every live demo, sets its link (`demos.url`) and takes expired, opted-out or forgotten ones down |
| `leadscout demos sync` | pulls views and unsubscribes back (the dashboard also runs it every hour, and the Demos page has a Sync now button) |
| `leadscout demos secret` | prints a new random sync secret |

Each deploy replaces the whole site, and preview URLs are switched off, so a page that comes down can't be reached at an older address. Never use `wrangler rollback`: it would bring taken-down pages back. To fix a mistake, rebuild or delete the demo and publish again.

### One-time setup (about 30 minutes)

You need Node.js (LTS, from nodejs.org) for wrangler, Cloudflare's deploy tool. Everything here is free.

1. **Cloudflare account.** Sign up at dash.cloudflare.com on the Free plan.
2. **Your domain on Cloudflare.** In the dashboard, choose *Add a domain*, type your studio domain and pick the Free plan. Cloudflare shows two nameservers: set them at your domain registrar (GoDaddy, Hostinger, BigRock...) in place of the old ones. It can take a few hours. Your existing website and email keep working if Cloudflare copied your DNS records; compare its list with your registrar's before switching. No domain yet? Skip this and use the free `*.workers.dev` address (step 6).
3. **Install wrangler** once, in a terminal in the LeadScout folder: `cd preview`, then `npm ci`.
4. **Storage for views and unsubscribes.** In the dashboard: *Storage & databases → Workers KV → Create*, name it `leadscout-events`, then copy its **ID**.
5. **API token.** *My profile → API tokens → Create token → "Edit Cloudflare Workers"* template. Under *Account resources* pick your account; under *Zone resources* pick your studio domain. Create it and copy the token: it's shown once. If the first publish says it can't add the custom domain, edit the token and add *Zone → DNS → Edit* for that domain.
6. **Account ID.** *Workers & Pages* overview, right-hand side: copy the *Account ID*. If you skipped step 2, the same page shows your `workers.dev` subdomain: your address is `https://leadscout-preview.<that subdomain>.workers.dev`.
7. **.env** (never commit it; the repo is public):
   ```
   CLOUDFLARE_API_TOKEN=the token from step 5
   PREVIEW_SYNC_SECRET=the output of `leadscout demos secret`
   ```
8. **config.toml**, in the `[preview]` section:
   ```toml
   base_url = "https://demo.yourstudio.in"   # or the workers.dev address from step 6
   account_id = "the ID from step 6"
   kv_namespace_id = "the ID from step 4"
   ```
9. **First deploy.** Build a demo (`leadscout demo <id>`), then `leadscout demos publish`, or the Publish button on the Demos page. The first one also creates the `demo.` DNS record. Open the link on your phone and check the concept banner, then run `leadscout demos sync`: the view shows up.

### Good to know

- Opening a demo yourself counts as a view too. Check pages before you send the link, or keep that in mind when you read the numbers.
- Free plan limits that matter: 100,000 requests a day and 1,000 KV writes a day. A view is written at most once per demo per 30 minutes, so this is far more than LeadScout needs.
- Each route has a per-minute limit inside the Worker. For a firmer limit, add one free *rate limiting rule* under *Security → WAF* for `demo.yourstudio.in/u/*` and `/v/*`.
- Unsubscribes from the host wait in LeadScout (the Demos page says how many) until the Find & qualify side has `outreach.unsubscribe.resolve()` (contract C4). Then they're applied on the next sync.
- If you rotate `PREVIEW_SYNC_SECRET`, publish again so the Worker gets the new one.

## Layout

```
src/leadscout/
  cli.py, config.py, db.py, compliance.py, scoring.py, emailcheck.py
  migrations/ 0001_baseline.sql, ... (numbered schema changes); backups.py; settings.py (the Settings page's form and save)
  sources/   geo.py (Nominatim), overture.py, csv_import.py, common.py
  audit/     classify.py, site.py, pagespeed.py, __init__.py (runner)
  pitch/     templates.py, jobs.py (Claude Code hand-off)
  demos/     __init__.py (builder), preview.py (publish, sync), cli.py, templates/ (one per vertical)
  mailer/    gmail.py, sender.py
  web/       app.py, templates/, static/
preview/     the Cloudflare Worker for demo pages (src/index.js, test/, package.json)
.claude/commands/pitch-today.md
tests/
```
