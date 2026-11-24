"""Sending from the dashboard: the same `sender.run` as `leadscout send`, in a background thread you can stop.

All the limits live in `sender.run` (warm-up cap, IST window, bounce pause, suppression list), so they apply here too.
Each email is claimed before it goes out, so this and a `leadscout send` running at the same time can't double-send.
"""

import threading
from collections import deque
from datetime import datetime

from leadscout import config, db
from leadscout.config import IST
from leadscout.mailer import sender

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
    try:
        sender.run(con, config.load(), gmail, log=_say, stop=_stop)
    except Exception as e:  # shown on the page, rather than lost in a thread
        _say(f"Stopped on an error: {e}")
    finally:
        con.close()
