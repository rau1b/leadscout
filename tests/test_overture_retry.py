"""Overture downloads retry a dropped connection instead of failing the whole search. No network."""

import pytest

from leadscout.sources import overture


class _Reader:
    def read_all(self):
        return "table"


def _flaky(fails: int):
    calls = {"n": 0}

    def reader(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] <= fails:
            raise OSError("AWS Error NETWORK_CONNECTION during GetObject operation")
        return _Reader()

    return reader, calls


def test_retries_after_a_dropped_connection(monkeypatch):
    reader, calls = _flaky(2)
    monkeypatch.setattr(overture.core, "record_batch_reader", reader)
    waited = []
    assert overture.download((0, 0, 1, 1), waits=(1, 2, 3), sleep=waited.append) == "table"
    assert calls["n"] == 3
    assert waited == [1, 2]


def test_gives_up_after_the_last_retry(monkeypatch):
    reader, calls = _flaky(99)
    monkeypatch.setattr(overture.core, "record_batch_reader", reader)
    with pytest.raises(OSError):
        overture.download((0, 0, 1, 1), waits=(1, 2), sleep=lambda _s: None)
    assert calls["n"] == 3


def test_no_data_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def none_reader(*_a, **_kw):
        calls["n"] += 1

    monkeypatch.setattr(overture.core, "record_batch_reader", none_reader)
    with pytest.raises(RuntimeError):
        overture.download((0, 0, 1, 1), waits=(1,), sleep=lambda _s: None)
    assert calls["n"] == 1
