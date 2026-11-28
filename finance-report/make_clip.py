"""
Daily TikTok clip for "Thai Finance Daily" (vertical 1080x1920 MP4, about 60-70 s).

Presenter: "หมูออม", a cartoon piggy bank drawn by this script. Its mouth moves with
the voice, it blinks and bobs, and a speech bubble shows each point in plain Thai.

  - script: written from today's data (gold, baht, stock markets, finance news),
            with simple "what this means for you" lines
  - voice:  free Microsoft neural Thai voice (edge-tts); Google voice as backup
  - video:  Pillow draws the frames (with the finance bot's charts), ffmpeg encodes

The finished clip is sent only to Fen's own LINE (push message, not broadcast),
together with a ready-to-copy TikTok caption. Fen then posts it in the TikTok app.

How the workflow runs it:
  python finance-report/make_clip.py           # make clip.mp4, cover.jpg, frames.jpg, caption.txt in finance-report/clip-out/
  (workflow pushes those files to the "clips" branch so LINE can load them)
  python finance-report/make_clip.py --send    # push the clip to LINE_USER_ID

Secrets (GitHub secrets - never put them in this file):
  FINANCE_LINE_TOKEN - LINE channel access token (same as the daily report)
  LINE_USER_ID       - Fen's own LINE user ID (U...), the only person who receives the clip
Needs: ffmpeg, pip install pillow matplotlib edge-tts gTTS, the Kanit font (downloaded by the workflow).
"""

import array
import asyncio
import glob
import json
import math
import os
import subprocess
import sys
import urllib.error
import urllib.request
import wave
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import send_finance as sf  # noqa: E402  (data + chart functions of the daily report)

OUT = HERE / "clip-out"
WORK = OUT / "work"
VOICE = "th-TH-PremwadeeNeural"   # female Thai voice (male: th-TH-NiwatNeural)
RATE = "+5%"
PITCH = "+12Hz"                   # a little higher = more cartoon-like
PAUSE = 0.35                      # seconds of silence after each sentence
FPS = 20
SR = 22050                        # audio sample rate used for lip-sync and the final mix
PUSH_URL = "https://api.line.me/v2/bot/message/push"
CLIP_BRANCH = "clips"

W, H = 1080, 1920
BG_TOP, BG_BOTTOM = (11, 20, 38), (24, 44, 78)
GOLD = (236, 192, 84)
WHITE = (255, 255, 255)
MUTED = (168, 180, 202)
INK = (12, 68, 124)  # text in the speech bubble
LEFT = 64            # left margin
TEXT_RIGHT = 900     # keep text clear of TikTok's buttons on the right
CHART_BOTTOM = 1230  # charts / big text stay above the piggy + bubble area
PIG_X, PIG_Y = 30, 1330


# ---------- fonts ----------
FONT_DIR = HERE / "fonts"  # the workflow downloads Kanit (Thai + English + numbers) here


def find_font(bold):
    # Kanit first; Loma (fonts-thai-tlwg) also has English letters and numbers.
    # (Noto Sans Thai has NO English letters/numbers - they show as boxes.)
    pats = (["Kanit-SemiBold.ttf", "Kanit-Bold.ttf", "Loma-Bold.ttf"] if bold
            else ["Kanit-Regular.ttf", "Kanit-Light.ttf", "Loma.ttf"])
    for p in pats:
        hits = sorted(glob.glob(str(FONT_DIR / p))) + sorted(
            glob.glob(f"/usr/share/fonts/**/{p}", recursive=True))
        if hits:
            return hits[0]
    sys.exit("No Thai font found - the workflow downloads Kanit into finance-report/fonts")


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


def draw_lines(draw, lines, fnt, x, y, fill, gap=1.28):
    step = int(fnt.size * gap)
    for ln in lines:
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += step
    return y


# ---------- the piggy (หมูออม) ----------
PINK, PINK_DARK, OUTLINE = (244, 192, 209), (237, 147, 177), (153, 53, 86)
DEEP, BLUSH = (114, 36, 62), (240, 120, 150)
_pigs = {}


def pig(mouth, blink):
    """Piggy picture (RGBA, 360x340). mouth 0 = closed smile .. 3 = wide open."""
    key = (mouth, blink)
    if key in _pigs:
        return _pigs[key]
    from PIL import Image, ImageDraw
    s = 2  # draw twice as big, then shrink = smooth edges
    im = Image.new("RGBA", (360 * s, 340 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def e(box, **kw):  # ellipse in 1x coordinates
        d.ellipse([v * s for v in box], **kw)

    def poly(pts, **kw):
        d.polygon([(x * s, y * s) for x, y in pts], **kw)

    w = 5 * s
    for x0 in (95, 225):  # legs
        d.rounded_rectangle([x0 * s, 262 * s, (x0 + 40) * s, 318 * s], 12 * s, fill=PINK_DARK, outline=OUTLINE, width=w)
    poly([(88, 110), (100, 40), (150, 92)], fill=PINK_DARK, outline=OUTLINE, width=w)   # ears
    poly([(210, 92), (260, 40), (272, 110)], fill=PINK_DARK, outline=OUTLINE, width=w)
    e([30, 70, 330, 300], fill=PINK, outline=OUTLINE, width=w)                          # body
    d.rounded_rectangle([150 * s, 86 * s, 210 * s, 100 * s], 7 * s, fill=DEEP)          # coin slot
    e([84, 182, 116, 204], fill=BLUSH)                                                  # cheeks
    e([244, 182, 276, 204], fill=BLUSH)
    for cx in (130, 230):                                                               # eyes
        if blink:
            d.line([(cx - 13) * s, 160 * s, (cx + 13) * s, 160 * s], fill=DEEP, width=6 * s)
        else:
            e([cx - 13, 143, cx + 13, 175], fill=(45, 18, 30))
            e([cx - 6, 148, cx + 2, 156], fill=WHITE)
    e([140, 168, 220, 216], fill=PINK_DARK, outline=OUTLINE, width=4 * s)               # snout
    e([158, 184, 172, 200], fill=DEEP)
    e([188, 184, 202, 200], fill=DEEP)
    if mouth == 0:                                                                      # mouth
        d.arc([156 * s, 212 * s, 204 * s, 246 * s], 20, 160, fill=DEEP, width=6 * s)
    else:
        h = [0, 12, 22, 32][mouth]
        e([160, 226, 200, 226 + h], fill=DEEP)
        e([170, 226 + h * 0.45, 190, 226 + h * 0.95], fill=(230, 90, 110))
    im = im.resize((360, 340), Image.LANCZOS)
    _pigs[key] = im
    return im


def bubble(d, text):
    """Speech bubble to the right of the piggy, with a tail pointing at it."""
    f = font(46)
    x0, x1 = 380, TEXT_RIGHT + 20
    lines = wrap(d, text, f, x1 - x0 - 56)[:3]
    h = int(len(lines) * f.size * 1.32) + 52
    bottom = 1500
    top = bottom - h
    d.rounded_rectangle([x0, top, x1, bottom], 34, fill=WHITE)
    d.polygon([(x0 + 6, bottom - 70), (x0 + 6, bottom - 26), (x0 - 46, bottom - 10)], fill=WHITE)
    draw_lines(d, lines, f, x0 + 28, top + 22, INK, gap=1.32)


# ---------- frames ----------
def background():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return img


_bg = []


def base_frame(scene, caption, progress):
    """Everything except the piggy: header, title, chart or big text, speech bubble."""
    from PIL import Image, ImageDraw
    if not _bg:
        _bg.append(background())
    img = _bg[0].copy()
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, W, 10], fill=(255, 255, 255, 40))
    d.rectangle([0, 0, int(W * progress), 10], fill=GOLD)
    d.text((LEFT, 120), "THAI FINANCE DAILY", font=font(34), fill=GOLD)
    d.text((LEFT, 168), sf.thai_today(), font=font(36, bold=False), fill=MUTED)
    y = draw_lines(d, wrap(d, scene["title"], font(72), TEXT_RIGHT - LEFT), font(72), LEFT, 250, WHITE)

    pic = scene.get("picture")
    if pic and Path(pic).exists():
        im = Image.open(pic).convert("RGB")
        box_w, box_h = W - 2 * LEFT, CHART_BOTTOM - y - 40
        scale = min((box_w - 32) / im.width, (box_h - 32) / im.height)
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        top = max(y + 30, int((y + CHART_BOTTOM) / 2 - (im.height + 32) / 2))
        d.rounded_rectangle([LEFT, top, LEFT + im.width + 32, top + im.height + 32], 28, fill=WHITE)
        img.paste(im, (LEFT + 16, top + 16))

    big = scene.get("big")
    if big:
        main, small = big
        f = font(64)
        lines = wrap(d, main, f, TEXT_RIGHT - LEFT)[:6]
        y0 = max(y + 80, 700 - len(lines) * f.size * 1.3 / 2)
        y1 = draw_lines(d, lines, f, LEFT, y0, WHITE, gap=1.32)
        if small:
            draw_lines(d, wrap(d, small, font(40, False), TEXT_RIGHT - LEFT), font(40, False),
                       LEFT, y1 + 30, GOLD)

    if caption:
        bubble(d, caption)
    d.text((LEFT, 1700), "ข้อมูลเพื่อการติดตามข่าวสาร ไม่ใช่คำแนะนำการลงทุน", font=font(30, False),
           fill=MUTED)
    return img


def with_pig(base, mouth, blink, bob):
    img = base.copy()
    p = pig(mouth, blink)
    img.paste(p, (PIG_X, PIG_Y + bob), p)
    return img


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
    """List of scenes: {title, picture or big, lines: [(bubble text, speech)]}.
    Each scene says the number, then what it means for an ordinary person."""
    WORK.mkdir(parents=True, exist_ok=True)
    today = datetime.now(sf.BKK).date()
    scenes = [{"title": "สรุปการเงินวันนี้",
               "big": ("ทอง  ค่าเงินบาท  หุ้น  และข่าวเด่น", "เล่าง่าย ๆ จบใน 1 นาที"),
               "lines": [("สวัสดีค่ะ หมูออมมาแล้ว",
                          f"สวัสดีค่ะ หมูออมมาแล้ว วันนี้{spoken_date()} มาดูเรื่องเงินกันค่ะ")]}]

    # gold
    gold = sf.safe(sf.thai_gold)
    gold_png = WORK / "gold.png"
    if sf.safe(sf.gold_picture, gold_png, gold) is None and not gold_png.exists():
        gold_png = None
    lines = []
    if gold:
        lines.append((f"ทองคำแท่ง ขายออก {baht(gold['bar_sell'])} บาท",
                      f"ทองคำแท่งวันนี้ ร้านขายออกบาทละ {baht(gold['bar_sell'])} บาท "
                      f"รับซื้อคืน {baht(gold['bar_buy'])} บาท"))
        prev = [v for d, v in sf.history_series("gold_bar_sell") if d < today]
        if prev:
            diff = gold["bar_sell"] - prev[-1]
            if diff >= 1:
                lines.append((f"แพงขึ้น {baht(diff)} บาท จากวันก่อน",
                              f"แพงขึ้น {baht(diff)} บาท จากวันก่อน "
                              "แปลว่า ใครจะซื้อทองวันนี้ ต้องจ่ายเพิ่มนิดนึงนะคะ"))
            elif diff <= -1:
                lines.append((f"ถูกลง {baht(-diff)} บาท จากวันก่อน",
                              f"ถูกลง {baht(-diff)} บาท จากวันก่อน "
                              "แปลว่า ใครอยากซื้อทอง วันนี้จ่ายน้อยลงค่ะ"))
            else:
                lines.append(("ราคาเท่ากับวันก่อน", "ราคาเท่ากับวันก่อนค่ะ"))
    world = sf.safe(sf.yahoo_series, "GC=F")
    if world and len(world) > 5:
        pct = sf.pct_change(world[-1][1], world[0][1])
        if pct is not None and abs(pct) >= 0.5:
            word = "แพงขึ้น" if pct > 0 else "ถูกลง"
            lines.append((f"ทองทั่วโลก เดือนนี้{word} {abs(pct):.1f}%",
                          f"ส่วนทองทั่วโลก ในหนึ่งเดือนนี้{word} {abs(pct):.1f} เปอร์เซ็นต์ "
                          "ราคาทองบ้านเรา ก็ขึ้นลงตามทองโลกเป็นหลักค่ะ"))
    if lines:
        scenes.append({"title": "ราคาทองวันนี้", "picture": gold_png, "lines": lines})

    # baht
    fx_png = WORK / "fx.png"
    if sf.safe(sf.fx_picture, fx_png) is None and not fx_png.exists():
        fx_png = None
    usd = sf.safe(sf.yahoo_series, "THB=X")
    if usd:
        last = usd[-1][1]
        lines = [(f"1 ดอลลาร์ = {last:.2f} บาท",
                  f"ค่าเงินบาทวันนี้ หนึ่งดอลลาร์ แลกได้ {last:.2f} บาท")]
        old = sf.value_on_or_before(usd, today - timedelta(days=30)) or usd[0][1]
        pct = sf.pct_change(last, old)
        if pct is not None and abs(pct) >= 0.3:
            if pct > 0:  # more baht per dollar = weaker baht
                lines.append(("บาทอ่อนลง: เที่ยวนอก ของนำเข้า แพงขึ้น",
                              f"เทียบกับเดือนก่อน เงินบาทอ่อนลง {abs(pct):.1f} เปอร์เซ็นต์ "
                              "แปลว่า ไปเที่ยวต่างประเทศ หรือซื้อของนำเข้า จะแพงขึ้นนิดนึงค่ะ"))
            else:
                lines.append(("บาทแข็งขึ้น: เที่ยวนอก ของนำเข้า ถูกลง",
                              f"เทียบกับเดือนก่อน เงินบาทแข็งขึ้น {abs(pct):.1f} เปอร์เซ็นต์ "
                              "แปลว่า ไปเที่ยวต่างประเทศ หรือซื้อของนำเข้า จะถูกลงค่ะ"))
        else:
            lines.append(("เงินบาทนิ่ง ๆ ทั้งเดือน", "เทียบกับเดือนก่อน เงินบาทแทบไม่เปลี่ยนเลยค่ะ"))
        scenes.append({"title": "ค่าเงินบาท", "picture": fx_png, "lines": lines})

    # stock markets
    idx_png = WORK / "indices.png"
    if sf.safe(sf.indices_picture, idx_png) is None and not idx_png.exists():
        idx_png = None
    moves = []
    set_hist = sf.history_series("set")
    for name, _market, symbol in sf.INDICES:
        s = sf.safe(sf.yahoo_series, symbol)
        if s and len(s) < 3 and symbol == "^SET.BK" and set_hist:  # Yahoo often has 1 SET day only
            s = [h for h in set_hist if h[0] < s[-1][0]] + s[-1:]
        if s and len(s) > 1:
            moves.append((name, s[-1][1], sf.pct_change(s[-1][1], s[-2][1])))
    lines = []
    for name, last, pct in moves:
        if name == "SET":
            mood = ("หุ้นไทยส่วนใหญ่ราคาขึ้น" if pct and pct >= 0.05 else
                    "หุ้นไทยส่วนใหญ่ราคาลง" if pct and pct <= -0.05 else "หุ้นไทยนิ่ง ๆ")
            lines.append((f"SET {last:,.0f} จุด {change_words(pct, 'บวก', 'ลบ')} = {mood}",
                          f"หุ้นไทย ดัชนีเซ็ต ซึ่งเป็นเหมือนคะแนนรวมของทั้งตลาด อยู่ที่ {last:,.0f} จุด "
                          f"{change_words(pct, 'บวก', 'ลบ')} แปลว่า{mood}ค่ะ"))
    world_moves = [m for m in moves if m[0] != "SET" and m[2] is not None]
    if len(world_moves) >= 2:
        best = max(world_moves, key=lambda m: m[2])
        worst = min(world_moves, key=lambda m: m[2])
        if best[2] > 0:
            lines.append((f"ขึ้นแรงสุด: {best[0]} +{best[2]:.1f}%",
                          f"ตลาดหุ้นต่างประเทศ ที่ขึ้นแรงที่สุดคือ {best[0]} บวก {best[2]:.1f} เปอร์เซ็นต์"))
        if worst[2] < 0:
            lines.append((f"ลงแรงสุด: {worst[0]} {worst[2]:.1f}%",
                          f"ส่วนที่ลงมากที่สุดคือ {worst[0]} ลบ {abs(worst[2]):.1f} เปอร์เซ็นต์ค่ะ"))
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
                       "lines": [(["มาดูข่าวเด่นกัน", "ข่าวต่อไป", "ข่าวสุดท้าย"][i - 1],
                                  ("มาดูข่าวการเงินเด่นวันนี้กันค่ะ " if i == 1 else "")
                                  + f"ข่าวที่ {i} {title}")]})

    scenes.append({"title": "ติดตามทุกวัน", "big": ("สรุปเรื่องเงินทุกเช้า เข้าใจง่ายใน 1 นาที",
                                                    "ข้อมูลจากสมาคมค้าทองคำ, Yahoo Finance และสำนักข่าว"),
                   "lines": [("กดติดตามหมูออมด้วยนะ",
                              "ถ้าชอบ กดติดตามหมูออมไว้นะคะ พรุ่งนี้มาเจอกันใหม่ค่ะ")]})
    return scenes


# ---------- voice ----------
def run(cmd, **kw):
    return subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kw)


VOICES = [  # tried in order; ONE voice is used for the whole clip
    ("edge", VOICE, RATE),          # Microsoft neural voice (natural, but sometimes flaky)
    ("google", "th", None),         # Google Translate voice (plainer, reliable backup)
]


def _say(engine, voice, rate, text, path):
    if engine == "edge":
        import edge_tts
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate, pitch=PITCH).save(str(path)))
    else:
        from gtts import gTTS
        gTTS(text, lang=voice).save(str(path))
    if not path.exists() or path.stat().st_size < 1000:
        raise RuntimeError("no audio")


def speak_all(texts, paths):
    """Record every sentence with the same voice. If a voice keeps failing (after
    rewording and retrying), start again with the next voice so the clip never mixes voices."""
    import time
    for engine, voice, rate in VOICES:
        try:
            for text, path in zip(texts, paths):
                # Microsoft's service refuses some sentences ("No audio was received"),
                # so a slightly reworded version is tried too.
                variants = [text, f"{text} ค่ะ", f"และ{text}", f"คือ{text} ค่ะ"]
                for attempt, said in enumerate(variants + [text]):
                    try:
                        _say(engine, voice, rate, said, path)
                        if said != text:
                            print(f"voice {engine}: reworded to '{said}'")
                        break
                    except Exception as e:
                        print(f"voice {engine} attempt {attempt + 1} failed on '{said}': {e}",
                              file=sys.stderr)
                        if attempt == len(variants):
                            raise
                        time.sleep(2 * (attempt + 1))
                time.sleep(0.5)  # be gentle with the free service
            print(f"voice used: {engine} {voice} {rate or ''}")
            return
        except Exception:
            print(f"voice {engine} gave up - trying the next voice", file=sys.stderr)
    raise RuntimeError("text-to-speech failed with every voice")


def samples(mp3):
    """Mono 16-bit samples of an mp3 at SR (decoded by ffmpeg)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return array.array("h", out)


def mouth_levels(snd, n_frames):
    """Mouth opening (0-3) for each video frame, from how loud the voice is."""
    per = SR / FPS
    loud = []
    for k in range(n_frames):
        chunk = snd[int(k * per):int((k + 1) * per)]
        loud.append(math.sqrt(sum(v * v for v in chunk[::4]) / max(1, len(chunk[::4]))) if chunk else 0)
    peak = sorted(loud)[int(len(loud) * 0.95)] if loud else 1
    peak = peak or 1
    levels = []
    for v in loud:
        r = v / peak
        levels.append(0 if r < 0.18 else 1 if r < 0.45 else 2 if r < 0.75 else 3)
    return levels


# ---------- video ----------
def build_clip(scenes):
    from PIL import features
    print("Thai text shaping (raqm):", features.check_feature("raqm"))
    steps = [(s, cap, sp) for s in scenes for cap, sp in s["lines"]]
    mp3s = [WORK / f"v{n:02d}.mp3" for n in range(len(steps))]
    speak_all([sp for _, _, sp in steps], mp3s)

    # one continuous soundtrack: each sentence + a short pause
    audio = array.array("h")
    parts = []
    for mp3 in mp3s:
        snd = samples(mp3)
        snd.extend([0] * int(PAUSE * SR))
        parts.append(snd)
        audio.extend(snd)
    track = WORK / "voice.wav"
    with wave.open(str(track), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(audio.tobytes())

    clip = OUT / "clip.mp4"
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", str(track), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
         "-shortest", "-movflags", "+faststart", str(clip)], stdin=subprocess.PIPE)
    done_samples, done_frames = 0, 0
    for n, ((scene, caption, speech), snd) in enumerate(zip(steps, parts)):
        base = base_frame(scene, caption, (n + 1) / len(steps))
        done_samples += len(snd)
        n_frames = round(done_samples / SR * FPS) - done_frames   # keeps picture and sound in step
        levels = mouth_levels(snd, n_frames)
        for k, level in enumerate(levels):
            t = (done_frames + k) / FPS
            blink = (t % 3.2) < 0.15
            bob = int(round(8 * math.sin(t * 2 * math.pi / 1.6)))
            img = with_pig(base, level, blink, bob)
            if k == len(levels) // 3:
                img.save(WORK / f"f{n:02d}.png")  # one still per sentence for the preview sheet
            enc.stdin.write(img.tobytes())
        done_frames += n_frames
        print(f"[{len(snd) / SR:4.1f}s] {speech}")
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg failed to make the video")

    from PIL import Image
    Image.open(WORK / "f00.png").convert("RGB").save(OUT / "cover.jpg", quality=85)
    # contact sheet of every sentence, to check the clip by eye without playing it
    cols, tw, th = 5, 270, 480
    frames = sorted(WORK.glob("f[0-9]*.png"))
    sheet = Image.new("RGB", (cols * tw, -(-len(frames) // cols) * th), (0, 0, 0))
    for i, p in enumerate(frames):
        sheet.paste(Image.open(p).convert("RGB").resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    sheet.save(OUT / "frames.jpg", quality=85)
    print(f"clip saved: {clip} ({done_frames / FPS:.0f} s, {clip.stat().st_size / 1e6:.1f} MB)")


def caption_text():
    d = datetime.now(sf.BKK)
    return (f"หมูออมสรุปเรื่องเงินวันนี้ {d.day} {sf.TH_MONTHS[d.month - 1]} {d.year + 543} "
            "ราคาทอง ค่าเงินบาท หุ้น และข่าวเด่น เล่าง่าย ๆ ใน 1 นาที 🐷\n"
            "#หมูออม #ราคาทอง #ทองคำ #ค่าเงินบาท #หุ้นไทย #การเงิน #ข่าวเศรษฐกิจ #ออมเงิน")


# ---------- send to Fen's LINE ----------
def send():
    meta = json.loads((OUT / "meta.json").read_text(encoding="utf-8"))
    repo = os.environ.get("GITHUB_REPOSITORY", sf.REPO)
    base = f"https://raw.githubusercontent.com/{repo}/{CLIP_BRANCH}/"
    video, cover = base + meta["video"], base + meta["cover"]
    msgs = [{"type": "video", "originalContentUrl": video, "previewImageUrl": cover},
            {"type": "text", "text": "🎬 คลิป TikTok วันนี้พร้อมแล้ว\n"
                                     "กดค้างที่คลิป > บันทึก แล้วโพสต์ใน TikTok\n"
                                     "(อย่าลืมเปิดป้าย \"AI-generated content\")\n"
                                     f"ถ้าเล่นไม่ได้ ดาวน์โหลดที่นี่: {video}\n\n"
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
