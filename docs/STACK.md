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
leadscout audit                  # classify site, fetch, HTML checks, PageSpeed
leadscout pagespeed              # re-run PageSpeed later (e.g. after adding a key)
leadscout score                  # 0-100 score, reasons, best deliverable email, dedupe, chains out
leadscout pitch --templates 50   # or: --prepare 50, then /pitch-today in Claude Code, then --import
leadscout serve                  # dashboard: review, edit, approve
leadscout gmail-login            # one time
leadscout send                   # sends approved emails inside the IST window, warm-up caps
leadscout check-replies          # replies, "no thanks" opt-outs, bounces
leadscout optout <email|phone>   # never contact again
leadscout forget <email|phone>   # delete everything, keep hashed opt-out
leadscout purge                  # delete never-contacted data older than 90 days
leadscout export leads.csv
```

Website classes: none, social_only, directory_only, dead_google_site (business.site), free_subdomain, broken (expired domain = `fetch_error: dns`, HTTP errors, parked pages), real. Bot-protected sites (403/429/503) count as real.

## Searching by city

The dashboard's **Find leads** page queues area searches (city + optional neighbourhood + business types) and runs find, audit and score in a background thread, one search at a time (`searches.py`). Each business stores its `area` and `city`; Leads and Pitches filter by area. A neighbourhood search covers 4 to 7 km; a city without a neighbourhood covers about 13 km around its centre. Places mapped as a single point are widened automatically.

## Sending safety

- Warm-up caps from first send: 15/day week 1, 30/day week 2, 50/day from week 3 (`config.toml`).
- Only 10:00 to 17:00 IST, Monday to Saturday; 3 to 6 minutes between emails.
- One follow-up after 4 days, in the same Gmail thread.
- Pauses itself if more than 5% of the last 40 first emails bounced.
- Every send checks the hashed opt-out list first.

## Layout

```
src/leadscout/
  cli.py, config.py, db.py, compliance.py, scoring.py, emailcheck.py
  sources/   geo.py (Nominatim), overture.py, csv_import.py, common.py
  audit/     classify.py, site.py, pagespeed.py, __init__.py (runner)
  pitch/     templates.py, jobs.py (Claude Code hand-off)
  mailer/    gmail.py, sender.py
  web/       app.py, templates/, static/
.claude/commands/pitch-today.md
tests/
```
