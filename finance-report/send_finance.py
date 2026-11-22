"""
Daily finance report for the "Thai Finance Daily" LINE Official Account.

Collects:
  - Thai gold prices (Gold Traders Association, goldtraders.or.th) + world gold
  - Exchange rates (baht per USD/EUR/GBP/100 JPY/CNY) + SET index (Yahoo Finance)
  - Finance news and economic news headlines (Google News RSS, Thai)
and BROADCASTS them to every friend of the LINE account.

Uses only the Python standard library.
Needs the environment variable FINANCE_LINE_TOKEN (a GitHub secret - never
put the token in this file).

Test without sending:  python finance-report/send_finance.py --dry-run
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

BKK = timezone(timedelta(hours=7))
UA = "Mozilla/5.0 (thai-finance-daily)"
BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
NEWS_PER_SECTION = 5

TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
             "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
TH_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]

FX = [  # (Yahoo symbol, label, multiplier)
    ("THB=X", "USD", 1),
    ("EURTHB=X", "EUR", 1),
    ("GBPTHB=X", "GBP", 1),
    ("JPYTHB=X", "JPY (100 เยน)", 100),
    ("CNYTHB=X", "CNY", 1),
]

FINANCE_NEWS = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=th&gl=TH&ceid=TH:th"
ECONOMY_NEWS = ("https://news.google.com/rss/search?q="
                + urllib.parse.quote("เศรษฐกิจ when:1d -site:facebook.com") + "&hl=th&gl=TH&ceid=TH:th")
MAX_TITLE = 140  # characters; longer headlines are cut with "…"


def http(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def num(text):
    return float(text.replace(",", ""))


def arrow(change, digits=2):
    if change is None:
        return ""
    if abs(change) < 10 ** -digits / 2:
        return " (คงที่)"
    return f" ({'▲ +' if change > 0 else '▼ '}{change:,.{digits}f})"


# ---------- gold ----------
def thai_gold():
    """Gold Traders Association prices, baht per baht-weight (96.5%)."""
    page = http("https://www.goldtraders.or.th/")
    found = re.findall(r'font-bold">(รับซื้อ|ขายออก|ฐานภาษี)</span><span[^>]*>([\d,]+\.?\d*)</span>', page)
    if len(found) < 4:
        raise ValueError("gold prices not found on page (site layout may have changed)")
    (_, bar_buy), (_, bar_sell), _, (_, orn_sell) = found[:4]
    when = re.search(r"ประจำวันที่\s*([^<]+?)\s*</", page)
    return {"bar_buy": num(bar_buy), "bar_sell": num(bar_sell), "orn_sell": num(orn_sell),
            "when": html.unescape(when.group(1)) if when else ""}


def yahoo(symbol):
    """(latest, previous) daily close from Yahoo Finance; previous may be None."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1mo&interval=1d"
    res = json.loads(http(url))["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    if not closes:
        price = res["meta"].get("regularMarketPrice")
        if price is None:
            raise ValueError(f"no data for {symbol}")
        return price, None
    return closes[-1], (closes[-2] if len(closes) > 1 else None)


def safe(fn, *args):
    try:
        return fn(*args)
    except Exception as e:  # one broken source must not stop the whole report
        print(f"skipped {fn.__name__}{args}: {e}", file=sys.stderr)
        return None


# ---------- news ----------
def news(url, n):
    root = ET.fromstring(http(url))
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if title.endswith("- Facebook"):
            continue
        if len(title) > MAX_TITLE:
            title = title[:MAX_TITLE].rstrip() + "…"
        if title and link:
            items.append((title, link))
        if len(items) >= n:
            break
    return items


# ---------- message ----------
def thai_today():
    d = datetime.now(BKK)
    return f"วัน{TH_DAYS[d.weekday()]}ที่ {d.day} {TH_MONTHS[d.month - 1]} {d.year + 543}"


def markets_text():
    lines = ["💰 สรุปการเงินประจำวัน", thai_today()]

    gold = safe(thai_gold)
    world = safe(yahoo, "GC=F")
    lines += ["", "🥇 ราคาทอง (สมาคมค้าทองคำ, บาทละ)"]
    if gold:
        lines += [f"ทองคำแท่ง  รับซื้อ {gold['bar_buy']:,.0f} | ขายออก {gold['bar_sell']:,.0f}",
                  f"ทองรูปพรรณ ขายออก {gold['orn_sell']:,.0f}"]
        if gold["when"]:
            lines.append(f"ประกาศ {gold['when']}")
    else:
        lines.append("ดึงราคาทองไทยไม่ได้วันนี้")
    if world:
        last, prev = world
        lines.append(f"ทองโลก {last:,.2f} $/ออนซ์{arrow(last - prev if prev else None)}")

    lines += ["", "💱 อัตราแลกเปลี่ยน (บาท)"]
    for symbol, label, mult in FX:
        q = safe(yahoo, symbol)
        if q:
            last, prev = q[0] * mult, (q[1] * mult if q[1] else None)
            lines.append(f"• {label}: {last:,.2f}{arrow(last - prev if prev else None)}")

    s = safe(yahoo, "^SET.BK")
    if s:
        last, prev = s
        lines += ["", f"📊 SET Index: {last:,.2f}{arrow(last - prev if prev else None)}"]

    lines += ["", "(ราคาอ้างอิง ณ เวลาที่ส่ง อาจต่างจากราคาหน้าร้าน/ธนาคาร)"]
    return "\n".join(lines)


def news_text(title, url, seen):
    items = safe(news, url, NEWS_PER_SECTION * 2) or []
    picked = []
    for t, link in items:
        if t not in seen:
            seen.add(t)
            picked.append((t, link))
        if len(picked) >= NEWS_PER_SECTION:
            break
    if not picked:
        return None
    lines = [title]
    for i, (t, link) in enumerate(picked, 1):
        lines += ["", f"{i}. {t}", link]
    return "\n".join(lines)


def build_messages():
    seen = set()
    texts = [markets_text(),
             news_text("📰 ข่าวการเงิน / ธุรกิจ", FINANCE_NEWS, seen),
             news_text("🏛️ ข่าวเศรษฐกิจ", ECONOMY_NEWS, seen)]
    return [t[:4900] for t in texts if t]


def broadcast(texts, token):
    body = json.dumps({"messages": [{"type": "text", "text": t} for t in texts]}).encode("utf-8")
    req = urllib.request.Request(
        BROADCAST_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"LINE broadcast sent (HTTP {r.status})")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        hint = {401: "token is wrong or expired - re-issue it and update the FINANCE_LINE_TOKEN secret",
                429: "monthly free message quota used up (or too many requests)"}.get(e.code, "")
        sys.exit(f"LINE broadcast FAILED: HTTP {e.code} {detail} {hint}")


def main():
    texts = build_messages()
    for t in texts:
        print(t)
        print("-" * 30)
    if "--dry-run" in sys.argv:
        print("Dry run - nothing sent.")
        return
    token = os.environ.get("FINANCE_LINE_TOKEN", "").strip()
    if not token:
        sys.exit("FINANCE_LINE_TOKEN is not set - add it in GitHub: Settings -> Secrets and variables -> Actions")
    broadcast(texts, token)


if __name__ == "__main__":
    main()
