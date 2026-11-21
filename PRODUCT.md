# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python, FastAPI + Jinja2 + HTMX, served locally by `leadscout serve` (no JS build step, no hosting). Chosen with the user during stack planning; see docs/STACK.md.

## Users

Two people (the user and a partner) who sell websites to Indian local businesses. They use the dashboard mostly on a laptop, in a daily sit-down session: review the day's leads, edit and approve pitches, watch sending progress, and handle replies. Each may send from their own Gmail account.

## Product Purpose

LeadScout finds Indian local businesses with no website or a weak one (free Overture Maps data), audits their sites, scores them, drafts honest pitches, and sends approved emails through Gmail at a safe pace (warm-up 15/30/50 a day). Success = 50 well-targeted, personal emails a day and replies that turn into paid website projects, with zero money spent on tools.

## Positioning

Every pitch is built from that business's own measured facts (expired domain, social-only presence, mobile load time) rather than a generic blast, and a human approves every message before it goes out.

## Operating Context

- Runs on the user's Windows laptop; data lives in one SQLite file.
- Daily ritual: run find/audit/score, draft pitches (templates or Claude Code `/pitch-today`), approve in the dashboard, let `leadscout send` work through the IST sending window.
- Outreach channels: email (automated, capped), WhatsApp click-to-chat links (manual only), walk-in visits.

## Capabilities and Constraints

- Zero budget: only free services (Overture Maps, Nominatim, PageSpeed with a free key, Gmail API, Claude Code on an existing Pro plan).
- Must follow docs/INDIA_RULES.md: no automated WhatsApp, calls or SMS; opt-outs are permanent; pitches cite only measured numbers.
- Lead statuses: new, drafted, approved, contacted, replied, won, lost, opted_out, bounced, excluded.

## Brand Commitments

None. Personal, private project; not public. No studio name, logo or colours.

## Evidence on Hand

Real lead data from Overture Maps (e.g. Kukatpally, Hyderabad). No testimonials, clients or results yet; never fabricate them in pitches or UI.

## Product Principles

1. A human approves every message; the tool drafts and paces, never decides alone.
2. Show the measured fact behind every lead, so the pitch can be trusted.
3. Protect the sender: caps, opt-outs and bounce limits are visible and never bypassed.
4. Today's work first: the dashboard opens on what needs doing now.
