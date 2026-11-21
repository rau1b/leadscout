"""Desktop launcher: start the dashboard in the background (no console window) and open it in the browser.

The desktop shortcut runs `pythonw -m leadscout.launch`. Make or remake the shortcut with `leadscout shortcut`.
"""

import os
import struct
import subprocess
import sys
import time
import urllib.request
import webbrowser
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 8000
URL = f"http://127.0.0.1:{PORT}/"
PID_FILE = ROOT / "data" / "dashboard.pid"


def running() -> bool:
    try:
        with urllib.request.urlopen(URL + "find", timeout=2) as r:
            return r.status == 200 and b"LeadScout" in r.read(4000)
    except OSError:
        return False


def start_server() -> None:
    (ROOT / "data").mkdir(exist_ok=True)
    log = open(ROOT / "data" / "dashboard.log", "ab")
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [str(pythonw), "-m", "uvicorn", "leadscout.web.app:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags,
        env={**os.environ, "LEADSCOUT_HOME": str(ROOT)},
    )
    PID_FILE.write_text(str(proc.pid))


def message(text: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "LeadScout", 0x10)
    else:
        print(text)


def main() -> None:
    if not running():
        start_server()
        for _ in range(40):
            time.sleep(0.5)
            if running():
                break
        else:
            message(f"The dashboard didn't start. Details are in:\n{ROOT / 'data' / 'dashboard.log'}")
            return
    webbrowser.open(URL)


def stop() -> bool:
    if not PID_FILE.exists():
        return False
    pid = PID_FILE.read_text().strip()
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    else:
        os.kill(int(pid), 15)
    PID_FILE.unlink(missing_ok=True)
    return True


# ---- Icon and shortcut -----------------------------------------------------------------------

# Bordeaux #531B24 square, sand #C6B7A2 stitch, porcelain #F3ECE2 letter: the dashboard's sidebar in miniature.
ICON_COLOURS = ((83, 27, 36, 255), (198, 183, 162, 255), (243, 236, 226, 255))


def _png(size: int) -> bytes:
    """The sidebar in miniature: bordeaux, a dashed sand stitch, an L. Drawn by hand, no image library."""
    red, yellow, white = ICON_COLOURS
    clear = (0, 0, 0, 0)
    s = size / 64
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            px, py = x / s, y / s
            # rounded square
            r = 12
            cx = min(max(px, r), 64 - r)
            cy = min(max(py, r), 64 - r)
            inside = (px - cx) ** 2 + (py - cy) ** 2 <= r * r
            c = clear
            if inside:
                c = red
                if 50 <= px <= 53 and int(py / 6) % 2 == 0 and 6 < py < 58:
                    c = yellow  # dashed stitch
                if (16 <= px <= 25 and 14 <= py <= 50) or (16 <= px <= 42 and 41 <= py <= 50):
                    c = white  # L
            row += bytes(c)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def write_icon(path: Path) -> None:
    images = [(n, _png(n)) for n in (16, 32, 48, 256)]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for n, data in images:
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    path.write_bytes(header + entries + blobs)


def make_shortcut() -> Path:
    (ROOT / "data").mkdir(exist_ok=True)
    icon = ROOT / "data" / "leadscout-bordeaux.ico"
    write_icon(icon)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = (
        "$d = [Environment]::GetFolderPath('Desktop'); "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'LeadScout.lnk')); "
        f"$s.TargetPath = '{pythonw}'; $s.Arguments = '-m leadscout.launch'; "
        f"$s.WorkingDirectory = '{ROOT}'; $s.IconLocation = '{icon}'; "
        "$s.Description = 'Open the LeadScout dashboard'; $s.WindowStyle = 7; $s.Save(); "
        "Write-Output (Join-Path $d 'LeadScout.lnk')"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


if __name__ == "__main__":
    main()
