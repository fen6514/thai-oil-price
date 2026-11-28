"""
Daily TikTok clip for "Thai Finance Daily" (vertical 1080x1920 MP4, about 45-60 s).

  - script: written from today's data (gold, baht, stock markets, finance news)
  - voice:  free Microsoft neural Thai voice (edge-tts)
  - video:  Pillow draws each frame (with the finance bot's charts), ffmpeg joins them

The finished clip is sent only to Fen's own LINE (push message, not broadcast),
together with a ready-to-copy TikTok caption. Fen then posts it in the TikTok app.

How the workflow runs it:
  python finance-report/make_clip.py           # make clip.mp4, cover.jpg, caption.txt in finance-report/clip-out/
  (workflow pushes those files to the "clips" branch so LINE can load them)
  python finance-report/make_clip.py --send    # push the clip to LINE_USER_ID

Secrets (GitHub secrets - never put them in this file):
  FINANCE_LINE_TOKEN - LINE channel access token (same as the daily report)
  LINE_USER_ID       - Fen's own LINE user ID (U...), the only person who receives the clip
Needs: ffmpeg, pip install pillow matplotlib edge-tts, a Thai font (fonts-noto-core).
"""

import asyncio
import glob
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import send_finance as sf  # noqa: E402  (data + chart functions of the daily report)

OUT = HERE / "clip-out"
WORK = OUT / "work"
VOICE = "th-TH-PremwadeeNeural"   # female Thai voice (male: th-TH-NiwatNeural)
RATE = "+8%"
PAUSE = 0.35                      # seconds of silence after each sentence
PUSH_URL = "https://api.line.me/v2/bot/message/push"
CLIP_BRANCH = "clips"

W, H = 1080, 1920
BG_TOP, BG_BOTTOM = (11, 20, 38), (24, 44, 78)
GOLD = (236, 192, 84)
WHITE = (255, 255, 255)
MUTED = (168, 180, 202)
UP, DOWN = (88, 214, 141), (245, 110, 100)
LEFT = 64            # left margin
TEXT_RIGHT = 900     # keep text clear of TikTok's buttons on the right


# ---------- fonts ----------
def find_font(bold):
    pats = (["NotoSansThai-Bold.ttf", "NotoSansThai*Bold*.ttf", "Loma-Bold.ttf", "*Thai*Bold*.ttf"] if bold
            else ["NotoSansThai-Regular.ttf", "NotoSansThai*.ttf", "Loma.ttf", "*Thai*.ttf"])
    for p in pats:
        hits = sorted(glob.glob(f"/usr/share/fonts/**/{p}", recursive=True))
        if hits:
            return hits[0]
    sys.exit("No Thai font found - the workflow installs fonts-noto-core")


_fonts = {}


def font(size, bold=True):
    from PIL import ImageFont, features
    key = (size, bold)
    if key not in _fonts:
        engine = ImageFont.Layout.RAQM if features.check_feature("raqm") else ImageFont.Layout.BASIC
        _fonts[key] = ImageFont.truetype(find_font(bold), size, layout_engine=engine)
    return _fonts[key]


THAI_MARKS = set(chr(c) for c in [0x0E31, *range(0x0E34, 0x0E3B), *range(0x0E47, 0x0E4F)])


def wrap(draw, text, fnt, width):
    """Split into lines that fit `width`. Breaks at spaces; very long Thai runs
    (no spaces) are split between characters, never before a vowel/tone mark."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
            line = ""
        while draw.textlength(word, font=fnt) > width:
            cut = len(word)
            while cut > 1 and (draw.textlength(word[:cut], font=fnt) > width or word[cut] in THAI_MARKS):
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        line = word
    if line:
        lines.append(line)
    return lines


def draw_lines(draw, lines, fnt, x, y, fill, gap=1.28, center_x=None):
    step = int(fnt.size * gap)
    for ln in lines:
        if center_x is not None:
            draw.text((center_x - draw.textlength(ln, font=fnt) / 2, y), ln, font=fnt, fill=fill)
        else:
            draw.text((x, y), ln, font=fnt, fill=fill)
        y += step
    return y


# ---------- frames ----------
def background():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return img


def frame(path, scene, caption, progress, big=None):
    """One still picture of the clip. big = (main text, small text) for text-only scenes."""
    from PIL import Image, ImageDraw
    img = background()
    d = ImageDraw.Draw(img, "RGBA")
    # progress bar + header
    d.rectangle([0, 0, W, 10], fill=(255, 255, 255, 40))
    d.rectangle([0, 0, int(W * progress), 10], fill=GOLD)
    d.text((LEFT, 120), "THAI FINANCE DAILY", font=font(34), fill=GOLD)
    d.text((LEFT, 168), sf.thai_today(), font=font(36, bold=False), fill=MUTED)
    y = draw_lines(d, wrap(d, scene["title"], font(72), TEXT_RIGHT - LEFT), font(72), LEFT, 250, WHITE)

    pic = scene.get("picture")
    if pic and Path(pic).exists():
        im = Image.open(pic).convert("RGB")
        box_w, box_h = W - 2 * LEFT, 820
        scale = min((box_w - 32) / im.width, (box_h - 32) / im.height)
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        top = max(y + 30, 400)
        d.rounded_rectangle([LEFT, top, LEFT + im.width + 32, top + im.height + 32], 28, fill=WHITE)
        img.paste(im, (LEFT + 16, top + 16))

    if big:
        main, small = big
        f = font(64)
        lines = wrap(d, main, f, TEXT_RIGHT - LEFT)[:7]
        y0 = max(y + 80, 760 - len(lines) * f.size * 1.3 / 2)
        y1 = draw_lines(d, lines, f, LEFT, y0, WHITE, gap=1.32)
        if small:
            draw_lines(d, wrap(d, small, font(40, False), TEXT_RIGHT - LEFT), font(40, False),
                       LEFT, y1 + 30, GOLD)

    if caption:  # subtitle box near the bottom, above TikTok's own caption area
        f = font(50)
        lines = wrap(d, caption, f, TEXT_RIGHT - LEFT - 40)[:4]
        h = int(len(lines) * f.size * 1.3) + 50
        top = 1600 - h
        d.rounded_rectangle([LEFT - 10, top, TEXT_RIGHT + 10, top + h], 26, fill=(0, 0, 0, 120))
        draw_lines(d, lines, f, LEFT + 20, top + 22, WHITE, gap=1.3)

    d.text((LEFT, 1660), "ข้อมูลเพื่อการติดตามข่าวสาร ไม่ใช่คำแนะนำการลงทุน", font=font(30, False),
           fill=MUTED)
    img.save(path)


# ---------- script from today's data ----------
def baht(v):
    return f"{v:,.0f}"


def change_words(pct, up="ขึ้น", down="ลง"):
    if pct is None or abs(pct) < 0.05:
        return "ทรงตัว"
    return f"{up if pct > 0 else down} {abs(pct):.1f} เปอร์เซ็นต์"


MONTHS_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม",
               "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def spoken_date():
    """e.g. วันเสาร์ที่ 28 พฤศจิกายน (the voice reads full month names better than "พ.ย.")."""
    d = datetime.now(sf.BKK)
    return f"วัน{sf.TH_DAYS[d.weekday()]}ที่ {d.day} {MONTHS_FULL[d.month - 1]}"


def make_script():
    """List of scenes: {title, picture, lines: [(caption, speech)], news: bool}."""
    WORK.mkdir(parents=True, exist_ok=True)
    today = datetime.now(sf.BKK).date()
    scenes = [{"title": "สรุปการเงินวันนี้", "big": ("ทอง  ค่าเงินบาท  หุ้น  และข่าวการเงินเด่น",
                                                   "สรุปจบใน 1 นาที"),
               "lines": [(None, f"สวัสดีค่ะ สรุปการเงินประจำ{spoken_date()} มาดูกันเลยค่ะ")]}]

    # gold
    gold = sf.safe(sf.thai_gold)
    gold_png = WORK / "gold.png"
    if sf.safe(sf.gold_picture, gold_png, gold) is None and not gold_png.exists():
        gold_png = None
    lines = []
    if gold:
        lines.append((f"ทองคำแท่ง รับซื้อ {baht(gold['bar_buy'])} ขายออก {baht(gold['bar_sell'])} บาท",
                      f"ราคาทองคำแท่งวันนี้ รับซื้อบาทละ {baht(gold['bar_buy'])} บาท "
                      f"ขายออก {baht(gold['bar_sell'])} บาท"))
        prev = [v for d, v in sf.history_series("gold_bar_sell") if d < today]
        if prev:
            diff = gold["bar_sell"] - prev[-1]
            if abs(diff) >= 1:
                word = "เพิ่มขึ้น" if diff > 0 else "ลดลง"
                lines.append((f"{word} {baht(abs(diff))} บาท จากวันก่อน",
                              f"{word} {baht(abs(diff))} บาท จากวันก่อนหน้า"))
            else:
                lines.append(("เท่ากับวันก่อน", "เท่ากับวันก่อนหน้า"))
    world = sf.safe(sf.yahoo_series, "GC=F")
    if world and len(world) > 5:
        pct = sf.pct_change(world[-1][1], world[0][1])
        lines.append((f"ทองโลก 1 เดือน {change_words(pct)}",
                      f"ส่วนทองคำโลกในรอบ 1 เดือน {change_words(pct)}"))
    if lines:
        scenes.append({"title": "ราคาทองวันนี้", "picture": gold_png, "lines": lines})

    # baht
    fx_png = WORK / "fx.png"
    if sf.safe(sf.fx_picture, fx_png) is None and not fx_png.exists():
        fx_png = None
    usd = sf.safe(sf.yahoo_series, "THB=X")
    if usd:
        last = usd[-1][1]
        lines = [(f"1 ดอลลาร์ = {last:.2f} บาท", f"ค่าเงินบาทวันนี้อยู่ที่ {last:.2f} บาท ต่อดอลลาร์")]
        old = sf.value_on_or_before(usd, today - timedelta(days=30)) or usd[0][1]
        pct = sf.pct_change(last, old)
        if pct is not None and abs(pct) >= 0.05:
            word = "อ่อนค่าลง" if pct > 0 else "แข็งค่าขึ้น"  # more baht per dollar = weaker baht
            lines.append((f"1 เดือน เงินบาท{word} {abs(pct):.1f}%",
                          f"เทียบกับเดือนก่อน เงินบาท{word} {abs(pct):.1f} เปอร์เซ็นต์"))
        scenes.append({"title": "ค่าเงินบาท", "picture": fx_png, "lines": lines})

    # stock markets
    idx_png = WORK / "indices.png"
    if sf.safe(sf.indices_picture, idx_png) is None and not idx_png.exists():
        idx_png = None
    moves = []
    for name, _market, symbol in sf.INDICES:
        s = sf.safe(sf.yahoo_series, symbol)
        if s and len(s) > 1:
            moves.append((name, s[-1][1], sf.pct_change(s[-1][1], s[-2][1])))
    lines = []
    for name, last, pct in moves:
        if name == "SET":
            lines.append((f"SET {last:,.2f} จุด {change_words(pct, 'บวก', 'ลบ')}",
                          f"ตลาดหุ้นไทย ดัชนีเซ็ต อยู่ที่ {last:,.2f} จุด {change_words(pct, 'บวก', 'ลบ')}"))
    world_moves = [m for m in moves if m[0] != "SET" and m[2] is not None]
    if len(world_moves) >= 2:
        best = max(world_moves, key=lambda m: m[2])
        worst = min(world_moves, key=lambda m: m[2])
        if best[2] > 0:
            lines.append((f"ขึ้นแรงสุด: {best[0]} +{best[2]:.1f}%",
                          f"ตลาดโลก {best[0]} ขึ้นแรงที่สุด {best[2]:.1f} เปอร์เซ็นต์"))
        if worst[2] < 0:
            lines.append((f"ลงแรงสุด: {worst[0]} {worst[2]:.1f}%",
                          f"ส่วน {worst[0]} ลงมากที่สุด {abs(worst[2]):.1f} เปอร์เซ็นต์"))
    if lines:
        scenes.append({"title": "ตลาดหุ้น", "picture": idx_png, "lines": lines})

    # finance news (top 3)
    articles = [a for a in (sf.safe(sf.fetch_articles) or []) if a["section"] == "finance"]
    pp = [a for a in articles if "prachachat" in a["feed"]]
    kh = [a for a in articles if "kaohoon" in a["feed"]]
    mixed = [a for pair in zip(pp, kh) for a in pair] + pp[len(kh):] + kh[len(pp):]
    for i, a in enumerate(mixed[:3], 1):
        title = a["title"][:120]
        scenes.append({"title": f"ข่าวเด่น {i}/3", "big": (title, f"ที่มา: {a['source']}"),
                       "lines": [(None, ("ข่าวการเงินเด่นวันนี้ " if i == 1 else "")
                                  + f"ข่าวที่ {i} {title}")]})

    scenes.append({"title": "ติดตามทุกวัน", "big": ("สรุปการเงินทุกเช้า กดติดตามไว้ได้เลย",
                                                    "ข้อมูลจากสมาคมค้าทองคำ, Yahoo Finance และสำนักข่าว"),
                   "lines": [(None, "ติดตามสรุปการเงินได้ทุกวัน กดติดตามไว้นะคะ แล้วพบกันพรุ่งนี้ค่ะ")]})
    return scenes


# ---------- voice + video ----------
def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


VOICES = [  # tried in order; the first one that works is used for the whole clip
    ("edge", VOICE, RATE),
    ("edge", VOICE, "+0%"),
    ("edge", "th-TH-NiwatNeural", "+0%"),
    ("google", "th", None),
]
_voice = []


def _say(engine, voice, rate, text, path):
    if engine == "edge":
        import edge_tts
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(path)))
    else:
        from gtts import gTTS
        gTTS(text, lang=voice).save(str(path))
    if not path.exists() or path.stat().st_size < 1000:
        raise RuntimeError("no audio")


def speak(text, path):
    """Same voice for the whole clip: the first working one is remembered."""
    choices = _voice or VOICES
    for engine, voice, rate in choices:
        for attempt in range(2):
            try:
                _say(engine, voice, rate, text, path)
                if not _voice:
                    _voice.append((engine, voice, rate))
                    print(f"voice used: {engine} {voice} {rate or ''}")
                return
            except Exception as e:
                print(f"voice {engine}/{voice} attempt {attempt + 1} failed: {e}", file=sys.stderr)
    raise RuntimeError("text-to-speech failed")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def build_clip(scenes):
    from PIL import features
    print("Thai text shaping (raqm):", features.check_feature("raqm"))
    steps = [(s, cap, sp) for s in scenes for cap, sp in s["lines"]]
    segments = []
    for n, (scene, caption, speech) in enumerate(steps):
        png, mp3, mp4 = WORK / f"f{n:02d}.png", WORK / f"v{n:02d}.mp3", WORK / f"s{n:02d}.mp4"
        frame(png, scene, caption, (n + 1) / len(steps), scene.get("big"))
        speak(speech, mp3)
        length = duration(mp3) + PAUSE
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", str(png), "-i", str(mp3),
             "-filter_complex", f"[1:a]apad=pad_dur={PAUSE}[a]", "-map", "0:v", "-map", "[a]",
             "-t", f"{length:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
             "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
             "-ac", "2", str(mp4)])
        segments.append(mp4)
        print(f"[{length:4.1f}s] {speech}")
    listing = WORK / "list.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8")
    clip = OUT / "clip.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
         "-movflags", "+faststart", str(clip)])
    from PIL import Image
    Image.open(WORK / "f00.png").convert("RGB").save(OUT / "cover.jpg", quality=85)
    print(f"clip saved: {clip} ({duration(clip):.0f} s, {clip.stat().st_size / 1e6:.1f} MB)")


def caption_text():
    d = datetime.now(sf.BKK)
    return (f"สรุปการเงินวันนี้ {d.day} {sf.TH_MONTHS[d.month - 1]} {d.year + 543} "
            "ราคาทอง ค่าเงินบาท หุ้นไทย-หุ้นโลก และข่าวการเงินเด่น ใน 1 นาที\n"
            "#ราคาทอง #ทองคำ #ค่าเงินบาท #หุ้นไทย #การเงิน #ข่าวเศรษฐกิจ #การลงทุน")


# ---------- send to Fen's LINE ----------
def send():
    meta = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
    repo = os.environ.get("GITHUB_REPOSITORY", sf.REPO)
    base = f"https://raw.githubusercontent.com/{repo}/{CLIP_BRANCH}/"
    video, cover = base + meta["video"], base + meta["cover"]
    msgs = [{"type": "video", "originalContentUrl": video, "previewImageUrl": cover},
            {"type": "text", "text": "🎬 คลิป TikTok วันนี้พร้อมแล้ว\n"
                                     "กดค้างที่คลิป > บันทึก แล้วโพสต์ใน TikTok\n"
                                     f"(ถ้าเล่นไม่ได้ ดาวน์โหลดที่นี่: {video})\n\n"
                                     "👇 คัดลอกแคปชันนี้ไปใช้ได้เลย"},
            {"type": "text", "text": meta["caption"]}]
    token = os.environ.get("FINANCE_LINE_TOKEN", "").strip()
    user = os.environ.get("LINE_USER_ID", "").strip()
    if not token or not user:
        sys.exit("FINANCE_LINE_TOKEN or LINE_USER_ID secret is missing")
    req = urllib.request.Request(PUSH_URL, method="POST",
                                 data=json.dumps({"to": user, "messages": msgs}).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"clip sent to LINE (HTTP {r.status}): {video}")
    except urllib.error.HTTPError as e:
        sys.exit(f"LINE push FAILED: HTTP {e.code} {e.read().decode('utf-8', 'replace')}")


def main():
    if "--send" in sys.argv:
        send()
        return
    OUT.mkdir(exist_ok=True)
    scenes = make_script()
    build_clip(scenes)
    stamp = datetime.now(sf.BKK).strftime("%Y-%m-%d-%H%M")
    meta = {"video": f"clip-{stamp}.mp4", "cover": f"cover-{stamp}.jpg", "caption": caption_text()}
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "caption.txt").write_text(meta["caption"], encoding="utf-8")
    print("caption:\n" + meta["caption"])


if __name__ == "__main__":
    main()
