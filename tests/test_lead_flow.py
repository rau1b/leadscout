"""Contract C6: the statuses Show & close sets, and that Find & qualify's rescoring leaves them alone. Offline."""

import tomllib
from pathlib import Path

import pytest

from leadscout import db
from leadscout.scoring import score_all


@pytest.fixture
def cfg():
    from leadscout.config import Config

    with open(Path(__file__).resolve().parents[1] / "config.example.toml", "rb") as f:
        return Config(tomllib.load(f))


def test_meeting_and_proposal_are_statuses():
    assert {"meeting", "proposal"} <= set(db.STATUSES)
    assert len(db.STATUSES) == len(set(db.STATUSES))


@pytest.mark.parametrize("status", ["meeting", "proposal"])
def test_rescoring_keeps_a_meeting_or_proposal_lead(tmp_path, cfg, status):
    con = db.connect(tmp_path / "t.db")
    con.execute(
        """insert into businesses (id, source, name, category, phone, phone_type, fetched_at)
           values ('a', 't', 'Smile Dental', 'dentist', '+919812345678', 'mobile', '2026-11-20')"""
    )
    con.execute("insert into leads (business_id, score, status, updated_at) values ('a', 70, ?, '2026-11-20')", (status,))
    con.commit()
    score_all(con, cfg)
    assert con.execute("select status from leads where business_id = 'a'").fetchone()[0] == status
