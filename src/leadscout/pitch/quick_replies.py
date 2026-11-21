"""Ready-made answers to the replies leads send most often. You edit before sending.

Override or add your own in config.toml under [quick_replies] (name = "text").
Anything in [square brackets] must be filled in; the dashboard won't send while brackets remain.
Placeholders: {name} business, {sender} your name, {phone} your phone, {portfolio} your portfolio link.
"""

import re

DEFAULTS = {
    "Price": (
        "Thanks for getting back to me! A simple, mobile-friendly website for {name} with a WhatsApp button, "
        "Google Maps directions and a contact form costs [your price]. That includes [what's included, e.g. "
        "domain and hosting for a year], and I can have it live in about [number of days] days.\n\n"
        "Happy to send the free homepage mockup first so you can see it before deciding."
    ),
    "Send mockup": (
        "Great, thank you! I'll put together a free mockup of {name}'s homepage. Could you send your logo and "
        "3 or 4 photos (your place, your team or your work) to me on WhatsApp at {phone}? "
        "I'll share the mockup within [number of days] days."
    ),
    "Call": (
        "Happy to explain on a quick call. What time suits you? You can also call or WhatsApp me on {phone}."
    ),
    "Examples": (
        "Of course. You can see some of my work here: {portfolio}\n\n"
        "If you'd like, I can also make a free mockup for {name} so you can see exactly how yours would look."
    ),
    "Not now": (
        "No problem at all, thanks for letting me know. I won't email again. If you ever need a website, "
        "just reply here."
    ),
}

UNFILLED = re.compile(r"\[[^\]]+\]")


def all_replies(cfg) -> dict[str, str]:
    return {**DEFAULTS, **cfg.raw.get("quick_replies", {})}


def fill(text: str, lead: dict, cfg) -> str:
    s = cfg.sender
    body = text.format(name=lead["name"], sender=s["name"], phone=s["phone"], portfolio=s["portfolio"])
    return f"{body}\n\n{s['name']}\n{s['phone']}"


def unfilled(text: str) -> list[str]:
    return UNFILLED.findall(text)
