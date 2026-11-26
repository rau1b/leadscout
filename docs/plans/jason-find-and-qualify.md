# LeadScout 2.0 — Jason's track: Find & qualify

> **For Claude Code:** this is Jason's build plan for the Find & qualify half of LeadScout 2.0. Jason will ask for one step at a time, for example "Do Phase 1 Step 2 from docs/plans/jason-find-and-qualify.md". Do only that step: follow its prompt below, plus CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md. If the code has changed so the step no longer fits as written, adapt it, keep its goal, and say what you changed. Never start the next step unless asked. Never edit rau1b's modules (`demos/`, `crm/`, `billing/`, `preview/`). If a step fails and you can't fix it inside this track, stop and report which test failed and why.

Written 25 Nov 2026. rau1b's plan is `docs/plans/rau1b-show-and-close.md`.

## How to use this plan

You build the Find & qualify half of LeadScout 2.0 on your own, one step at a time, without waiting for rau1b. Each step below has a goal, a prompt for Claude Code, and a done-when check. Do the steps in order; each one ends in a pull request you merge yourself.

**Daily routine**

1. Start of day: in Claude Code, say `git switch jason, git fetch origin, git merge origin/main, then run ruff and the tests`. This picks up whatever rau1b merged.
2. Work on the next step. Commit and push to `jason` as often as you like.
3. When a step is done: merge `origin/main` once more, run ruff and the full suite, open a PR into main, wait for the GitHub check to go green, then merge it yourself with **Create a merge commit**.

**Working alone: the rules**

- Work only in your own modules (next section). Never edit files in rau1b's modules, and never push to the `rau1b` branch.
- You merge your own PRs once the check is green. Nobody has to review them first; rau1b may leave comments later.
- Shared files (`db.py`, `migrations/`, `web/app.py`, `cli.py`, `base.html`, `config.example.toml`, `CLAUDE.md`) get small, additive changes only: one import line, one nav link, one new config section.
- Database migrations take the next free number when you merge. If rau1b's landed first with the same number, rename yours to the next one. The migration test catches clashes.
- Everything that crosses into rau1b's half goes through the contracts in this plan. If his side isn't built yet, your code uses the fallback written next to each contract and keeps working.
- Every prompt starts with "Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first", so Claude Code follows the same rules each time.

## What you own

You own everything from "find a business" to "send the pitch and read the reply": Phases 1 and 3 of the plan, plus the funnel and scoring half of Phase 5. rau1b owns demo sites, the preview host, the pipeline board, proposals and invoices.

| Area | Your modules | Phase |
| --- | --- | --- |
| Business data | `sources/`, `searches.py`, new `enrich/` | 1 |
| Website audits and findings | `audit/`, new `findings` code | 1 |
| Scoring | `scoring.py` | 1, 5 |
| Pitches | `pitch/` | 1, 3 |
| Sending, replies, inboxes | `mailer/`, new `outreach/` | 3 |
| Opt-outs and privacy | `compliance.py` | all |
| Your dashboard pages | `web/<area>.py` per new page, `web/extras.py` replies part | 1, 3, 5 |

Not yours: `demos/`, `crm/`, `billing/`, the preview host (Cloudflare) and their dashboard pages. One exception is agreed in advance: rau1b adds a single call to `demos.remove_orphans(con)` inside `compliance.forget()`. Leave it in place when you edit that function.

## Contracts with rau1b's half

These are fixed, and rau1b's plan has the same table word for word, so neither of you needs to ask the other anything. Your Step 0 copies this table into `docs/CONTRACTS.md`. Until that's merged, this table is the source of truth.

| # | Contract | Owner | The other side uses it to | Fallback if the owner hasn't built it yet |
| --- | --- | --- | --- | --- |
| C1 | `demos` table: business_id, slug, template, url (null until published), built_at, expires_at, first_viewed_at, view_count. Cascades on business delete. | rau1b (exists, PR #6) | Jason: put the demo link in a pitch only when `url` is set and `expires_at` is in the future; treat `first_viewed_at` as a buying signal in scoring and follow-ups | No row or null `url`: no link, no signal |
| C2 | `audits.screenshot_path`: mobile screenshot image (JPEG from PageSpeed, or PNG) of the lead's current site, path relative to the data folder, may be null | Jason (Phase 1, Step 4) | rau1b: the "before" half of before/after images | Null or missing column: rau1b takes his own screenshot with Playwright |
| C3 | `businesses.basic_category`: Overture's plain category label | Jason (Phase 1, Step 1) | rau1b: choose the demo template | Missing column or null: use `category` and `category_path` |
| C4 | One-click unsubscribe. Jason's emails carry `List-Unsubscribe` with a mailto always, plus `<[preview] base_url>/u/<token>` when that setting exists. Jason owns table `unsubscribe_tokens(token primary key, business_id, created_at)` and `outreach.unsubscribe.resolve(con, token) -> business_id or None`. | Jason (Phase 3, Step 2) | rau1b: the preview host's `/u/<token>` route stores tokens; `leadscout demos sync` calls `resolve()` then `compliance.opt_out_business(con, business_id, "unsubscribe link")` | If the import fails, sync keeps the tokens queued and logs it. No https links are sent before Jason builds it, so none arrive |
| C5 | `compliance.opt_out_business(con, business_id, reason)`: opts out that lead's email and phone, sets status `opted_out` (never for a won lead) | Jason (Phase 1, Step 0) | rau1b: unsubscribes and "stop" clicks from the preview host | None needed after Step 0 |
| C6 | Lead statuses. Jason sets new, drafted, approved, contacted, replied, send_failed, opted_out, bounced, excluded, hidden. rau1b sets meeting, proposal, won, lost, and only from replied, meeting or proposal. Jason's code never moves a lead out of meeting, proposal, won or lost, except to opted_out or bounced. Replies keep being checked for meeting and proposal leads. | both | Shared lead flow | rau1b adds `meeting` and `proposal` to `db.STATUSES` (one line); Jason's Step 0 makes reply checking include them |
| C7 | Events (`db.log_event`). Jason writes: audit_done, findings_updated, pitch_drafted, pitch_sent, reply_received, reply_labelled, opted_out, settings_changed, visit_logged, whatsapp_opened. rau1b writes: demo_built, demo_published, demo_viewed, demo_expired, proposal_sent, proposal_accepted, invoice_sent, invoice_paid, stage_changed, task_done. Actor is system, dashboard, cli or preview-host. `data_json` never holds an email, phone number or message text. | both | Timeline and analytics | An unknown event type is ignored by readers |
| C8 | Forget. `compliance.forget()` deletes businesses; the `demos` rows cascade; rau1b's single `demos.remove_orphans(con)` call inside it removes local pages; rau1b's next sync takes forgotten or expired demos off the preview host | Jason (function), rau1b (the one call, sync) | Delete-on-request reaches every copy | None |
| C9 | Config sections. Jason: sender, pitch, sending, scoring, retention, backups, enrich, outreach. rau1b: preview, demos, billing. | both | Settings and defaults | Missing section: code uses defaults |
| C10 | Dashboard: each new area is its own `web/<area>.py`, one import line in `app.py`, one nav link in `base.html`. Migrations: next free number at merge time. | both | No clashes in shared files | Not applicable |


Changing a contract is the only time you must message rau1b first. Everything else, you decide.

## Phase 1: better data and audits (weeks 1–4)

Phase 1 ends when every lead has findings, the one-page audit report prints, and one Goa area runs end to end. Steps 0 to 6 are musts; Step 7 is worth doing if time allows.

### Step 0: contracts and the two helpers rau1b relies on (half a day)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

1. Replace the contracts in docs/CONTRACTS.md with the Contracts table (C1-C10) from docs/plans/jason-find-and-qualify.md, word for word, and mark C2, C3, C4 as planned. Commit both files in docs/plans/ too, so rau1b gets them from main.
2. Add compliance.opt_out_business(con, business_id, reason): opts out the lead's email and the business phone through the existing opt_out(), sets lead status 'opted_out' unless it is 'won', logs an opted_out event (no email or phone in data). Tests.
3. Reply checking (sender.check_replies and anything else that lists "active conversations") must also include leads with status 'meeting' or 'proposal', and must never move a lead out of meeting/proposal/won/lost except to opted_out or bounced. Use plain string checks so it works before rau1b adds those statuses. In scoring.py, add meeting and proposal to STATUS_RANK at the same rank as replied (so a twin listing is never pitched instead), and to IN_CONTACT (so rescoring never drops their email). Tests.
4. Ruff and full suite pass. Commit, push, open a PR into main, and once the GitHub check is green merge it with "Create a merge commit". Report the PR link.
```

Done when: the PR is merged and `docs/CONTRACTS.md` matches the plan.

### Step 1: better business data from Overture (1–2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

Background (checked against Overture's docs): `categories` was removed in the 2026-09-23 release. Places now have basic_category (about 280 plain labels) and taxonomy (primary, hierarchy, alternates). Our code already reads taxonomy.primary and taxonomy.hierarchy, and Overture's id is the GERS id, stable across releases.

1. New migration (next free number): businesses gets basic_category text and category_alternates text default '[]'. New table source_records(business_id references businesses(id) on delete cascade, source text not null, source_id text, fetched_at text not null, release text, unique(business_id, source)). No raw payloads.
2. sources/overture.py: select basic_category and taxonomy.alternates, store both, record the Overture release if the overturemaps library exposes it (else null, and say so), and write a source_records row on every upsert. CSV import and manual adds write their own row.
3. Matching business types: basic_category first, then the taxonomy hierarchy and alternates, then the name. Show basic_category on the lead page. On the Find page, suggest the basic categories already in the database (a datalist).
4. Make sure a CSV or manually added business is matched against Overture businesses by the existing DuplicateFinder (phone, own website, name within 15 km), keeping the copy with more history.
5. Offline tests: fields stored; matching prefers basic_category; a CSV duplicate is caught; source_records cascade on forget.
6. Ruff and full suite pass. Commit, push, PR into main, merge when the check is green. Report anything you did differently and why.
```

Done when: a fresh search in a Goa area shows basic categories on lead pages, and contract C3 exists.

### Step 2: Google Places enrichment for top leads, within Google's terms (2 days)

Google's terms let you keep only the Places `place_id` permanently. Ratings, review counts, phone numbers and websites from Google may not be saved, so they are fetched when needed and shown with attribution. It stays off until you turn it on.

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

Add optional Google Places enrichment in a new module src/leadscout/enrich/places.py. It must follow Google's Places caching rules: store ONLY the place_id permanently; never store rating, review count, phone, website, hours or coordinates from Google.

1. Config [enrich]: places_enabled = false, monthly_request_cap = 1000, min_score_to_enrich = 50. Uses GOOGLE_API_KEY from .env. Off, or no key: everything else works exactly as now.
2. Matching: for leads at or above min_score_to_enrich with no Google id yet, call Places API (New) Text Search with field mask places.id only (the IDs-only tier), text = business name + locality, location bias = a 500 m circle around our coordinates. Keep the place_id in source_records (source 'google', source_id = place_id) only when one result clearly matches; otherwise record nothing.
3. Details at use time: Place Details with rating, userRatingCount, businessStatus, regularOpeningHours. Used (a) while scoring, in memory only, so the score can use review count and "permanently closed"; and (b) on the lead page behind a "Show Google details" button, displayed with "Data from Google" attribution and not saved. Scoring stores only its own score and a reason without Google's numbers (e.g. "Well reviewed on Google").
4. Cost guard: count every Places request in the meta table per calendar month; stop at monthly_request_cap with a clear message on the dashboard and in the CLI. Show this month's count on the Settings page. Tell me in your report to also set a quota in Google Cloud Console.
5. Offline tests with respx: nothing from Google except place_id is ever written to the database (scan every table after a run); the cap stops requests; disabled = no requests.
6. Ruff and full suite pass. Update docs/STACK.md (how to turn it on). Commit, push, PR, merge when green.
```

Done when: with it switched on for one area, the top leads show live Google details, and a database scan finds only place ids from Google.

### Step 3: domain, certificate and technology facts (2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

1. Domain facts via RDAP (free): find the RDAP server from IANA's bootstrap file (https://data.iana.org/rdap/dns.json, cached in data/ for 7 days), read registration and expiry dates. Certificate expiry from the TLS certificate when HTTPS works. Store on the audit (new migration, next free number): domain_registered, domain_expires, cert_expires.
2. Technology detection from HTML and headers with our own small rule set (no copied fingerprint database): WordPress and its version, Wix, Blogger, Google Sites, Shopify, Linktree, Elementor/Divi page builders, jQuery 1.x, hand-made. Store tech and cms_version.
3. Crawl at most 5 pages on the same host (home, contact, about, services, found from links), obeying robots.txt, to find emails, wa.me links, booking widgets, Google Maps embeds and tel: links. Keep the existing per-site time limits.
4. Offline tests with fixture HTML and recorded RDAP responses (respx). No network in tests.
5. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: lead pages show domain expiry, certificate expiry and the detected technology.

### Step 4: the findings engine (3 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

1. New migration (next free number): audit_runs(id, business_id references businesses on delete cascade, started_at, finished_at, psi_score, lcp_s, cls, inp_ms, seo_score, a11y_score, screenshot_path, error) and findings(audit_run_id references audit_runs on delete cascade, code, severity 1-3, value, evidence_url, evidence_text). Add audits.screenshot_path (contract C2).
2. Every check writes a finding row with its measured value and evidence: site class, speed, mobile viewport, HTTPS/certificate, copyright year, domain/cert expiring within 60 days, technology, missing WhatsApp button, missing click-to-call, no map embed, no contact form, missing title or meta description, no LocalBusiness schema, address/phone not on the page.
3. PageSpeed: request performance, seo, accessibility and best-practices categories; keep field data when present; save the final screenshot to data/screenshots/<business_id>.jpg and set screenshot_path (C2).
4. Backfill: a one-time step turns existing audit rows into findings, so every audited lead has findings.
5. Pitches, scores and the lead page read findings. Extend the existing unmeasured-number check so a pitch may only cite numbers from this lead's findings.
6. Offline tests: each check produces its finding from fixtures; backfill covers old audits; forget removes findings and the screenshot file.
7. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: every audited lead shows a findings list with evidence, and screenshots exist for sites PageSpeed could load.

### Step 5: scoring v2 (2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

1. New migration: scores(business_id references businesses on delete cascade, fit, need, reach, intent, total, reasons_json, weights_version, scored_at).
2. Four sub-scores 0-100, each with plain reasons: Fit (category value, Google review count and open status when enrichment is on, chain or not), Need (findings severity, site class), Reach (verified email, mobile number, locality), Intent (domain expiring within 60 days, demo viewed per contract C1, reply received). Weights in config [scoring.weights] with a version string.
3. Keep exclusions, the opt-out check and DuplicateFinder exactly as they are. Lead page shows the four bars and the reasons.
4. Offline tests for each sub-score, and that a viewed demo (a demos row with first_viewed_at) raises intent while a missing demos row changes nothing.
5. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: every lead shows four sub-scores with reasons, and the Leads list sorts by the total.

### Step 6: printable one-page audit report (1–2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

1. Route /leads/<id>/report in its own web/report.py: one A4 page with a print stylesheet, in the dashboard's Bahi-khata style. Contents: business name and area, date measured, the 3-5 most severe findings in plain words with their measured values, the "before" screenshot (C2) when present, a locality line computed from our own database ("7 of 10 dentists in Panaji that we checked have a website"), studio contact, and "Measured on <date> with Google PageSpeed Insights".
2. A QR code (the qrcode package, SVG output, no image libraries) pointing to the lead's demo url when contract C1 has a live one, else to the studio portfolio link.
3. A "Print report" button on the lead page; the browser's print-to-PDF makes the file. Suppressed leads get no report.
4. Only measured facts: the same unmeasured-number rule as pitches. Offline tests: report renders, shows only findings that exist, QR target follows C1.
5. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: you can print a clean one-page report for a real Goa lead.

### Step 7 (if time allows): background jobs

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

Replace the single background thread in searches.py with a worker that runs rows from the existing jobs table: find, audit, enrich and score as job types, with retries (3 attempts, backoff), progress shown on the Find page, and failures recorded on the job instead of leaving half-finished rows. Several areas can queue up. No Redis or new services. Offline tests for retry and progress. Ruff and full suite pass. Commit, push, PR, merge when green.
```

**Phase 1 gate:** run one Goa area from search to printed report. Every lead has findings, scores have reasons, and the report prints on one page.

## Phase 3: outreach v2 (weeks 5–7)

Phase 3 ends when the outreach domain is warmed up, 100 emails have gone out from it, and spam complaints stay under 0.1% in Google Postmaster Tools. Start the domain warm-up (see Non-code tasks) during Phase 1, because it takes 2–3 weeks anyway.

### Step 1: send from any inbox, with DNS checks (2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

1. New migration (next free number): inboxes(id, address, provider 'gmail' or 'smtp', smtp_host, smtp_port, warmup_started, daily_cap, spf_ok, dkim_ok, dmarc_ok, checked_at). The current Gmail account becomes the first row.
2. SMTP sending next to the Gmail API (Zoho Mail and Google Workspace both work over SMTP with an app password). Passwords live in .env or the Windows credential store via keyring, never in the database or config.toml.
3. Before an inbox may send, check its domain with dnspython: SPF includes the provider, a DKIM record exists for the provider's selector, DMARC exists (p=none is fine to start). Show the result and the exact record to add on an Inboxes page (its own web/inboxes.py, linked from Settings).
4. Warm-up caps, the sending window, the bounce pause and the single-sender lease apply per inbox. Replies are read from whichever inbox sent the first email.
5. Offline tests with a fake SMTP server and mocked DNS. Ruff and full suite pass. Commit, push, PR, merge when green.
```

### Step 2: one-click unsubscribe (contract C4) (1 day)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

1. New migration: unsubscribe_tokens(token text primary key, business_id references businesses on delete cascade, created_at). One token per lead, secrets.token_urlsafe(16).
2. Every cold email gets List-Unsubscribe with the existing mailto, plus <base_url>/u/<token> and List-Unsubscribe-Post: List-Unsubscribe=One-Click when config [preview] base_url is set (rau1b's section; read it, never write it). Without base_url, mailto only, exactly as now.
3. Add src/leadscout/outreach/unsubscribe.py with resolve(con, token) -> business_id or None, exactly as contract C4 says. rau1b's sync calls it.
4. Offline tests: headers with and without base_url; resolve() for a known, unknown and forgotten token. Update docs/CONTRACTS.md to mark C4 as built. Ruff and full suite pass. Commit, push, PR, merge when green.
```

### Step 3: follow-ups that use what we know (1 day)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

Still at most one follow-up per lead (INDIA_RULES.md). Make the follow-up text adapt, citing only true facts: if the lead viewed its demo (contract C1 first_viewed_at), say so plainly; if the domain expires within 60 days (a finding), mention it; otherwise the current text. First emails include the demo link only when C1 has a live url. Plain text, one link per email. Offline tests for each variant and for "no demos row". Ruff and full suite pass. Commit, push, PR, merge when green.
```

### Step 4: reply sorting with your final say (2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

1. New migration: reply_labels(reply id, label one of interested, question, not_now, opt_out, bounce, auto_reply, by one of rule, claude, person, labelled_at).
2. Rules first: the existing opt-out rule and bounce detection, plus auto-replies (out of office, Auto-Submitted header), interested (asks price, asks to call, says send), not now, question. Clear opt-outs keep being applied automatically, as now.
3. Optional Claude pass through the Claude Code hand-off, like /pitch-today: a new .claude/commands/sort-replies.md reads a JSON file of unlabelled replies and writes suggested labels back. No Anthropic API (CLAUDE.md).
4. The Replies page shows each label with Confirm and Change buttons; a person's choice always wins and logs reply_labelled (no message text in the event).
5. Offline tests for every rule. Ruff and full suite pass. Commit, push, PR, merge when green.
```

### Step 5: visit planner (1–2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

New page web/visits.py: pick a locality and a day; list the best not-yet-visited leads there (no website or weak site, not suppressed), ordered as a walking route by nearest neighbour from a start point you type; one Print button prints the route sheet plus each lead's one-page audit report (Phase 1 Step 6). After the day, mark each visit as visited, not there, interested or not interested; that logs visit_logged and updates the lead. Offline tests. Ruff and full suite pass. Commit, push, PR, merge when green.
```

### Step 6: WhatsApp queue, by hand only (1 day)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

New page web/whatsapp.py: a queue of leads LeadScout may suggest a WhatsApp chat for, following docs/INDIA_RULES.md exactly (mobile numbers only, never suppressed, replied leads first). Each row has the click-to-chat link with a prefilled honest message; opening one logs whatsapp_opened and counts against the existing whatsapp_daily_cap. Never send anything automatically. Offline tests for the cap and the suppression check. Ruff and full suite pass. Commit, push, PR, merge when green.
```

### Step 7: deliverability health page (1 day)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

New page web/health.py: per inbox the warm-up stage, today's sends against the cap, bounce rate over the last 40 emails, DNS check status and age, unsubscribes this week, plus a weekly reminder to check Google Postmaster Tools (complaints must stay under 0.1%). Also show Places and PageSpeed requests used this month. Offline tests. Ruff and full suite pass. Commit, push, PR, merge when green.
```

**Phase 3 gate:** 100 emails sent from the warmed outreach domain, bounce rate under the limit, complaints under 0.1% in Postmaster Tools, and every reply labelled.

## Phase 5: your share of analytics (weeks 8–9)

Your half of Phase 5 is the funnel, score calibration and pitch A/B tests. rau1b's half is the revenue report. Score calibration needs at least 200 contacted leads, so start Step 2 only once the funnel shows that many.

### Step 1: the funnel report (1–2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

New page web/funnel.py: found, qualified, contacted, replied, meeting, won, built from leads, outreach, replies and events (contract C6 statuses; meeting and won come from rau1b's side and may be zero). Break it down by basic_category, locality, pitch version, inbox and channel (email, visit, WhatsApp), for a date range. Show reply rate and win rate per 100 contacted. Offline tests with a seeded database. Ruff and full suite pass. Commit, push, PR, merge when green.
```

### Step 2: calibrate the score from real outcomes (2 days, after 200+ contacted)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

Add `leadscout calibrate`: fit a simple logistic regression of "replied" and of "won" against the four sub-scores (fit, need, reach, intent) for leads contacted at least 14 days ago. Write it with numpy only if it isn't already a dependency, else plain Python. Print the suggested weights, the sample size and a warning below 200 leads. The Settings page shows the suggestion with an Accept button that writes new [scoring.weights] and a new weights_version. Never apply weights automatically. Offline tests with a synthetic dataset. Ruff and full suite pass. Commit, push, PR, merge when green.
```

### Step 3: A/B tests on subject lines and first lines (1–2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch jason: git fetch origin, merge origin/main, run tests.

Let pitch templates carry two variants of the subject line or first sentence. Assign each new pitch a variant at random and store it on the pitch. The funnel page shows replies per variant and only names a winner after at least 50 sends per variant. Both variants must pass the measured-facts check. Offline tests. Ruff and full suite pass. Commit, push, PR, merge when green.
```

**Finishing 2.0:** once your Phase 5 steps and rau1b's Phase 4 gate are both merged into main (you can see this in main's history), tag the release `v2.0.0` with a short changelog.

## Non-code tasks

Start the outreach domain this week. Warm-up takes 2–3 weeks, and Phase 3 depends on it.

- [ ] Buy a separate outreach domain, never your main studio domain: the studio name plus a word, as a .in or .com (about ₹800–1,000 a year).
- [ ] Create one mailbox on it: Zoho Mail Lite (about ₹59 per user a month) or Google Workspace Business Starter (about ₹270 per user a month), both before GST. Check current prices on their sites.
- [ ] Add SPF, DKIM and DMARC records at your domain registrar. Start DMARC at `p=none`.
- [ ] Register the domain in Google Postmaster Tools.
- [ ] Warm up at the existing caps: 15 emails a day in week 1, 30 in week 2, 50 from week 3, to real leads only. Send plain-text emails with one link each.
- [ ] Phase 1 gate check: pick one Goa locality, search it, and print 5 audit reports to take on a visit.

## When something goes wrong

Almost everything here you fix alone. The one exception is a contract that has to change: message rau1b first.

| What happened | What you do |
| --- | --- |
| A step fails and Claude Code couldn't fix it | Paste the recovery prompt below. |
| The migration test fails after merging main | rau1b's migration took your number. Tell Claude Code: "rename my migration to the next free number and update anything that refers to it". |
| A merge conflict in a shared file (`app.py`, `cli.py`, `base.html`, `config.example.toml`, `CLAUDE.md`, the lead page template) | Tell Claude Code: "resolve by keeping both sides' additions". These files only get additive lines, so both sides belong. |
| Tests fail after merging main, in rau1b's code | Don't edit his modules. If main itself has been red for more than a day, `git revert` the commit that broke it in a small PR, and open a GitHub issue saying which test failed and that you reverted it. He can re-apply it. |
| Your step needs something from his side that isn't in the contracts | Use the fallback from the contracts table and keep going. Write a GitHub issue describing what you'd like later; don't build it in his modules. |
| Claude Code wants to change a file in `demos/`, `crm/` or `billing/` | Say no. Repeat the rule: work only in the Find & qualify modules. |
| The GitHub check on your PR is red | Fix it on `jason`, push, and wait for green. Never merge red. |
| `pip install` fails with a locked file (WinError 32) | Stop the dashboard first: `leadscout stop`, or Ctrl+C the terminal running `leadscout serve`. |
| You committed `.env`, `config.toml` or anything in `data/` by mistake | The repo is public, so treat it as leaked straight away: revoke the Google API key in Cloud Console, run `leadscout gmail-login` again for a new token, change any mailbox password. Then remove the file in a new commit. |
| A contract looks wrong or blocks you | Message rau1b with the contract number (C1–C10) and your proposed change. Change it only after he agrees, then update both plans and `docs/CONTRACTS.md`. |

**Recovery prompt**

```
The last step didn't finish cleanly. Do this:
1. Run git status and show me what's changed but not committed.
2. Run ruff and the full test suite; list every failure with the file and test name.
3. Fix the failures inside my own track's modules (see docs/TRACKS.md). Don't edit the other track's files.
4. If a failure comes from the other track's code or from a contract in docs/CONTRACTS.md, don't fix it; tell me which test and why.
5. Re-run ruff and the full suite until they pass, then commit and push. Don't open or merge a PR yet; show me a summary first.
```
