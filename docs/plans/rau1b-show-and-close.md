# LeadScout 2.0 — rau1b's track: Show & close

> **For Claude Code:** this is rau1b's build plan for the Show & close half of LeadScout 2.0. rau1b will ask for one step at a time, for example "Do Phase 2 Step 1 from docs/plans/rau1b-show-and-close.md". Do only that step: follow its prompt below, plus CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md. If the code has changed so the step no longer fits as written, adapt it, keep its goal, and say what you changed. Never start the next step unless asked. Never edit Jason's modules (`sources/`, `enrich/`, `audit/`, `scoring.py`, `pitch/`, `mailer/`, `outreach/`, `compliance.py`), except the one agreed `demos.remove_orphans(con)` line in `compliance.forget()`. If a step fails and you can't fix it inside this track, stop and report which test failed and why.

Written 25 Nov 2026. Jason's plan is `docs/plans/jason-find-and-qualify.md`.

## How to use this plan

You build the Show & close half of LeadScout 2.0 on your own, one step at a time, without waiting for Jason. Each step below has a goal, a prompt for Claude Code, and a done-when check. Do the steps in order; each one ends in a pull request you merge yourself.

**Daily routine**

1. Start of day: in Claude Code, say `git switch rau1b, git fetch origin, git merge origin/main, then run ruff and the tests`. This picks up whatever Jason merged.
2. Work on the next step. Commit and push to `rau1b` as often as you like.
3. When a step is done: merge `origin/main` once more, run ruff and the full suite, open a PR into main, wait for the GitHub check to go green, then merge it yourself with **Create a merge commit**.

**Working alone: the rules**

- Work only in your own modules (next section). Never edit files in Jason's modules, and never push to the `jason` branch.
- You merge your own PRs once the check is green. Nobody has to review them first; Jason may leave comments later.
- Shared files (`db.py`, `migrations/`, `web/app.py`, `cli.py`, `base.html`, `config.example.toml`, `CLAUDE.md`) get small, additive changes only: one import line, one nav link, one new config section.
- Database migrations take the next free number when you merge. If Jason's landed first with the same number, rename yours to the next one. The migration test catches clashes.
- Everything that crosses into Jason's half goes through the contracts in this plan. If his side isn't built yet, your code uses the fallback written next to each contract and keeps working.
- Every prompt starts with "Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first", so Claude Code follows the same rules each time.
- Before your first prompt on a computer that has an old copy: `git switch main`, `git pull origin main`, then reinstall with `.venv\Scripts\python -m pip install -e ".[dev]"` (stop the dashboard first).

## What you own

You own everything from "show the business its new website" to "get paid": Phases 2 and 4 of the plan, plus the revenue report in Phase 5. Jason owns business data, audits, scoring, pitches, sending and replies.

| Area | Your modules | Phase |
| --- | --- | --- |
| Demo sites | `demos/` (started in PR #6) | 2 |
| Preview host (Cloudflare Pages + a Worker) | new `preview/` folder in the repo, plus `demos/sync` code | 2, 4 |
| Pipeline board, tasks, notes, timeline | new `crm/` | 4 |
| Packages, proposals, invoices, payments | new `billing/` | 4 |
| Revenue report | `billing/` reports | 5 |
| Your dashboard pages | `web/<area>.py` per new page, `web/extras.py` deals part | 2, 4, 5 |

Not yours: `sources/`, `enrich/`, `audit/`, `scoring.py`, `pitch/`, `mailer/`, `outreach/`, `compliance.py` and their pages. One exception is agreed in advance: you add a single call to `demos.remove_orphans(con)` inside `compliance.forget()`, right after businesses are deleted (Step 1). Don't change anything else in that file.

## Contracts with Jason's half

These are fixed, and Jason's plan has the same table word for word, so neither of you needs to ask the other anything. Jason's first step copies this table into `docs/CONTRACTS.md`. Until that's merged, this table is the source of truth.

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


Changing a contract is the only time you must message Jason first. Everything else, you decide.

## Phase 2: demo sites, the flagship (weeks 1–5)

Phase 2 ends with the go/no-go test: 20 demos shown to real businesses, every reply read, and the concept banner checked on each. If those 20 do no better than plain pitches, stop after Step 2 and go straight to Phase 4. The printable audit report on Jason's side then becomes the main visual instead. Steps 1 to 4 are musts; Step 5 is worth doing if time allows.

### Step 0: merge PR #6 (today)

PR #6 (the demo builder) is already tested: 265 tests pass and the sample page follows every honesty rule. Under the working-alone rules you merge your own PRs, so open https://github.com/rau1b/leadscout/pull/6, check the GitHub check is green, and click **Merge pull request** with **Create a merge commit**.

### Step 1: finish the builder (1 day)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

1. Forget (contract C8): add ONE call, demos.remove_orphans(con), inside compliance.forget() right after the businesses are deleted. Change nothing else in compliance.py. Test that a forgotten business's page folder is gone immediately.
2. Lead statuses (contract C6): add 'meeting' and 'proposal' to db.STATUSES (one line). Nothing else in db.py.
3. Template choice (contract C3): use businesses.basic_category when that column exists and is not null (check with pragma table_info), else category and category_path as now.
4. Make the page feel like a website, not a contact card, without inventing anything: add clearly labelled placeholder sections such as "Your photos here", "Your services and prices here" and "Opening hours", styled as empty frames. A real fact always replaces its placeholder.
5. Offline tests for each point. Ruff and full suite pass. Commit, push, open a PR into main, merge it yourself when the GitHub check is green. Report the PR link and anything you did differently.
```

Done when: forget removes demo pages at once and the sample page reads like a website.

### Step 2: six vertical templates (2–3 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

1. Six templates in demos/templates: clinic/dentist, salon/spa, restaurant/cafe, coaching/tuition, real estate, general shop. Each is one fast, mobile-first page: click-to-call, WhatsApp (mobile numbers only), directions, hours when known, enquiry section with only our contact, the placeholders from Step 1 where facts are missing.
2. Each vertical gets its own layout and colour set, so two demos in the same street don't look identical. Neutral SVG or CSS illustrations only: no stock photos, no logos or photos from third-party sites, no invented reviews, prices or years.
3. Keep every honesty rule from PR #6: the concept banner, noindex, unguessable slug, 30-day expiry, refusal for suppressed businesses or the example sender.
4. A performance budget: each page stays under 30 KB with no JavaScript. Add a test that checks size and that no external requests are made.
5. Offline tests: each vertical renders from a minimal business row; template choice by basic_category and by category fallback. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: `leadscout demo` builds a distinct page for each of the six verticals.

### Step 3: the preview host on Cloudflare (3 days)

The preview host is free on Cloudflare's plan, needs a Cloudflare account, and lives on a subdomain of the studio domain, for example `demo.<studio domain>`.

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

Build the public preview host. It serves only static pages and stores no lead data.

1. A preview/ folder in the repo: a Cloudflare Pages project for the static demo pages plus a small Worker (wrangler config, JS, its own tests with vitest or miniflare). Routes:
   - GET /v/<slug>: a view ping from a tiny image in each demo. Record slug and time only, no IP, no cookies.
   - GET /u/<token>: an unsubscribe page with one confirm button; POST /u/<token>: the one-click unsubscribe (RFC 8058). Store token and time only.
   - GET /api/sync with a bearer secret: return new views and unsubscribes since the last sync, then mark them as handed over.
   Use Workers KV or D1 for storage, rate-limit each route, and serve noindex headers everywhere.
2. Config [preview]: base_url and project name. Secrets (Cloudflare API token, sync secret) go in .env only.
3. `leadscout demos publish`: copy every live, unexpired, unsuppressed demo into a build folder and deploy it with wrangler; set demos.url (contract C1) and log demo_published. Expired or forgotten demos are left out, so a deploy also takes them down (contract C8). Log demo_expired for those that aged out.
4. `leadscout demos sync`: pull views into demos.first_viewed_at and view_count, logging demo_viewed. Pull unsubscribe tokens and pass each to outreach.unsubscribe.resolve() then compliance.opt_out_business(con, business_id, "unsubscribe link") (contracts C4, C5). If that import fails because it isn't built yet, keep the tokens in a local queue table and log it. Run sync hourly from a small task you register in your own module (one additive line in app.py's lifespan) and from a button on a new Demos page (web/demos.py).
5. Docs in docs/STACK.md: Cloudflare setup step by step for a beginner (account, subdomain, API token, first deploy).
6. Offline tests (no Cloudflare in tests): publish builds the right folder and sets url; sync updates views and opts out a resolved token; a missing resolve() queues tokens. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: a published demo opens on your phone from `demo.<studio domain>`, and opening it shows as a view after the next sync.

### Step 4: before/after images (1–2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

1. Add Playwright (Chromium) as a dependency for demos only and document the one-time `playwright install chromium`.
2. `leadscout demos images <business_id>`: a 390 px wide screenshot of the demo, next to the "before": audits.screenshot_path when it exists (contract C2), otherwise a Playwright screenshot of their current website, otherwise a "No website today" panel. Compose both side by side into data/demos/<slug>/before-after.png by rendering a small HTML page and screenshotting it (no Pillow).
3. Show the image on the Demos page with a Download button (for sharing by hand on WhatsApp after a reply). Never send it automatically.
4. Offline tests mock Playwright. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: each demo has a before/after image you can download.

### Step 5 (if time allows): better demo copy through Claude Code

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

Add a Claude Code hand-off like /pitch-today: `leadscout demos prepare-copy` writes data/demo_copy_jobs.json with each lead's facts; a new .claude/commands/demo-copy.md tells Claude Code to write a 2-sentence intro and a services heading per lead using only those facts; `leadscout demos import-copy` loads them. A check rejects copy with any number, claim or name not in the facts, and the template copy stays the fallback. No Anthropic API (CLAUDE.md). Offline tests. Ruff and full suite pass. Commit, push, PR, merge when green.
```

**Phase 2 gate:** 20 demos shown to real businesses, every reply read, the banner checked on each page, and a written go or no-go on automating further.

## Phase 4: pipeline and billing (weeks 6–9)

Phase 4 ends when one real deal runs inside LeadScout from reply to paid invoice. Steps 1 to 4 are musts; Step 5 is worth doing if time allows. You can start Phase 4 while waiting on demo replies for the Phase 2 gate.

### Step 1: the pipeline board (2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

1. New page web/pipeline.py (nav link "Pipeline"): columns Replied, Meeting, Proposal, Won, Lost (contract C6). Cards show business name, area, demo status (C1) and the next task once Step 2 exists.
2. Drag a card between columns with Alpine.js (one static file, no build step), with a plain button fallback. A move may only go from replied, meeting or proposal to meeting, proposal, won or lost (C6), and logs stage_changed with the from and to stages only. Moving to Won sets won_at.
3. Never move a lead that is opted_out, bounced or suppressed; show those as read-only.
4. Offline tests: allowed and refused moves, the event, read-only suppressed leads. Ruff and full suite pass. Commit, push, PR into main, merge when the check is green.
```

Done when: replied leads appear on the board and can be moved to Meeting and Proposal.

### Step 2: tasks, notes and one timeline per lead (2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

1. New migration (next free number): tasks(id, business_id references businesses on delete cascade, due_at, text, done_at) and notes(id, business_id references businesses on delete cascade, body, created_at).
2. On the lead page add a Tasks and Notes panel from your own template partial (one include line in the lead template; nothing else changed there). Completing a task logs task_done (no task text in the event).
3. A Timeline panel built from events for that lead (contract C7: Jason's and yours), plus your notes and tasks, newest first. Unknown event types are skipped. History from before events existed won't show; say so in a small note.
4. The Pipeline nav link shows how many tasks are due today; a Due today list sits on top of the board.
5. Offline tests; forget removes tasks and notes. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: you can add "Call Tuesday 11:00" to a lead and see it on the board on Tuesday.

### Step 3: packages and hosted proposals (3 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

1. New migration: packages(id, name, price_inr, inclusions_json, active) and deals(id, business_id references businesses on delete cascade, package_id, quote_inr, proposal_slug, sent_at, accepted_at, status). A one-time step copies today's leads.quote_inr, paid_inr, deal_note and won_at into deals (leave the old columns in place, unused).
2. A Packages page (web/billing.py) to add Starter, Business, Store and so on, with INR prices and what's included. Move the existing Deals page to read deals.
3. A proposal for a lead: choose a package and timeline, then publish a static page to the preview host at /p/<slug> (noindex, unguessable slug, expires after 30 days) showing the demo (C1), the package, the price, the timeline and an Accept button. Log proposal_sent and move the lead to Proposal.
4. The Worker gets POST /p/<slug>/accept (records slug and time only); demos sync pulls accepts, sets deals.accepted_at, moves the lead to Won and logs proposal_accepted. The page shows a thank-you with your contact.
5. Offline tests (Worker tests in preview/). Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: a test proposal opened on your phone can be accepted, and the lead turns Won after sync.

### Step 4: invoices with a UPI QR code (2–3 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

1. New migration: invoices(id, number unique, deal_id, items_json, gstin, place_of_supply, tax_json, total_inr, issued_at, due_at, status) and payments(id, invoice_id, amount_inr, method one of UPI, bank, cash, paid_at, reference).
2. Config [billing]: studio legal name, address, UPI ID, optional gstin. Numbers run per Indian financial year (INV-2026-27-001) and never repeat or get reused.
3. When gstin is set, show GST fields and split CGST/SGST or IGST by place of supply; when it isn't, issue a plain invoice with no tax lines. Add a note in the README that the format should be checked with a CA; don't give tax advice in the app.
4. A UPI QR code (the qrcode package, SVG) encoding upi://pay?pa=<UPI ID>&pn=<name>&am=<amount due>&cu=INR&tn=<invoice number>, printed on the invoice.
5. An A4 print layout plus `leadscout invoice <number> --pdf` using Playwright. Record part and full payments; a fully paid invoice logs invoice_paid; sending one logs invoice_sent. Invoices are never deleted, only cancelled with a reason (keep this even on forget: tell me in your report how you handled forget for invoices, since tax records may need keeping).
6. Offline tests: numbering across a financial year boundary, GST and no-GST totals, QR payload, payments. Ruff and full suite pass. Commit, push, PR, merge when green.
```

Done when: you can issue an invoice, scan its QR code with a UPI app (stop before paying), and mark it paid.

### Step 5 (if time allows): client content form

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

After a deal is won, publish a form at /c/<slug> on the preview host (noindex, unguessable, expires after 30 days) where the client uploads logo, photos, text and their services list. Store uploads in Cloudflare R2 on the free tier; demos sync downloads them into data/clients/<business_id>/ and deletes them from R2. Forget deletes the local folder too. Size and type limits on uploads. Offline tests. Ruff and full suite pass. Commit, push, PR, merge when green.
```

**Phase 4 gate:** one real deal from reply to paid, entirely in LeadScout: board, tasks, proposal accepted, invoice paid.

## Phase 5: your share of analytics (week 10)

Your half of Phase 5 is the revenue report; Jason's half is the lead funnel, score calibration and pitch A/B tests.

### Step 1: the revenue report (2 days)

```
Read CLAUDE.md, docs/TRACKS.md and docs/CONTRACTS.md first. Branch rau1b: git fetch origin, merge origin/main, run tests.

New page web/revenue.py: deals won and money collected per month; by package; by business type (businesses.basic_category, contract C3, falling back to category) and locality; proposal acceptance rate; average days from reply to paid (from events, contract C7); demos built vs viewed vs won; invoices outstanding with days overdue. Add a CSV export of the invoice register for your CA (number, date, client, GSTIN if any, taxable value, tax, total). Offline tests with a seeded database. Ruff and full suite pass. Commit, push, PR, merge when green.
```

**Finishing 2.0:** Jason tags `v2.0.0` once his Phase 5 steps and your Phase 4 gate are both in main. Nothing for you to coordinate.

## Non-code tasks

The demo test is the most important task in this plan: it decides whether the flagship feature is worth automating.

- [ ] This week: run a search for one Goa locality, pick 3 leads with no website or a weak one, build their demos with `leadscout demo`, and check each page's concept banner.
- [ ] Show those 3 in person, on your phone or printed. Note each owner's reaction in one line.
- [ ] Keep going to 20 demos shown, across at least two business types. From Phase 4 Step 2 onwards, record reactions as notes in LeadScout; before that, a simple sheet is fine.
- [ ] Decide go or no-go: if the 20 demos get clearly better replies than plain pitches, carry on with Phase 2 Steps 3–5. If not, skip to Phase 4.
- [ ] Before Step 3: create a free Cloudflare account and put the studio domain's DNS on it, so `demo.<studio domain>` can point at the preview host.
- [ ] Before Phase 4 Step 3: decide your packages and prices, and get your UPI ID and (if registered) GSTIN ready.

## When something goes wrong

Almost everything here you fix alone. The one exception is a contract that has to change: message Jason first.

| What happened | What you do |
| --- | --- |
| A step fails and Claude Code couldn't fix it | Paste the recovery prompt below. |
| The migration test fails after merging main | Jason's migration took your number. Tell Claude Code: "rename my migration to the next free number and update anything that refers to it". |
| A merge conflict in a shared file (`app.py`, `cli.py`, `base.html`, `config.example.toml`, `CLAUDE.md`, the lead page template) | Tell Claude Code: "resolve by keeping both sides' additions". These files only get additive lines, so both sides belong. |
| Tests fail after merging main, in Jason's code | Don't edit his modules. If main itself has been red for more than a day, `git revert` the commit that broke it in a small PR, and open a GitHub issue saying which test failed and that you reverted it. He can re-apply it. |
| Your step needs something from his side that isn't in the contracts | Use the fallback from the contracts table and keep going. Write a GitHub issue describing what you'd like later; don't build it in his modules. |
| Claude Code wants to change a file in `sources/`, `audit/`, `scoring.py`, `pitch/`, `mailer/`, `outreach/` or `compliance.py` | Say no, except for the one agreed `demos.remove_orphans(con)` line in `compliance.forget()`. Repeat the rule: work only in the Show & close modules. |
| The GitHub check on your PR is red | Fix it on `rau1b`, push, and wait for green. Never merge red. |
| `pip install` fails with a locked file (WinError 32) | Stop the dashboard first: `leadscout stop`, or Ctrl+C the terminal running `leadscout serve`. |
| You committed `.env`, `config.toml`, a Cloudflare token or anything in `data/` by mistake | The repo is public, so treat it as leaked straight away: revoke the Cloudflare API token and the sync secret, revoke the Google API key, run `leadscout gmail-login` again. Then remove the file in a new commit. |
| A demo page shows something untrue or a business asks for it to come down | Delete its demos row (or run forget for that business) and run `leadscout demos publish`; the page is gone from the preview host after that deploy. |
| A contract looks wrong or blocks you | Message Jason with the contract number (C1–C10) and your proposed change. Change it only after he agrees, then update both plans and `docs/CONTRACTS.md`. |

**Recovery prompt**

```
The last step didn't finish cleanly. Do this:
1. Run git status and show me what's changed but not committed.
2. Run ruff and the full test suite; list every failure with the file and test name.
3. Fix the failures inside my own track's modules (see docs/TRACKS.md). Don't edit the other track's files.
4. If a failure comes from the other track's code or from a contract in docs/CONTRACTS.md, don't fix it; tell me which test and why.
5. Re-run ruff and the full suite until they pass, then commit and push. Don't open or merge a PR yet; show me a summary first.
```
