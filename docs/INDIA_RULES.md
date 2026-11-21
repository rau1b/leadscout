# India outreach rules

The rules LeadScout follows, and enforces in code where it can. This is not legal advice. Rules change, so re-check the sources before you scale up.

Last checked: 21 Nov 2026.

## Channel by channel

| Channel | Verdict | Why |
|---|---|---|
| Email | **Primary cold channel** | India has no CAN-SPAM-style email law. The risks are deliverability and reputation, not a regulator |
| In-person visit with a printed audit | **Best for local shops** | No regulation, and it converts well with small Indian businesses |
| WhatsApp | **Manual, low volume, at your own risk** | Meta's policy requires opt-in before a business messages someone. Cold messages break it, and blocks/reports get the number restricted |
| Phone call | **Only after they reply** | TRAI: promotional calls must come from a registered 140-series number. Unregistered 10-digit numbers get barred, then disconnected and blacklisted |
| SMS | **Not supported** | Commercial SMS needs DLT registration (entity, header, templates). Not worth it for this |

### Email

- Send from a **separate outreach domain** (e.g. `getyourname.in` rather than your main one), on Zoho Mail or Google Workspace.
- Set up **SPF, DKIM and DMARC** before the first send. Gmail and Yahoo reject or spam-folder mail without them.
- **Warm up** new inboxes: start around 10/day and stay under ~30–40/day per inbox.
- Every email carries your real name, business name, city, phone number and a plain opt-out line ("Reply 'no' and I won't email again").
- Send one email plus at most one follow-up. Stop on any reply that says no.
- Contact email comes only from the business's own website or listing, never from guessed or bought lists.
- Enforced in code: daily cap per inbox, follow-up limit, suppression check.

### WhatsApp

- Meta's WhatsApp Business policy requires opt-in before you message someone. A cold first message breaks it however polite it is. Every block or report lowers the number's standing, and enough of them get it restricted or banned.
- So LeadScout **never automates WhatsApp**: no bulk senders, no WhatsApp Web bots, no Cloud API for cold leads. It only builds a `wa.me/91XXXXXXXXXX?text=…` link for a message you choose to send yourself.
- If you use it anyway:
  - Use a **separate WhatsApp Business number**, never your personal one.
  - Send at most ~15–20 new chats a day, one message each, no follow-up spam.
  - Write a personal, specific message (the pitch is built for this), never a broadcast.
  - Stop at the first "no" and add them to the suppression list.
- After a business replies, WhatsApp becomes a normal, safe channel for the conversation.
- The WhatsApp Business **API** is for customers who opted in. Marketing templates cost about ₹0.86 per delivered message in India. Not useful for cold leads.
- Enforced in code: WhatsApp links only for mobile numbers, a daily cap on links opened, suppression check.

### Phone calls

- Under TRAI's TCCCPR (amended Feb 2025, tightened again in 2026), promotional calls must come from a registered **140-series** number. Calls and SMS from ordinary 10-digit numbers count as unregistered telemarketing.
- Complaints against an unregistered sender lead to its outgoing services being barred for 15 days on the first violation. Repeat violations mean **every number in the sender's name is disconnected for a year and blacklisted**.
- Practical rule: **don't cold call from your SIM.** Call only when the business replied or asked you to.
- LeadScout has no dialer and never will.

### Timing

- Send only between **10:00 and 19:00 IST, Monday to Saturday**, and avoid major festival days. This is good practice, not law. Enforced in code as quiet hours for the dashboard's "send" buttons.

## Data and privacy

### DPDP Act 2023 and DPDP Rules 2025

- The Rules were notified in **November 2025** and are phased in. Most obligations on data fiduciaries (notice, consent, security, retention, breach reporting) apply about **18 months later, around 13 May 2027**.
- Section 3(c)(ii) of the Act excludes personal data that the person **made public themselves**. Contact details a business owner published on their own Google listing likely fall under it. Don't lean on that alone, and design as if the Act applies:
  - Collect the minimum: business name, public phone, public email, website, rating. No personal social profiles, no home addresses.
  - Store locally only. Never sell, share or upload lead lists.
  - **Opt-outs are permanent and immediate.** One reply of "no", "stop" or "not interested" puts the number/email on the suppression list.
  - Delete on request: `leadscout forget <phone|email>` removes all their data and keeps only a hashed suppression entry.
  - Retention: leads you never engaged with are purged after 90 days.

### Google Maps Platform terms

- Using the Places API, not scraping Maps, keeps you inside Google's terms.
- Google lets you store `place_id` indefinitely but restricts caching other Places content. LeadScout keys everything on `place_id`, treats the other Places fields as a short-lived working cache (auto-expired after 30 days for leads you haven't contacted), and re-fetches when you act on a lead. Check the current Maps Platform service terms before you scale up.

## Pitch content rules (in the AI system prompt)

- Cite only numbers we measured (load time, score, missing HTTPS). Nothing made up, nothing exaggerated.
- No fake urgency ("offer ends today"), no fear claims ("Google will delist you"), no pretending to be Google or a customer.
- Be clear about who you are and that you're offering a paid service.
- Open with something genuinely positive when it's true (e.g. "4.7★ from 230 reviews").
- Use a low-pressure call to action: a free mockup or a free audit report.
- Always include an opt-out line.

## Sources

- DPDP Rules 2025, phased rollout: [PIB](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf), [YourStory](https://yourstory.com/2025/11/digital-personal-data-protection-dpdp-rules-2025-rollout-over-18-months)
- TRAI TCCCPR amendment (Feb 2025): [TRAI PR 11/2025](https://cms.trai.gov.in/sites/default/files/2025-02/PR_No.11of2025.pdf), [JSA summary](https://www.jsalaw.com/wp-content/uploads/2025/02/JSA-Prism-Telecommunications_February-2025_TCCCPR-amendments.Final_.pdf)
- TRAI 140-series for promotional calls (2026): [TRAI PR 91/2026](https://trai.gov.in/sites/default/files/2026-07/PR_No91of2026.pdf), [TRAI PR 119/2026](https://www.trai.gov.in/sites/default/files/2026-09/PR_No119of2026.pdf)
- WhatsApp opt-in requirement: [Meta: Get opt-in for WhatsApp](https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in)
- WhatsApp India pricing: [Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing), [MyOperator 2026](https://myoperator.com/blog/whatsapp-business-api-pricing-india-2026)
- Google Maps Platform India pricing: [India pricing](https://developers.google.com/maps/billing-and-pricing/pricing-india), [India billing FAQ](https://developers.google.com/maps/billing-and-pricing/india)
- Places field tiers: [Place Data Fields (New)](https://developers.google.com/maps/documentation/places/web-service/data-fields), [Text Search (New)](https://developers.google.com/maps/documentation/places/web-service/text-search)
