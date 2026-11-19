#!/usr/bin/env python3
"""Watch the Batch 1 seat count on goakal.com and alert via ntfy.

Runs are stateless apart from state.json, which is committed back to the repo.
Env:
  NTFY_TOPIC   required. topic name on ntfy.sh (acts as the secret)
  NTFY_SERVER  optional. default https://ntfy.sh
  DIGEST_HOUR  optional. local hour (Asia/Jakarta) for the daily digest, default 8
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Jakarta")
except Exception:  # no tzdata available
    TZ = timezone(timedelta(hours=7))

PAGE = "https://goakal.com/brobri/program-suami-qawwam"
STATE_PATH = Path(__file__).resolve().with_name("state.json")
DRY_RUN = "--dry-run" in sys.argv
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR") or "8")
HEARTBEAT_DAYS = 30
ERROR_ALERT_HOURS = 6
UA = "akal-seat-monitor/1.0 (+https://github.com)"


def now_local():
    return datetime.now(TZ)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def parse_iso(value):
    return datetime.fromisoformat(value)


def fetch_html():
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                PAGE, headers={"User-Agent": UA, "Accept": "text/html"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError(f"fetch failed: {last}")


def parse_batch1(html):
    """Return Batch 1 seats from the embedded RSC payload, badge text as fallback."""
    if "kursi tersisa" not in html:
        raise ValueError("page has no 'kursi tersisa' text (layout changed?)")

    txt = html.replace('\\"', '"')
    match = re.search(
        r'"title":"(Batch\s*1\b[^"]*)".{0,900}?"quotaMax":(\d+),"quotaUsed":(\d+)',
        txt,
        re.S,
    )
    if match and match.group(0).count('"title":"Batch') == 1:
        qmax, qused = int(match.group(2)), int(match.group(3))
        if qused > qmax:
            raise ValueError(f"invalid quota used={qused} max={qmax}")
        return {
            "seats": qmax - qused,
            "max": qmax,
            "used": qused,
            "title": match.group(1),
            "source": "json",
        }

    badge = re.search(r">\s*(\d+)\s*<!-- -->\s*kursi tersisa", html)
    if badge:
        return {
            "seats": int(badge.group(1)),
            "max": None,
            "used": None,
            "title": "Batch 1",
            "source": "badge",
        }
    raise ValueError("Batch 1 seat count not found in page")


def ntfy(title, body, priority=3, tags=""):
    if DRY_RUN:
        print(f"[dry-run] {title}\n{body}\n")
        return True

    topic = (os.environ.get("NTFY_TOPIC") or "").strip()
    if not topic:
        print("ERROR: NTFY_TOPIC is not set", file=sys.stderr)
        return False

    server = (os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(
        f"{server}/{topic}", data=body.encode("utf-8"), method="POST"
    )
    req.add_header("Title", title.encode("ascii", "replace").decode("ascii"))
    req.add_header("Priority", str(priority))
    req.add_header("Click", PAGE)
    if tags:
        req.add_header("Tags", tags)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                print(f"ntfy returned HTTP {resp.status}", file=sys.stderr)
            return ok
    except urllib.error.HTTPError as exc:
        print(f"ntfy HTTP {exc.code}: {exc.read()[:200]!r}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"ntfy failed: {exc}", file=sys.stderr)
    return False


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            print(f"state.json unreadable, starting fresh: {exc}", file=sys.stderr)
    return {}


def save_state(state):
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(STATE_PATH)


def handle_error(state, now, exc):
    state["lastError"] = str(exc)
    last = state.get("lastErrorAlertAt")
    due = True
    if last:
        due = now - parse_iso(last) > timedelta(hours=ERROR_ALERT_HOURS)
    if due:
        ntfy(
            "Akal monitor error",
            f"Batch 1 check failed at {now:%Y-%m-%d %H:%M} WIB\n\n{exc}\n\n{PAGE}",
            priority=5,
            tags="rotating_light",
        )
        state["lastErrorAlertAt"] = iso(now)
    else:
        print(f"error alert suppressed (last sent {last})", file=sys.stderr)
    save_state(state)


def main():
    now = now_local()
    today = now.date().isoformat()
    state = load_state()

    try:
        parsed = parse_batch1(fetch_html())
    except Exception as exc:  # noqa: BLE001
        handle_error(state, now, exc)
        return 1

    seats, qmax, qused = parsed["seats"], parsed["max"], parsed["used"]
    stamp = f"{now:%Y-%m-%d %H:%M} WIB"
    previous = state.get("seats")

    if previous is None:
        ntfy(
            f"Monitor aktif: {seats} kursi tersisa",
            f"Batch 1 sekarang: {seats} kursi tersisa\n"
            f"Kuota: {qused}/{qmax} terpakai\n"
            f"Dicek: {stamp}\n\n{PAGE}",
            priority=2,
            tags="white_check_mark",
        )
        state["seats"] = seats
        state["updatedAt"] = iso(now)
    elif seats != previous:
        delta = seats - previous
        ntfy(
            f"Akal Batch 1: {previous} -> {seats}",
            f"Kursi tersisa: {seats} (sebelumnya {previous}, {'+' if delta > 0 else ''}{delta})\n"
            f"Kuota: {qused}/{qmax} terpakai\n"
            f"Waktu: {stamp}\n\n{PAGE}",
            priority=4,
            tags="warning",
        )
        state["seats"] = seats
        state["updatedAt"] = iso(now)
        state["previousSeats"] = previous
    else:
        print(f"no change: {seats} kursi tersisa")

    if qmax is not None:
        state["quotaMax"] = qmax
        state["quotaUsed"] = qused
    state["title"] = parsed["title"]
    state["source"] = parsed["source"]

    if now.hour >= DIGEST_HOUR and state.get("lastDigestDate") != today:
        yesterday = state.get("prevDaySeats")
        if yesterday is None:
            state["prevDaySeats"] = seats
            state["prevDayDate"] = today
            state["lastDigestDate"] = today
        else:
            delta = seats - yesterday
            if delta == 0:
                summary = (
                    f"Hari ini: {seats} kursi tersisa\n"
                    f"Kemarin: {yesterday}\nTidak ada perubahan."
                )
            else:
                summary = (
                    f"Hari ini: {seats} kursi tersisa\n"
                    f"Kemarin: {yesterday}\n"
                    f"Perubahan: {'+' if delta > 0 else ''}{delta}"
                )
            ntfy(
                f"Akal harian: {seats} kursi tersisa",
                f"{summary}\nDicek: {stamp}\n\n{PAGE}",
                priority=4 if delta else 3,
                tags="calendar",
            )
            state["prevDaySeats"] = seats
            state["prevDayDate"] = today
            state["lastDigestDate"] = today

    heartbeat = state.get("lastHeartbeat")
    if not heartbeat or now - parse_iso(heartbeat) > timedelta(days=HEARTBEAT_DAYS):
        state["lastHeartbeat"] = iso(now)

    if state.get("lastError"):
        state.pop("lastError", None)

    save_state(state)
    print(f"batch 1 = {seats} seats (used {qused}/{qmax}) via {parsed['source']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"fatal: {exc}", file=sys.stderr)
        sys.exit(1)
