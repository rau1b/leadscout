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
            os.environ.setdefault(k.strip(), v.strip())


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


def load() -> Config:
    _load_env()
    path = home() / "config.toml"
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / "config.example.toml"
    with open(path, "rb") as f:
        return Config(tomllib.load(f))
