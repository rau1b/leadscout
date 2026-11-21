"""Settings from config.toml and .env in the project folder (the folder you run leadscout from)."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def home() -> Path:
    return Path(os.environ.get("LEADSCOUT_HOME", Path.cwd()))


def data_dir() -> Path:
    d = home() / "data"
    d.mkdir(exist_ok=True)
    return d


def _load_env() -> None:
    env = home() / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]  # KEY="value" is common in .env files
            os.environ.setdefault(k.strip(), v)


@dataclass
class Config:
    raw: dict

    @property
    def sender(self) -> dict:
        return self.raw["sender"]

    @property
    def pitch(self) -> dict:
        return self.raw["pitch"]

    @property
    def sending(self) -> dict:
        return self.raw["sending"]

    @property
    def scoring(self) -> dict:
        return self.raw["scoring"]

    @property
    def retention(self) -> dict:
        return self.raw.get("retention", {"purge_uncontacted_after_days": 90})

    @property
    def google_api_key(self) -> str:
        return os.environ.get("GOOGLE_API_KEY", "")


EXAMPLE = Path(__file__).resolve().parents[2] / "config.example.toml"


def load() -> Config:
    _load_env()
    path = home() / "config.toml"
    if not path.exists():
        path = EXAMPLE  # fine for browsing the dashboard; sender_problem() blocks drafting and sending
    with open(path, "rb") as f:
        return Config(tomllib.load(f))


def sender_problem(cfg: Config) -> str | None:
    """Why pitches can't be drafted or sent yet (they'd be signed "Your Name"), or None if [sender] is filled in."""
    if not (home() / "config.toml").exists():
        return "config.toml is missing. Run `leadscout init`, then fill in the [sender] section with your details."
    with open(EXAMPLE, "rb") as f:
        example = tomllib.load(f)["sender"]
    left = [k for k in ("name", "business", "phone", "email", "portfolio") if cfg.sender.get(k) == example.get(k)]
    if left:
        return f"config.toml still has the example [sender] values for: {', '.join(left)}. Put your own details there first."
    return None
