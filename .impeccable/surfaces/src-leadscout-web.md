---
version: 1
slug: "src-leadscout-web"
primary_target: "src/leadscout/web"
related_targets: []
---

# LeadScout dashboard

Scope: the local dashboard (src/leadscout/web). Mode: Operate. Laptop-first, two users (owner and partner), daily review session.

Job: see today's sending progress, review and edit drafted pitches, approve them, handle replies and opt-outs, open WhatsApp/mail links by hand.

## Direction contract

THESIS: The outreach day kept like a shop's bahi-khata: one page per day with a fixed capacity, totals carried forward. Refuses the default SaaS shell of stat-card tiles over a grey table.

OWN-WORLD: Bordeaux wine and warm sand (user-pinned palette, 21 Nov 2026, replacing the original bahi red and haldi yellow): bordeaux (#531B24) cloth rail with a dashed sand (#C6B7A2) stitch; linen (#E7D8C3) active tab and notes; porcelain (#F3ECE2) page with cards and fields a step lighter (#FFFCF8); wine (#6A2931) for names, links and figures; text #2A1A1D. Green only for replied/won, a clear red (#B42318) for bounced/opt-out. Mukta (Ek Type) throughout with tabular figures. One colour code per lead status, used everywhere. Dense rows, no card tiles, 6-8px radii.

STORY: Open the dashboard, see today's page (sent / cap, next send time), approve the pitches waiting, check replies, close the day. Every lead shows the measured fact behind it.

FIRST VIEWPORT: Left bordeaux rail (nav with counts). Header: "Today", date, sending window, warm-up week, primary action "Approve N". Left column: Today's page, a fixed-capacity slot column (cap = warm-up limit) filled with sent names and times in wine, empty slots below, a red double rule with what carries to tomorrow. Right: dense lead table (business, category, what's wrong, score, email, status chip).

FORM: Bahi-khata, candidate 5 of 7; seed:ac3ca7f66de52070. Raises: capacity page (from j-card), density courage (from event catalog), single status colour code (from catalog sleeve).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
