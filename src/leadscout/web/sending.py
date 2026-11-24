"""Sending from the dashboard: the same `sender.run` as `leadscout send`, in a background thread you can stop.

All the limits live in `sender.run` (warm-up cap, IST window, bounce pause, suppression list), so they apply here too.
Each email is claimed before it goes out, so this and a `leadscout send` running at the same time can't double-send.
"""

import threading
from collections import deque
from datetime import datetime

from leadscout import config, db
from leadscout.compliance import in_window
from leadscout.config import IST
from leadscout.mailer import sender

RUNNING_KEY = "dashboard_send_running"  # set while a dashboard run is going; left behind if the dashboard was closed mid-run

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
log: deque[str] = deque(maxlen=8)  # newest last; shown on the Today page


def _say(line: str) -> None:
    log.append(f"{datetime.now(IST):%H:%M} {line}")


def running() -> bool:
    return _thread is not None and _thread.is_alive()


def stopping() -> bool:
    return running() and _stop.is_set()


def block_reason(con, cfg) -> str:
    """Why sending can't start right now, in plain words; empty if it can."""
    sc = cfg.sending
    if not in_window(sc):
        return f"The sending window is closed. It opens at {sc['window_start']} IST on sending days."
    if sender.bounce_rate(con) > sc["max_bounce_rate"]:
        return "Paused: too many recent emails bounced. Check your lead emails before sending more."
    if sender.sent_today(con) >= sender.daily_cap(con, cfg):
        return "Today's cap is reached. Sending picks up tomorrow."
    if sender.next_item(con, cfg) is None:
        return "Nothing to send. Approve some pitches first."
    return ""


def note_cut_off_run(con) -> None:
    """On dashboard start: if the last run was still going when the dashboard closed, say so on the Today page."""
    started = db.get_meta(con, RUNNING_KEY)
    if started:
        _say(f"The run started at {started[11:16]} ended when the dashboard closed. Start it again if you want to keep sending.")
        con.execute("delete from meta where key = ?", (RUNNING_KEY,))
        con.commit()


def start(gmail) -> bool:
    """Start sending with this logged-in Gmail client. False if it's already running."""
    global _thread
    with _lock:
        if running():
            return False
        _stop.clear()
        _say("Started sending.")
        _thread = threading.Thread(target=_work, args=(gmail,), daemon=True, name="leadscout-send")
        _thread.start()
        return True


def stop() -> None:
    """Ask the run to end. It finishes the email in hand (if any) and stops before the next one."""
    if running():
        _stop.set()


def _work(gmail) -> None:
    con = db.connect()
    db.set_meta(con, RUNNING_KEY, db.now())
    try:
        sender.run(con, config.load(), gmail, log=_say, stop=_stop)
    except Exception as e:  # shown on the page, rather than lost in a thread
        _say(f"Stopped on an error: {e}")
    finally:
        con.execute("delete from meta where key = ?", (RUNNING_KEY,))
        con.commit()
        con.close()
