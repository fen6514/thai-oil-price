"""
Send a short daily oil-price report to everyone who has added the
LINE Official Account as a friend (LINE Messaging API "broadcast").

Reads data/latest.json, data/tomorrow.json and data/signal.json
(made by fetch_prices.py). Uses only the Python standard library.

Needs the environment variable LINE_TOKEN (a GitHub secret - never put
the token in this file). Optional SITE_URL adds a link to the website.

Test without sending:  python scripts/send_line.py --dry-run
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BKK = timezone(timedelta(hours=7))
DATA = Path(__file__).resolve().parent.parent / "data"
BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
BRAND = "Bangchak"

TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
             "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
TH_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


def load(name):
    path = DATA / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def thai_date(iso, weekday=False):
    d = datetime.strptime(iso, "%Y-%m-%d")
    text = f"{d.day} {TH_MONTHS[d.month - 1]} {d.year + 543}"
    return f"วัน{TH_DAYS[d.weekday()]}ที่ {text}" if weekday else text


def build_message():
    latest = load("latest.json")
    if not latest:
        sys.exit("latest.json not found - run fetch_prices.py first")
    today = latest["date"]
    prices = [p for p in latest["prices"] if p["brand"] == BRAND]
    if not prices:
        sys.exit(f"No {BRAND} prices in latest.json - nothing to send")

    lines = [f"⛽ ราคาน้ำมัน{BRAND} วันนี้", thai_date(today, weekday=True), ""]
    for p in prices:
        lines.append(f"• {p['product']}: {p['price']:.2f} บาท")

    # --- tomorrow (officially announced by Bangchak) ---
    tmr = load("tomorrow.json")
    expected = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    lines.append("")
    if tmr and tmr.get("for_date") == expected and tmr.get("items"):
        moved = [i for i in tmr["items"] if i.get("brand", BRAND) == BRAND and i["change"] != 0]
        lines.append(f"📅 พรุ่งนี้ ({thai_date(expected)})")
        if moved:
            ups = sum(1 for i in moved if i["change"] > 0)
            lines.append("▲ ราคาขึ้น" if ups == len(moved) else
                         "▼ ราคาลง" if ups == 0 else "มีการปรับราคา")
            for i in moved:
                sign = "+" if i["change"] > 0 else ""
                lines.append(f"• {i['product']}: {i['today']:.2f} → {i['tomorrow']:.2f} "
                             f"({sign}{i['change']:.2f})")
        else:
            lines.append("ไม่มีการเปลี่ยนแปลงราคา (ตามที่บางจากประกาศ)")
    else:
        lines.append("📅 พรุ่งนี้: ยังไม่มีประกาศราคา")

    # --- trend outlook from world crude ---
    sig = load("signal.json")
    if sig and sig.get("direction") in ("up", "down", "flat"):
        label = {"up": "▲ มีแนวโน้มขึ้น", "down": "▼ มีแนวโน้มลง",
                 "flat": "● น่าจะทรงตัว"}[sig["direction"]]
        pct = sig["change_pct"]
        lines += ["",
                  f"📈 แนวโน้มอีกไม่กี่วัน: {label}",
                  f"น้ำมันดิบเบรนท์ (คิดเป็นบาท) {'+' if pct > 0 else ''}{pct:.1f}% ใน 5 วันทำการ",
                  "(เป็นการคาดการณ์คร่าวๆ ไม่ใช่การยืนยัน)"]

    site = os.environ.get("SITE_URL", "").strip()
    if site:
        lines += ["", f"ดูราคาทุกยี่ห้อและกราฟย้อนหลัง: {site}"]

    return "\n".join(lines)


def broadcast(text, token):
    body = json.dumps({"messages": [{"type": "text", "text": text[:4900]}]}).encode("utf-8")
    req = urllib.request.Request(
        BROADCAST_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"LINE broadcast sent (HTTP {r.status})")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        hint = {401: "token is wrong or expired - re-issue it and update the LINE_TOKEN secret",
                429: "monthly free message quota used up (or too many requests)"}.get(e.code, "")
        sys.exit(f"LINE broadcast FAILED: HTTP {e.code} {detail} {hint}")


def main():
    text = build_message()
    print(text)
    print("-" * 30)
    if "--dry-run" in sys.argv:
        print("Dry run - nothing sent.")
        return
    token = os.environ.get("LINE_TOKEN", "").strip()
    if not token:
        sys.exit("LINE_TOKEN is not set - add it in GitHub: Settings -> Secrets and variables -> Actions")
    broadcast(text, token)


if __name__ == "__main__":
    main()
