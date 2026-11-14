"""
Fetch today's Thai retail fuel prices and append them to data/prices.csv.

Sources (tried in order, both if possible):
  1. PTT (OR) public price web service
  2. Bangchak public price feed

Uses only the Python standard library, so no installs are needed.
Run:  python scripts/fetch_prices.py
"""

import csv
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

BKK = timezone(timedelta(hours=7))
ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "prices.csv"
LATEST_PATH = ROOT / "data" / "latest.json"
FIELDS = ["date", "brand", "product", "price"]
UA = "Mozilla/5.0 (thai-oil-price tracker)"


def http(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def to_price(value):
    try:
        p = float(str(value).replace(",", "").strip())
        return round(p, 2) if 5 < p < 200 else None  # ignore blanks / nonsense
    except (TypeError, ValueError):
        return None


# ---------- PTT ----------
def fetch_ptt():
    url = "https://orapiweb.pttor.com/oilservice/OilPrice.asmx"
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body><CurrentOilPrice xmlns="http://www.pttor.com">'
        "<Language>en</Language></CurrentOilPrice></soap:Body></soap:Envelope>"
    )
    raw = http(
        url,
        data=body.encode(),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://www.pttor.com/CurrentOilPrice",
        },
    )
    # The result is XML wrapped (escaped) inside the SOAP response.
    m = re.search(r"<CurrentOilPriceResult>(.*)</CurrentOilPriceResult>", raw, re.S)
    inner = html.unescape(m.group(1)) if m else raw
    root = ET.fromstring(inner)

    rows = []
    for el in root.iter():
        kids = {c.tag.split("}")[-1].upper(): (c.text or "").strip() for c in el}
        if "PRODUCT" in kids and "PRICE" in kids:
            price = to_price(kids["PRICE"])
            if kids["PRODUCT"] and price:
                rows.append({"brand": "PTT", "product": kids["PRODUCT"], "price": price})
    return rows


# ---------- Bangchak ----------
def fetch_bangchak():
    raw = json.loads(http("https://oil-price.bangchak.co.th/ApiOilPrice2/en"))
    item = raw[0] if isinstance(raw, list) else raw
    oils = item.get("OilList", [])
    if isinstance(oils, str):
        oils = json.loads(oils)

    rows = []
    for o in oils:
        name = (o.get("OilName") or "").strip()
        price = to_price(o.get("PriceToday"))
        if name and price:
            rows.append({"brand": "Bangchak", "product": name, "price": price})
    return rows


# ---------- save ----------
def save(today, rows):
    CSV_PATH.parent.mkdir(exist_ok=True)
    existing = []
    if CSV_PATH.exists():
        with CSV_PATH.open(newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f) if r["date"] != today]  # re-run safe
    new = [{"date": today, **r} for r in rows]
    all_rows = sorted(existing + new, key=lambda r: (r["date"], r["brand"], r["product"]))
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(all_rows)
    LATEST_PATH.write_text(
        json.dumps({"date": today, "updated": datetime.now(BKK).isoformat(timespec="minutes"), "prices": rows},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    today = datetime.now(BKK).strftime("%Y-%m-%d")
    rows, errors = [], []
    for name, fn in [("PTT", fetch_ptt), ("Bangchak", fetch_bangchak)]:
        try:
            got = fn()
            print(f"{name}: {len(got)} prices")
            rows += got
        except Exception as e:  # keep going if one source is down
            errors.append(f"{name}: {e}")
            print(f"{name} FAILED: {e}", file=sys.stderr)

    if not rows:
        sys.exit("No prices fetched from any source:\n" + "\n".join(errors))
    save(today, rows)
    print(f"Saved {len(rows)} prices for {today}")


if __name__ == "__main__":
    main()
