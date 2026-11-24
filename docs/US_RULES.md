# US test: rules LeadScout follows

LeadScout is built for India (see `INDIA_RULES.md`). It can also run a small US test: one niche in a few cities,
email only. This page covers what changes for US leads. Everything in `INDIA_RULES.md` that isn't India-specific
(cite only measured facts, permanent opt-outs, warm-up caps, a human approves every email) still applies.

Not legal advice. Summary of the FTC's CAN-SPAM guide: https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business

## Email: CAN-SPAM

Cold business email is legal in the US if every message:

- **Has honest headers.** From, To and Reply-To name you and your real Gmail address. LeadScout sends from your own account.
- **Has an honest subject.** No "Re:" on a first email, no fake urgency. The follow-up uses "Re:" only because it really is a reply in the same thread.
- **Says it's an offer.** LeadScout adds "This is a business offer from <your studio>, <your postal address>." to every US email at send time, so it's there whoever wrote the pitch.
- **Carries your valid postal address.** A street address, a post office box, or a private mailbox. Set `postal_address` under `[sender]` in `config.toml`. **US emails don't send until it's set.** An India Post PO box works if you'd rather not use your home address.
- **Lets them opt out, and honours it fast.** The law allows 10 business days; LeadScout does it at once. A "no" reply or the List-Unsubscribe button puts the address on the hashed opt-out list for good.

Fines are per email, so the code enforces the footer and the address check instead of leaving them to the pitch.

## No calls, texts or WhatsApp

US cold calls and texts fall under the TCPA and state laws, with heavy per-message fines. LeadScout shows no
WhatsApp link for US leads and writes no WhatsApp text for them. Talk on the phone only after they reply and ask.

## Sending hours

US leads are emailed 10:00-16:00 **their local time**, Monday to Friday, skipping US federal holidays. The time
zone comes from the lead's map position. Change it under `[sending.us]` in `config.toml`. That's about
20:30-02:30 IST for the East Coast and 22:30-04:30 IST for the West Coast, so leave the dashboard sending
overnight, or run `leadscout send` before bed. The daily warm-up cap is shared with India: it's one Gmail account.

## Pitches

- US English, plain and direct. Prices in dollars only if you choose to quote one.
- Say plainly where you are: "based in Goa, India, working with US businesses remotely". Never imply you're local.
- Same fact rule as India: only what LeadScout measured on their site.

## Getting paid

Payment from a US client is an export of services: no GST if you file a Letter of Undertaking (LUT) on the GST
portal, and keep the bank's foreign inward remittance record (FIRC or e-FIRA) for each payment. PayPal, Wise and
Payoneer all work. Deals are tracked in rupees in the dashboard: enter what actually landed in your account.
