"""Find & qualify's side of the contracts with Show & close (docs/CONTRACTS.md): C5 and C6. Offline."""

import json
import tomllib
from pathlib import Path

import pytest

from leadscout import config, db
from leadscout.compliance import is_opted_out, opt_out_business
from leadscout.mailer import sender
from leadscout.scoring import score_all


@pytest.fixture
def con(tmp_path):
    return db.connect(tmp_path / "t.db")


@pytest.fixture
def cfg():
    with open(Path(__file__).resolve().parents[1] / "config.example.toml", "rb") as f:
        return config.Config(tomllib.load(f))


def _lead(con, bid="b1", status="contacted", email="owner@clinic.in", phone="+919812345678"):
    con.execute("insert into businesses (id, source, name, category, phone, phone_type, fetched_at) values (?, 't', 'Smile Dental', 'dentist', ?, 'mobile', '2026-11-20')",
                (bid, phone))
    con.execute("insert into audits (business_id, site_class, audited_at) values (?, 'none', '2026-11-20')", (bid,))
    con.execute("insert into leads (business_id, score, status, email, updated_at) values (?, 80, ?, ?, '2026-11-20')", (bid, status, email))
    con.execute("insert into outreach (business_id, channel, kind, to_addr, gmail_id, thread_id, sent_at) values (?, 'email', 'first', ?, 'g1', 't1', '2026-11-20T10:00:00+05:30')",
                (bid, email))
    con.commit()


def _status(con, bid="b1"):
    return con.execute("select status from leads where business_id = ?", (bid,)).fetchone()[0]


# ---- C5: opt_out_business ------------------------------------------------------------------

def test_opt_out_business_suppresses_email_and_phone_and_logs_without_contact_details(con):
    _lead(con)
    assert opt_out_business(con, "b1", "unsubscribe link", actor="preview-host")
    assert _status(con) == "opted_out"
    assert is_opted_out(con, "owner@clinic.in") and is_opted_out(con, "+91 98123 45678")
    [e] = con.execute("select type, business_id, actor, data_json from events").fetchall()
    assert (e["type"], e["business_id"], e["actor"]) == ("opted_out", "b1", "preview-host")
    assert json.loads(e["data_json"]) == {"reason": "unsubscribe link"}
    assert "clinic" not in e["data_json"] and "9812345678" not in e["data_json"]


def test_opt_out_business_never_changes_a_won_lead(con):
    _lead(con, status="won")
    _lead(con, bid="b2", status="won")  # a twin listing with the same email and phone
    assert opt_out_business(con, "b1", "unsubscribe link")
    assert _status(con) == "won" and _status(con, "b2") == "won"
    assert is_opted_out(con, "owner@clinic.in")  # still never emailed again


def test_opt_out_business_without_contact_details_or_business(con):
    _lead(con, email=None, phone=None)
    assert opt_out_business(con, "b1", "unsubscribe link") and _status(con) == "opted_out"
    assert not opt_out_business(con, "nobody", "unsubscribe link")


# ---- C6: reply checking covers meeting and proposal leads -----------------------------------

class Gmail:
    def __init__(self, kind):
        self.kind = kind

    def incoming(self, thread_id, me):
        return [{"id": "m1", "from": "owner@clinic.in", "subject": "Re", "body": "...", "received_ms": 1795000000000, "kind": self.kind}]

    def unsubscribe_requests(self, me, since=None):
        return set()


@pytest.mark.parametrize("status", ["meeting", "proposal"])
def test_replies_from_meeting_and_proposal_leads_are_saved_and_keep_the_status(con, cfg, status):
    _lead(con, status=status)
    assert sender.check_replies(con, cfg, Gmail("replied"))["replied"] == 1
    assert _status(con) == status
    assert con.execute("select count(*) from replies").fetchone()[0] == 1


@pytest.mark.parametrize("status", ["meeting", "proposal"])
@pytest.mark.parametrize("kind", ["opted_out", "bounced"])
def test_only_a_no_or_a_bounce_moves_a_meeting_or_proposal_lead(con, cfg, status, kind):
    _lead(con, status=status)
    sender.check_replies(con, cfg, Gmail(kind))
    assert _status(con) == kind


@pytest.mark.parametrize("status,kind", [("won", "opted_out"), ("won", "bounced"), ("won", "replied"), ("lost", "opted_out")])
def test_won_and_lost_leads_keep_their_status(con, cfg, status, kind):
    _lead(con, status=status)
    sender.check_replies(con, cfg, Gmail(kind))
    assert _status(con) == status


@pytest.mark.parametrize("status", ["meeting", "proposal"])
def test_rescoring_keeps_a_meeting_lead_ahead_of_its_twin_and_keeps_its_email(con, cfg, status, monkeypatch):
    from leadscout import emailcheck

    monkeypatch.setattr(emailcheck, "is_deliverable", lambda email: False)  # DNS would now reject the address
    _lead(con, status=status)
    _lead(con, bid="b2", status="new")  # the same business listed twice
    score_all(con, cfg)
    assert _status(con) == status and _status(con, "b2") == "excluded"
    assert con.execute("select email from leads where business_id = 'b1'").fetchone()[0] == "owner@clinic.in"
