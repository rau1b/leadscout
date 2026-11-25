# LeadScout

Private tool for two people selling websites to **Indian local businesses**. ₹0 budget: only free services (Overture Maps, Nominatim, PageSpeed with a free key, Gmail API, Claude Code on the user's Pro plan). Never add a paid API or the Anthropic API.

- Stack, pipeline, commands: `docs/STACK.md`. Setup: `README.md`.
- Outreach and privacy rules the code must enforce: `docs/INDIA_RULES.md`, plus `docs/US_RULES.md` for the small US test (email only, CAN-SPAM footer, sending in the lead's local time).
- Product record and dashboard design contract: `PRODUCT.md`, `.impeccable/surfaces/src-leadscout-web.md` (Bahi-khata direction).
- Run things with `.venv/Scripts/leadscout ...` from the project root; tests with `.venv/Scripts/python -m pytest`.

Hard rules:
- Never automate WhatsApp sends, phone calls or SMS. Generate `wa.me` / `mailto:` links for a human.
- Every send and export checks the hashed suppression list first.
- Pitches cite only measured facts; no invented numbers, reviews or claims.
- Respect warm-up caps, sending windows (IST, or a US lead's local time) and the bounce pause in `mailer/sender.py`.
- Tests never hit the network or send email.
