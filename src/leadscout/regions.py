"""India and a small US test: the few things that differ by country.

- Phone numbers are read in the country's format.
- Each lead is emailed only inside the sending window of its own local time: IST for India, the lead's US
  time zone for the US. The daily warm-up cap is shared, because it's one Gmail account.
- US emails follow CAN-SPAM (docs/US_RULES.md): your postal address and a line saying it's a business offer.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from leadscout.config import IST

COUNTRIES = {"IN": "India", "US": "USA"}

# Used when config.toml has no [sending.us] table. US federal holidays (observed dates) are skipped.
US_DEFAULTS = {
    "window_start": "10:00",
    "window_end": "16:00",
    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "skip_dates": ["2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", "2027-06-18",
                   "2027-07-05", "2027-09-06", "2027-11-25", "2027-11-26", "2027-12-24"],
}


def country_of(value: str | None) -> str:
    return value if value in COUNTRIES else "IN"


def local_tz(country: str, lat: float | None = None, lon: float | None = None) -> ZoneInfo:
    """The lead's time zone. US zones come from longitude, which is right for nearly every city; near a zone
    line it can be an hour off, which the window's margins absorb."""
    if country_of(country) == "IN":
        return IST
    if lon is None:
        return ZoneInfo("America/Chicago")  # middle of the country: an hour off at worst for the mainland
    if lon < -140 and (lat or 0) < 30:
        return ZoneInfo("Pacific/Honolulu")
    if lon < -130:
        return ZoneInfo("America/Anchorage")
    if -115 <= lon < -109 and (lat or 0) < 37:
        return ZoneInfo("America/Phoenix")  # Arizona keeps standard time all year
    if lon < -114.5:
        return ZoneInfo("America/Los_Angeles")
    if lon < -101.5:
        return ZoneInfo("America/Denver")
    if lon < -86.5:
        return ZoneInfo("America/Chicago")
    return ZoneInfo("America/New_York")


def window(cfg, country: str) -> dict:
    """The [sending] settings for this country: India uses [sending], the US uses [sending.us] (or the defaults)."""
    if country_of(country) == "IN":
        return cfg.sending
    return {**US_DEFAULTS, **(cfg.sending.get("us") or {})}


def open_now(cfg, country: str, lat: float | None = None, lon: float | None = None, at: datetime | None = None) -> bool:
    from leadscout.compliance import in_window

    tz = local_tz(country, lat, lon)
    return in_window(window(cfg, country), (at or datetime.now(IST)).astimezone(tz))


def any_open_now(cfg, countries, at: datetime | None = None) -> bool:
    """True if some lead somewhere could be emailed now. For the US, any mainland zone being open counts."""
    for c in set(countries):
        if c == "US":
            if any(open_now(cfg, "US", None, lon, at) for lon in (-75, -90, -105, -112, -120)):
                return True
        elif open_now(cfg, c, at=at):
            return True
    return False


def needs_postal_address(country: str) -> bool:
    return country_of(country) == "US"
