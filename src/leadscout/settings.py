"""The dashboard's Settings page: config.toml as a form. Validates, keeps keys the form doesn't show, writes atomically."""

import copy
import os
import re
import tomllib
from datetime import date, datetime

import phonenumbers
import tomli_w

from leadscout import backups, config, db
from leadscout.compliance import DAYS
from leadscout.config import IST

TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TEXT = [("sender", k) for k in ("name", "business", "email", "phone", "city", "portfolio")] + [("pitch", "offer"), ("pitch", "pitch_line")]
# name -> (section, key, lowest, highest): whole numbers the form edits as they are.
INTS = {
    "sending.whatsapp_daily_cap": ("sending", "whatsapp_daily_cap", 1, None),
    "sending.min_gap_seconds": ("sending", "min_gap_seconds", 1, None),
    "sending.max_gap_seconds": ("sending", "max_gap_seconds", 1, None),
    "sending.followup_after_days": ("sending", "followup_after_days", 1, None),
    "sending.max_followups": ("sending", "max_followups", 0, 1),  # docs/INDIA_RULES.md: at most one follow-up
    "scoring.min_score": ("scoring", "min_score", 0, 100),
    "retention.purge_uncontacted_after_days": ("retention", "purge_uncontacted_after_days", 1, None),
    "backups.keep_days": ("backups", "keep_days", 1, None),
}
WARMUP = ["week 1", "week 2", "week 3 onward"]


def _get(raw, section, key, default=""):
    return raw.get(section, {}).get(key, default)


def current() -> dict:
    """config.toml as tomllib reads it (the example while there's no config.toml yet)."""
    return copy.deepcopy(config.load().raw)


def form_values(raw: dict) -> dict:
    """The strings and lists the form shows for this config."""
    v = {f"{s}.{k}": str(_get(raw, s, k)) for s, k in TEXT}
    v |= {name: str(_get(raw, s, k)) for name, (s, k, _, _) in INTS.items()}
    sc = raw.get("sending", {})
    v |= {
        "sending.window_start": sc.get("window_start", ""),
        "sending.window_end": sc.get("window_end", ""),
        "sending.days": list(sc.get("days", [])),
        "sending.skip_dates": "\n".join(sc.get("skip_dates", [])),
        "sending.max_bounce_rate": f"{sc.get('max_bounce_rate', 0.05) * 100:g}",  # shown as a percentage
        "scoring.high_value": "\n".join(_get(raw, "scoring", "high_value", [])),
        "scoring.excluded": "\n".join(_get(raw, "scoring", "excluded", [])),
    }
    for i, n in enumerate(sc.get("warmup", [15, 30, 50])[:3]):
        v[f"sending.warmup.{i}"] = str(n)
    return v


def _lines(text: str) -> list[str]:
    """One item per line (commas work too); blanks dropped, order kept."""
    return [x.strip() for x in re.split(r"[\n,]", text) if x.strip()]


def _is_date(s: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:  # e.g. 2027-02-30
        return False


def parse(form, base: dict) -> tuple[dict, dict]:
    """Apply the submitted form to a copy of `base`. Returns (new config, {field name: error}); keys not on the form stay."""
    raw = copy.deepcopy(base)
    errors = {}

    def put(section, key, value):
        raw.setdefault(section, {})[key] = value

    for s, k in TEXT:
        value = (form.get(f"{s}.{k}") or "").strip()
        if not value:
            errors[f"{s}.{k}"] = "Fill this in."
        put(s, k, value)
    email = raw["sender"]["email"]
    if email and not EMAIL.match(email):
        errors["sender.email"] = "That doesn't look like an email address."
    phone = raw["sender"]["phone"]
    if phone:
        try:
            ok = phonenumbers.is_valid_number(phonenumbers.parse(phone, "IN"))
        except phonenumbers.NumberParseException:
            ok = False
        if not ok:
            errors["sender.phone"] = "Not a valid Indian phone number, e.g. +91 98765 43210."

    for name in ("sending.window_start", "sending.window_end"):
        value = (form.get(name) or "").strip()
        if not TIME.match(value):
            errors[name] = "Use 24-hour HH:MM, e.g. 10:00."
        put("sending", name.split(".")[1], value)
    if not errors.keys() & {"sending.window_start", "sending.window_end"} and raw["sending"]["window_start"] >= raw["sending"]["window_end"]:
        errors["sending.window_end"] = "The window must end after it starts."

    days = form.getlist("sending.days") if hasattr(form, "getlist") else form.get("sending.days", [])
    if not days or any(d not in DAYS for d in days):
        errors["sending.days"] = "Pick at least one day."
    put("sending", "days", [d for d in DAYS if d in days])  # always in week order

    dates = _lines(form.get("sending.skip_dates") or "")
    bad = [d for d in dates if not _is_date(d)]
    if bad:
        errors["sending.skip_dates"] = f"Use YYYY-MM-DD, one per line. Not a date: {', '.join(bad)}."
    put("sending", "skip_dates", sorted(set(dates)))

    def whole(name, lo, hi):
        text = (form.get(name) or "").strip()
        try:
            n = int(text)
        except ValueError:
            errors[name] = "Enter a whole number."
            return None
        if n < lo or (hi is not None and n > hi):
            errors[name] = f"Use a number from {lo} to {hi}." if hi is not None else f"Use {lo} or more."
        return n

    for name, (s, k, lo, hi) in INTS.items():
        n = whole(name, lo, hi)
        if n is not None:
            put(s, k, n)
    if not errors.keys() & {"sending.min_gap_seconds", "sending.max_gap_seconds"} and raw["sending"]["min_gap_seconds"] > raw["sending"]["max_gap_seconds"]:
        errors["sending.max_gap_seconds"] = "Must be at least the shortest gap."

    warmup = [whole(f"sending.warmup.{i}", 1, None) for i in range(3)]
    if None not in warmup:
        put("sending", "warmup", warmup)

    text = (form.get("sending.max_bounce_rate") or "").strip().rstrip("%")
    try:
        pct = float(text)
        if not 0 < pct < 100:
            errors["sending.max_bounce_rate"] = "Use a percentage above 0 and below 100."
        else:
            put("sending", "max_bounce_rate", round(pct / 100, 4))
    except ValueError:
        errors["sending.max_bounce_rate"] = "Enter a number, e.g. 5."

    put("scoring", "high_value", _lines(form.get("scoring.high_value") or ""))
    put("scoring", "excluded", _lines(form.get("scoring.excluded") or ""))
    return raw, errors


def changed_keys(old: dict, new: dict) -> list[str]:
    """Dotted names of the settings that differ, e.g. ["sending.window_end"]. Names only, never values."""
    keys = []
    for section in sorted(old.keys() | new.keys()):
        a, b = old.get(section, {}), new.get(section, {})
        if not isinstance(a, dict) or not isinstance(b, dict):
            keys += [section] if a != b else []
            continue
        keys += [f"{section}.{k}" for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]
    return keys


def save(raw: dict, actor: str = "dashboard") -> list[str]:
    """Write config.toml (backing up the old one first) and log which keys changed. Returns them."""
    path = config.home() / "config.toml"
    old = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else current()
    keys = changed_keys(old, raw)
    if not keys and path.exists():
        return []
    if path.exists():
        folder = backups.folder(db.default_path())
        folder.mkdir(exist_ok=True)
        (folder / f"config-{datetime.now(IST):%Y%m%d-%H%M%S}.toml").write_bytes(path.read_bytes())
        backups.prune(folder, raw.get("backups", {}).get("keep_days", 14))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("# Edited on the dashboard's Settings page. Secrets (API keys, Gmail login) stay in .env and data/.\n"
                   + tomli_w.dumps(raw), encoding="utf-8")
    os.replace(tmp, path)  # atomic: a crash leaves the old file or the new one, never half of each
    con = db.connect()
    db.log_event(con, "settings_changed", actor=actor, keys=keys)
    con.commit()
    return keys
