import json
import tomllib

import pytest

from leadscout import config, db, settings

MINE = """
[sender]
name = "Asha Rao"
business = "Rao Web Studio"
city = "Pune"
phone = "+91 98765 43210"
email = "asha.outreach@gmail.com"
portfolio = "https://asha.example"

[pitch]
offer = "a free mockup of your new homepage"
pitch_line = "I build fast websites"

[sending]
window_start = "10:00"
window_end = "17:00"
days = ["Mon", "Tue", "Wed"]
skip_dates = ["2026-12-25"]
whatsapp_daily_cap = 20
min_gap_seconds = 180
max_gap_seconds = 360
warmup = [15, 30, 50]
followup_after_days = 4
max_followups = 1
max_bounce_rate = 0.05
lease_note = "a key the form doesn't show"

[scoring]
min_score = 40
high_value = ["dentist", "clinic"]
excluded = ["bank"]

[retention]
purge_uncontacted_after_days = 90

[backups]
keep_days = 14

[extras]
future_flag = true
"""


@pytest.fixture
def web(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from leadscout.web.app import app

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(MINE, encoding="utf-8")
    return TestClient(app, base_url="http://127.0.0.1:8000"), tmp_path


def _form(**changes) -> dict:
    v = settings.form_values(tomllib.loads(MINE))
    return {**v, **changes}


def test_settings_page_renders(web, monkeypatch):
    client, _ = web
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    page = client.get("/settings").text
    assert 'aria-current="page">Settings' in page
    assert 'value="asha.outreach@gmail.com"' in page and 'value="Mon" checked' in page and 'value="Sat" >' in page
    assert "Not set." in page
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-secret-value")
    page = client.get("/settings").text
    assert "Set</b>" in page and "AIza-secret-value" not in page  # only whether it's set, never the key


def test_valid_save_writes_file_keeps_unknown_keys_backs_up_and_logs(web):
    client, home = web
    r = client.post("/settings", data=_form(**{"sending.window_end": "18:30", "sending.days": ["Mon", "Sat"], "sender.city": "Mumbai"}),
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings?saved=3"

    saved = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert saved["sending"]["window_end"] == "18:30" and saved["sending"]["days"] == ["Mon", "Sat"] and saved["sender"]["city"] == "Mumbai"
    assert saved["sending"]["lease_note"] == "a key the form doesn't show" and saved["extras"] == {"future_flag": True}
    assert saved["sending"]["warmup"] == [15, 30, 50] and saved["sending"]["max_bounce_rate"] == 0.05  # types kept

    [backup] = (home / "data" / "backups").glob("config-*.toml")
    assert backup.read_text(encoding="utf-8") == MINE
    assert not list(home.glob("*.tmp"))

    con = db.connect()
    [event] = con.execute("select type, actor, data_json from events").fetchall()
    assert (event["type"], event["actor"]) == ("settings_changed", "dashboard")
    assert json.loads(event["data_json"]) == {"keys": ["sender.city", "sending.days", "sending.window_end"]}
    assert "Mumbai" not in event["data_json"]  # names of what changed, never the values
    assert "Saved. 3 settings changed" in client.get("/settings?saved=3").text


def test_new_values_apply_without_a_restart(web):
    client, _ = web
    client.post("/settings", data=_form(**{"sending.window_start": "09:15"}))
    assert config.load().sending["window_start"] == "09:15"
    assert 'value="09:15"' in client.get("/settings").text


@pytest.mark.parametrize("changes,field", [
    ({"sending.window_start": "9am"}, "sending.window_start"),
    ({"sending.window_start": "18:00", "sending.window_end": "17:00"}, "sending.window_end"),
    ({"sending.days": []}, "sending.days"),
    ({"sending.days": ["Mon", "Funday"]}, "sending.days"),
    ({"sending.skip_dates": "2026-12-25\n25/12/2026"}, "sending.skip_dates"),
    ({"sending.skip_dates": "2027-02-30"}, "sending.skip_dates"),
    ({"sending.whatsapp_daily_cap": "0"}, "sending.whatsapp_daily_cap"),
    ({"sending.warmup.1": "-5"}, "sending.warmup.1"),
    ({"sending.max_bounce_rate": "100"}, "sending.max_bounce_rate"),
    ({"sending.max_bounce_rate": "0"}, "sending.max_bounce_rate"),
    ({"sending.max_followups": "3"}, "sending.max_followups"),
    ({"sending.min_gap_seconds": "400", "sending.max_gap_seconds": "300"}, "sending.max_gap_seconds"),
    ({"backups.keep_days": "0"}, "backups.keep_days"),
    ({"scoring.min_score": "lots"}, "scoring.min_score"),
    ({"sender.email": "asha at gmail"}, "sender.email"),
    ({"sender.phone": "12345"}, "sender.phone"),
    ({"sender.name": "  "}, "sender.name"),
])
def test_invalid_input_shows_the_error_and_saves_nothing(web, changes, field):
    client, home = web
    r = client.post("/settings", data=_form(**changes))
    assert r.status_code == 400
    assert f'id="{field}-err"' in r.text and "Nothing was saved." in r.text
    assert (home / "config.toml").read_text(encoding="utf-8") == MINE
    assert not (home / "data" / "backups").exists()


def test_saving_example_sender_values_shows_the_usual_warning(web):
    client, _ = web
    example = tomllib.loads(config.EXAMPLE.read_text(encoding="utf-8"))["sender"]
    page = client.post("/settings", data=_form(**{f"sender.{k}": v for k, v in example.items()})).text
    assert config.sender_problem(config.load()) in page.replace("&#39;", "'").replace("&#34;", '"')


def test_cross_site_post_is_blocked(web):
    client, home = web
    r = client.post("/settings", data=_form(**{"sender.city": "Elsewhere"}), headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert (home / "config.toml").read_text(encoding="utf-8") == MINE


def test_config_backups_are_pruned_with_the_database_ones(tmp_path):
    from leadscout import backups

    d = tmp_path / "backups"
    d.mkdir()
    (d / "config-20200101-000000.toml").write_text("old")
    (d / "config-99990101-000000.toml").write_text("new")
    assert backups.prune(d, 14) == ["config-20200101-000000.toml"]
