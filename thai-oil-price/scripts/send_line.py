"""
Send a short daily oil-price report to everyone who has added the
LINE Official Account as a friend (LINE Messaging API "broadcast").

Reads data/latest.json, data/tomorrow.json and data/signal.json
(made by fetch_prices.py). Uses only the Python standard library.

Needs the environment variable LINE_TOKEN (a GitHub secret - never put
the token in this file). Optional SITE_URL adds a link to the website.

Test without sending:  python scripts/send_line.py --dry-run
"""

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

BKK = timezone(timedelta(hours=7))
DATA = Path(__file__).resolve().parent.parent / "data"
BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
BRAND = "Bangchak"  # the only source that announces tomorrow's price
BRANDS = [("PTT", "ปตท. (PTT)"), ("Bangchak", "บางจาก (Bangchak)")]

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
    morning = datetime.now(BKK).hour < 12
    title = "⛽ ราคาน้ำมันวันนี้ (รอบเช้า)" if morning else "⛽ ราคาน้ำมันวันนี้ (รอบเย็น)"
    lines = [title, thai_date(today, weekday=True)]
    found = False
    for brand, label in BRANDS:
        prices = [p for p in latest["prices"] if p["brand"] == brand]
        if not prices:
            continue
        found = True
        lines += ["", f"🔹 {label}"]
        for p in prices:
            lines.append(f"• {p['product']}: {p['price']:.2f} บาท")
    if not found:
        sys.exit("No prices in latest.json - nothing to send")

    # --- tomorrow (officially announced by Bangchak) ---
    # Bangchak announces changes in the evening, so the morning report skips this.
    tmr = load("tomorrow.json")
    expected = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    if not morning:
        lines.append("")
    if morning:
        pass
    elif tmr and tmr.get("for_date") == expected and tmr.get("items"):
        moved = [i for i in tmr["items"] if i.get("brand", BRAND) == BRAND and i["change"] != 0]
        lines.append(f"📅 พรุ่งนี้ ({thai_date(expected)}) ตามประกาศบางจาก")
        if moved:
            ups = sum(1 for i in moved if i["change"] > 0)
            lines.append("▲ ราคาขึ้น" if ups == len(moved) else
                         "▼ ราคาลง" if ups == 0 else "มีการปรับราคา")
            for i in moved:
                sign = "+" if i["change"] > 0 else ""
                lines.append(f"• {i['product']}: {i['today']:.2f} → {i['tomorrow']:.2f} "
                             f"({sign}{i['change']:.2f})")
        else:
            lines.append("ไม่มีการเปลี่ยนแปลงราคา")
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


# ---------- oil news (evening report only) ----------
def _tag_feed(site, tag):
    return f"https://www.{site}/tag/{urllib.parse.quote(tag)}/feed"


NEWS_FEEDS = [  # (source name, feed URL)
    ("ข่าวหุ้น", _tag_feed("kaohoon.com", "ราคาน้ำมัน")),
    ("ข่าวหุ้น", _tag_feed("kaohoon.com", "น้ำมัน")),
    ("ประชาชาติธุรกิจ", _tag_feed("prachachat.net", "น้ำมัน")),
    ("ประชาชาติธุรกิจ", _tag_feed("prachachat.net", "ราคาน้ำมัน")),
]
GOOGLE_NEWS = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote("ราคาน้ำมัน when:2d") + "&hl=th&gl=TH&ceid=TH:th")
NEWS_COUNT = 5
NEWS_DAYS = 3             # only news from the last few days
SKIP_DAILY = ("ราคาน้ำมันวันนี้", "เช็กราคาน้ำมัน", "อัปเดตราคาน้ำมัน")  # daily price posts


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (thai-oil-price)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def plain(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def opening_lines(desc_html, limit=200):
    first = re.search(r"<p>([\s\S]*?)</p>", desc_html or "")
    text = plain(first.group(1) if first else desc_html)
    text = re.sub(r"\s*(…|\.\.\.|\[…\])\s*$", "", text)
    if len(text) > limit:
        cut = text[:limit]
        text = (cut[:cut.rfind(" ")] if " " in cut[80:] else cut).rstrip() + "…"
    return text


def oil_news():
    """Up to NEWS_COUNT recent oil stories: (title, opening lines or "", source, link)."""
    cutoff = datetime.now(BKK) - timedelta(days=NEWS_DAYS)
    found, seen = [], set()

    def add(items, source, with_text):
        for it in items:
            title = plain(it.findtext("title"))
            link = (it.findtext("link") or "").strip()
            key = re.sub(r"\W", "", title)[:40]
            if not title or not link or key in seen or any(s in title for s in SKIP_DAILY):
                continue
            try:
                when = parsedate_to_datetime(it.findtext("pubDate"))
            except Exception:
                continue
            if when < cutoff:
                continue
            seen.add(key)
            text = opening_lines(it.findtext("description")) if with_text else ""
            found.append((when, title, text, source, link))

    for source, url in NEWS_FEEDS:
        try:
            add(ET.fromstring(http_get(url)).iter("item"), source, True)
        except Exception as e:
            print(f"skipped news feed {url}: {e}", file=sys.stderr)
    found.sort(key=lambda x: x[0], reverse=True)
    if len(found) < NEWS_COUNT:  # top up with Google News headlines (no opening lines)
        try:
            add(ET.fromstring(http_get(GOOGLE_NEWS)).iter("item"), "Google News", False)
        except Exception as e:
            print(f"skipped Google News: {e}", file=sys.stderr)
    return [f[1:] for f in found[:NEWS_COUNT]]


def news_message():
    items = oil_news()
    if not items:
        return None
    lines = ["🛢️ ข่าวน้ำมันล่าสุด"]
    for i, (title, text, source, link) in enumerate(items, 1):
        lines += ["", f"{i}. {title}"]
        if text:
            lines.append(f"📝 {text}")
        lines.append(f"({source}) {link}")
    return "\n".join(lines)


def broadcast(texts, token):
    body = json.dumps({"messages": [{"type": "text", "text": t[:4900]} for t in texts]}).encode("utf-8")
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
    texts = [build_message()]
    evening = datetime.now(BKK).hour >= 12 or "--evening" in sys.argv
    if evening:  # the evening report also gets a second bubble with oil news
        try:
            news = news_message()
        except Exception as e:  # never let the news stop the price report
            print(f"oil news skipped: {e}", file=sys.stderr)
            news = None
        if news:
            texts.append(news)
    for t in texts:
        print(t)
        print("-" * 30)
    if "--dry-run" in sys.argv:
        print("Dry run - nothing sent.")
        return
    token = os.environ.get("LINE_TOKEN", "").strip()
    if not token:
        sys.exit("LINE_TOKEN is not set - add it in GitHub: Settings -> Secrets and variables -> Actions")
    broadcast(texts, token)


if __name__ == "__main__":
    main()
