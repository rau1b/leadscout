---
description: Write today's LeadScout pitches from data/pitch_jobs.json (uses your Claude Pro plan, no API cost)
---

Write personalised cold-email pitches for the leads in `data/pitch_jobs.json`.

If the file is missing or has no leads, tell me to run `leadscout pitch --prepare 50` first and stop.

For each lead in `leads`, write a pitch using ONLY the facts in that lead's record (site_class, fetch_error, perf_score, lcp_s, https, viewport, copyright_year, has_whatsapp, reasons, category, locality). Use `sender`, `offer`, `pitch_line` and `opt_out_line` from the top of the file. `template_draft` shows a safe baseline; improve on it, don't copy it.

Rules (from docs/INDIA_RULES.md):
- Cite only the measured facts given. Never invent numbers, reviews, competitors or claims.
- No fake urgency, no scare claims ("Google will remove you"), never pretend to be a customer or Google.
- `fetch_error: "bad_certificate"`: say the security certificate has a problem, so some browsers and phones may warn visitors. Never claim every browser shows a warning.
- Say plainly who the sender is and that this is a paid service, with a free, no-obligation first step (the `offer`).
- Plain text, under 120 words, no links except the sender's portfolio in the signature (if one is set), no attachments.
- Location: if the lead's `city` is the sender's city (Hyderabad and Secunderabad count as one), you may say "here in <city>". Otherwise say the sender is based in their city and works with businesses across India online. Never imply the sender is local when they are not. Mention the lead's neighbourhood (first part of `area`) when present.
- Indian English, warm and direct. Address it to "<business name> team" unless a person's name is in the business name (e.g. "Dr. Teeth" stays as the business).
- Subject: specific to their problem, under 60 characters, no clickbait, no ALL CAPS, no emoji.
- End with the signature built from the sender details that are filled in (name, business, city, phone, portfolio; leave out blank ones) and then `opt_out_line` exactly.
- Also write a WhatsApp version (under 600 characters, same facts, ends with "If not, just say no and I won't message again.").

Write the results to `data/pitch_results.json` as a JSON array:
`[{"id": "<lead id>", "subject": "...", "body": "...", "whatsapp": "..."}]`

Then run `.venv/Scripts/leadscout pitch --import` and tell me how many were imported. The import sets aside any pitch containing a number that isn't in the lead's facts or the sender details. If some were set aside, rewrite just those from `data/pitch_results.rejected.json` without the listed numbers, write them to `data/pitch_results.json` again and re-run the import. Don't send anything; I approve pitches in the dashboard.
