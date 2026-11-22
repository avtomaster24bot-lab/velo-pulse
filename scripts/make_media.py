#!/usr/bin/env python3
"""ВелоПульс: для каждого поста дня делает
 - карусель слайдов 1080×1350 PNG (обложка, 4 слайда, финальная карточка) + ZIP,
 - аудио-рассказ (edge-tts, с таймингами слов),
 - вертикальное видео 1080×1920 (слайды + голос + субтитры) и постер,
 - готовые тексты для Telegram / Instagram / YouTube / TikTok.
Файлы кладутся в media/ и загружаются в GitHub Release `day-ДАТА`.

MEDIA_DATE=2026-11-22  MEDIA_FORCE=1  NO_RELEASE=1  MEDIA_LIMIT=1
"""
import asyncio
import io
import json
import os
import re
import subprocess
import time
import zipfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from common import CFG, DATA, REPO, ROOT, SITE, UA, load_json, log, save_json

FONTS = ROOT / "assets" / "fonts"
MEDIA = ROOT / "media"
SW, SH = 1080, 1350          # слайд
VW, VH = 1080, 1920          # видео
FPS = 30
TRANS = 0.45
LEAD = 0.4
END = 3.0
MAX_LEN = 58.0
BG = (12, 14, 20)
TXT = (244, 246, 250)
MUT = (168, 176, 192)
ORANGE = (255, 90, 54)
SITE_SHORT = SITE.replace("https://", "").rstrip("/")
VOICES = [CFG.get("voice", "ru-RU-DmitryNeural"), CFG.get("voice_alt", "ru-RU-SvetlanaNeural")]
_fc = {}


def font(w, s):
    k = (w, s)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(str(FONTS / f"Inter-{w}.ttf"), s)
    return _fc[k]


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def wrap(d, text, f, width):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(d, text, weight, width, height, mx, mn=30, sp=1.28):
    size = mx
    while True:
        f = font(weight, size)
        lines = wrap(d, text, f, width)
        lh = int(size * sp)
        if lh * len(lines) <= height or size <= mn:
            return f, lines, lh
        size -= 2


def draw_lines(d, xy, lines, f, lh, fill, **kw):
    x, y = xy
    for l in lines:
        d.text((x, y), l, font=f, fill=fill, **kw)
        y += lh
    return y


def cover_crop(img, w, h, fy=0.42):
    iw, ih = img.size
    s = max(w / iw, h / ih)
    nw, nh = int(iw * s + 0.5), int(ih * s + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = int((nh - h) * fy)
    return img.crop((x, y, x + w, y + h))


def gradient(w, h, top_a, bot_a, color=BG, start=0.0):
    g = Image.new("L", (1, h))
    for y in range(h):
        t = max(0.0, (y / max(h - 1, 1) - start) / max(1 - start, 1e-6))
        g.putpixel((0, y), int(top_a + (bot_a - top_a) * min(t, 1) ** 1.3))
    g = g.resize((w, h))
    layer = Image.new("RGBA", (w, h), color + (0,))
    layer.putalpha(g)
    return layer


def logo(size):
    im = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    S = size * 4
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=S // 4, fill=(15, 18, 24, 255))
    r = int(S * 0.33)
    c = S // 2
    for i in range(int(S * 0.08)):
        t = i / (S * 0.08)
        col = tuple(int(a + (b - a) * t) for a, b in zip(ORANGE, (255, 177, 26)))
        d.ellipse([c - r - i // 2, c - r - i // 2, c + r + i // 2, c + r + i // 2], outline=col)
    pts = [(0.125, 0.515), (0.31, 0.515), (0.39, 0.34), (0.5, 0.69), (0.6, 0.45), (0.65, 0.52), (0.88, 0.52)]
    d.line([(x * S, y * S) for x, y in pts], fill="white", width=int(S * 0.066), joint="curve")
    return im.resize((size, size), Image.LANCZOS)


def chip(d, xy, text, bg, fg=(10, 12, 16), f=None):
    f = f or font("ExtraBold", 32)
    x, y = xy
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + tw + 44, y + 58], radius=29, fill=bg)
    d.text((x + 22, y + 10), text, font=f, fill=fg)
    return x + tw + 44


def brand(img, xy, size=40, color=TXT):
    d = ImageDraw.Draw(img)
    x, y = xy
    img.alpha_composite(logo(size + 14), (int(x), int(y - 7)))
    f = font("ExtraBold", size)
    d.text((x + size + 28, y - 4), "Вело", font=f, fill=color)
    d.text((x + size + 28 + d.textlength("Вело", font=f), y - 4), "Пульс", font=f, fill=ORANGE)


def brand_right(img, y, size=36):
    d = ImageDraw.Draw(img)
    f = font("ExtraBold", size)
    w = d.textlength("ВелоПульс", font=f) + size + 28
    brand(img, (SW - 60 - w, y), size)


# ------------------------------------------------------------------ картинки
def fetch_image(url):
    for a in range(4):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": UA})
            if r.status_code == 429:
                time.sleep(5 * (a + 1)); continue
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception as e:  # noqa
            log("  фото:", e)
            time.sleep(3)
    return None


def pretty(img):
    img = ImageEnhance.Contrast(img).enhance(1.06)
    return ImageEnhance.Color(img).enhance(1.08)


# ------------------------------------------------------------------ слайды
def slide_cover(p, pic, n):
    col = hexrgb(p["color"])
    img = pretty(cover_crop(pic, SW, SH)).convert("RGBA")
    img.alpha_composite(gradient(SW, SH, 0, 250, start=0.28))
    img.alpha_composite(gradient(SW, 260, 150, 0, color=(0, 0, 0)), (0, 0))
    d = ImageDraw.Draw(img)
    chip(d, (60, 56), p["rubric_name"].upper(), col)
    brand_right(img, 66, 34)
    f, lines, lh = fit(d, p["title"], "ExtraBold", SW - 120, 420, 96, 56, 1.12)
    hf, hl, hlh = fit(d, p.get("hook", ""), "SemiBold", SW - 120, 150, 40, 30, 1.3)
    y_end = SH - 150
    y = y_end - len(hl) * hlh - 30 - len(lines) * lh
    d.rectangle([60, y - 34, 180, y - 24], fill=col)
    y = draw_lines(d, (60, y), lines, f, lh, TXT)
    draw_lines(d, (60, y + 22), hl, hf, hlh, (222, 226, 235))
    ff = font("ExtraBold", 34)
    t = "ЛИСТАЙ  →"
    d.text((SW - 60 - d.textlength(t, font=ff), SH - 96), t, font=ff, fill=col)
    cf = font("Regular", 21)
    cr = p["images"][0]["credit"]
    d.text((60, SH - 86), cr[:70], font=cf, fill=(190, 196, 208))
    d.text((60, SH - 58), f"1 / {n}", font=font("SemiBold", 24), fill=(190, 196, 208))
    return img


def slide_text(p, s, i, n, pic, bgpic=None):
    col = hexrgb(p["color"])
    img = Image.new("RGBA", (SW, SH), BG + (255,))
    if pic is None and bgpic is not None:  # без своего фото — мягкий размытый фон из обложки
        b = cover_crop(bgpic, SW, SH, 0.3).filter(ImageFilter.GaussianBlur(28))
        img = ImageEnhance.Brightness(b).enhance(0.28).convert("RGBA")
        img.alpha_composite(gradient(SW, SH, 60, 200, start=0.2))
    ph = 560
    if pic is not None:
        fy = [0.35, 0.6, 0.25, 0.5][i % 4]
        top = pretty(cover_crop(pic, SW, ph, fy)).convert("RGBA")
        img.alpha_composite(top, (0, 0))
        img.alpha_composite(gradient(SW, ph, 0, 255, start=0.45), (0, 0))
        img.alpha_composite(gradient(SW, 200, 120, 0, color=(0, 0, 0)), (0, 0))
    else:
        ph = 250
    d = ImageDraw.Draw(img)
    chip(d, (60, 50), p["rubric_name"].upper(), col, f=font("ExtraBold", 26))
    brand_right(img, 58, 30)
    y = ph - 70
    numf = font("ExtraBold", 110)
    d.text((56, y - 40), f"{i:02d}", font=numf, fill=col)
    y += 90
    hf, hl, hlh = fit(d, s["h"], "ExtraBold", SW - 120, 170, 70, 46, 1.1)
    y = draw_lines(d, (60, y), hl, hf, hlh, TXT) + 22
    tf, tl, tlh = fit(d, s["t"], "SemiBold", SW - 120, SH - y - 150, 56 if pic is None else 50, 32, 1.36)
    draw_lines(d, (60, y), tl, tf, tlh, (226, 230, 238))
    # прогресс
    yb = SH - 82
    for k in range(n):
        x = 60 + k * 46
        d.rounded_rectangle([x, yb, x + 34, yb + 10], radius=5, fill=col if k == i else (60, 66, 80))
    pf = font("SemiBold", 26)
    t = f"{i + 1} / {n}"
    d.text((SW - 60 - d.textlength(t, font=pf), yb - 12), t, font=pf, fill=MUT)
    return img


def slide_end(p, pic, n):
    col = hexrgb(p["color"])
    bg = cover_crop(pic, SW, SH).filter(ImageFilter.GaussianBlur(30))
    bg = ImageEnhance.Brightness(bg).enhance(0.32).convert("RGBA")
    img = bg
    d = ImageDraw.Draw(img)
    cx = SW // 2
    img.alpha_composite(logo(190), (cx - 95, 130))

    def center(t, y, f, fill):
        d.text((cx - d.textlength(t, font=f) / 2, y), t, font=f, fill=fill)
    f = font("ExtraBold", 104)
    w1, w2 = d.textlength("Вело", font=f), d.textlength("Пульс", font=f)
    x0 = cx - (w1 + w2) / 2
    d.text((x0, 360), "Вело", font=f, fill=TXT)
    d.text((x0 + w1, 360), "Пульс", font=f, fill=ORANGE)
    center("вело-контент каждый день", 500, font("SemiBold", 44), (220, 224, 232))
    bf = font("ExtraBold", 42)
    lines = ["Сохрани, чтобы не потерять", "и отправь другу-велосипедисту"]
    d.rounded_rectangle([90, 610, SW - 90, 790], radius=36, fill=col)
    center(lines[0], 640, bf, (12, 14, 20))
    center(lines[1], 702, bf, (12, 14, 20))
    center(SITE_SHORT, 850, font("SemiBold", 34), TXT)
    y = 950
    sf = font("SemiBold", 26)
    for s in p["sources"][:2]:
        for l in wrap(d, "Источник: " + s["name"], sf, SW - 180)[:2]:
            center(l, y, sf, (200, 206, 218)); y += 36
    y += 14
    cf = font("Regular", 22)
    for im in p["images"][:3]:
        for l in wrap(d, im["credit"], cf, SW - 180)[:2]:
            center(l, y, cf, (170, 178, 194)); y += 30
    t = f"{n} / {n}"
    d.text((SW - 60 - d.textlength(t, font=font("SemiBold", 26)), SH - 94), t, font=font("SemiBold", 26), fill=MUT)
    return img


# ------------------------------------------------------------------ звук
async def _tts(text, mp3, voice):
    import edge_tts
    words, buf = [], bytearray()
    comm = edge_tts.Communicate(text, voice, rate="+6%", boundary="WordBoundary")
    async for ch in comm.stream():
        if ch["type"] == "audio":
            buf.extend(ch["data"])
        elif ch["type"] == "WordBoundary":
            words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    if len(buf) < 5000:
        raise RuntimeError("пустой ответ edge-tts")
    Path(mp3).write_bytes(bytes(buf))
    return words


def tts(text, mp3, voice):
    for a in range(4):
        try:
            return asyncio.run(_tts(text, mp3, voice))
        except Exception as e:  # noqa
            log("  edge-tts:", e)
            time.sleep(4 * (a + 1))
    from gtts import gTTS  # запасной вариант
    gTTS(text, lang="ru").save(str(mp3))
    return []


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def chunks_from_words(words, text):
    tokens, ti, res, cur, start = text.split(), 0, [], [], None
    for (a, b, w) in words:
        tok = w
        for j in range(ti, min(ti + 4, len(tokens))):
            if re.sub(r"\W", "", tokens[j]).lower().startswith(re.sub(r"\W", "", w).lower()[:3] or "§"):
                tok, ti = tokens[j], j + 1
                break
        if start is None:
            start = a
        cur.append(tok)
        txt = " ".join(cur)
        if len(cur) >= 5 or len(txt) > 28 or re.search(r"[.!?,:;—]$", tok):
            res.append([start, b, txt]); cur, start = [], None
    if cur:
        res.append([start, words[-1][1], " ".join(cur)])
    for i in range(len(res) - 1):
        res[i][1] = max(res[i][1], min(res[i + 1][0], res[i][1] + 0.4))
    return res


def chunks_prop(text, dur):
    parts, cur = [], []
    for t in text.split():
        cur.append(t)
        if len(cur) >= 4 or len(" ".join(cur)) > 26 or re.search(r"[.!?,:;]$", t):
            parts.append(" ".join(cur)); cur = []
    if cur:
        parts.append(" ".join(cur))
    tot = sum(len(p) + 3 for p in parts)
    t, res = 0.0, []
    for p in parts:
        d = dur * (len(p) + 3) / tot
        res.append([t, t + d, p]); t += d
    return res


def subtitle_png(text, path, col):
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    f = font("ExtraBold", 62)
    lines = wrap(tmp, text, f, VW - 160)
    if len(lines) > 2:
        f = font("ExtraBold", 52); lines = wrap(tmp, text, f, VW - 140)[:3]
    lh = int(f.size * 1.22)
    bw = max(tmp.textlength(l, font=f) for l in lines) + 70
    bh = lh * len(lines) + 40
    im = Image.new("RGBA", (VW, int(bh) + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([(VW - bw) / 2, 0, (VW + bw) / 2, bh], radius=26, fill=(8, 10, 16, 215))
    d.rounded_rectangle([(VW - bw) / 2, bh - 8, (VW + bw) / 2, bh], radius=4, fill=col + (255,))
    y = 18
    for l in lines:
        d.text(((VW - d.textlength(l, font=f)) / 2, y), l, font=f, fill="white", stroke_width=2, stroke_fill=(0, 0, 0))
        y += lh
    im.save(path)
    return im.height


def video_frame(slide, bgpic, p):
    bg = cover_crop(bgpic, VW, VH).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.35).convert("RGBA")
    sh = Image.new("RGBA", (SW + 40, SH + 40), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([20, 20, SW + 20, SH + 20], radius=10, fill=(0, 0, 0, 160))
    bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)), (-20, 150))
    bg.alpha_composite(slide.convert("RGBA"), (0, 170))
    d = ImageDraw.Draw(bg)
    brand(bg, (60, 62), 40)
    ef = font("SemiBold", 30)
    d.text((VW - 60 - d.textlength(p["rubric_name"], font=ef), 66), p["rubric_name"], font=ef, fill=hexrgb(p["color"]))
    return bg


def build_video(p, slides, bgpic, audio, words, out, work):
    col = hexrgb(p["color"])
    adur = duration(audio)
    tempo = 1.0
    if adur + LEAD + 1.5 > MAX_LEN:
        tempo = min((adur + LEAD + 1.5) / MAX_LEN, 1.25)
    spoken = adur / tempo
    total = min(LEAD + spoken + 0.8 + END * 0.7, 59.5)
    chunks = chunks_from_words(words, p["narration"]) if words else chunks_prop(p["narration"], adur)
    n = len(slides)
    content = total - END + (n - 1) * TRANS
    w = [1.3] + [0.8 + len(s["t"]) / 200 for s in p["slides"]][: n - 2]
    durs = [content * x / sum(w) for x in w] + [END + TRANS]
    inputs, filt = [], []
    for i, (sl, du) in enumerate(zip(slides, durs)):
        fp = work / f"f{i}.png"
        video_frame(sl, bgpic, p).convert("RGB").save(fp)
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{du:.3f}", "-i", str(fp)]
        z = "1+0.04*t/%.3f" % du
        filt.append(f"[{i}:v]scale={VW}:{VH},setsar=1,format=yuv420p,fps={FPS}[v{i}]")
    prev, acc = "v0", 0.0
    tr = ["fade", "slideleft", "smoothleft", "fade", "slideleft", "fadeblack"]
    for i in range(1, n):
        acc += durs[i - 1] - TRANS
        filt.append(f"[{prev}][v{i}]xfade=transition={tr[(i - 1) % len(tr)]}:duration={TRANS}:offset={acc:.3f}[x{i}]")
        prev = f"x{i}"
    si = n + 1
    sub_in = []
    for k, (a, b, txt) in enumerate(chunks):
        sp = work / f"sub{k}.png"
        h = subtitle_png(txt, sp, col)
        sub_in += ["-i", str(sp)]
        ta, tb = LEAD + a / tempo, LEAD + b / tempo
        filt.append(f"[{prev}][{si + k}:v]overlay=0:{1660 - h // 2}:enable='between(t,{ta:.2f},{tb:.2f})'[s{k}]")
        prev = f"s{k}"
    at = f"atempo={tempo:.4f}," if tempo != 1.0 else ""
    filt.append(f"[{n}:a]{at}adelay={int(LEAD * 1000)}|{int(LEAD * 1000)},apad[aout]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-i", str(audio), *sub_in,
           "-filter_complex", ";".join(filt), "-map", f"[{prev}]", "-map", "[aout]", "-t", f"{total:.2f}", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-1500:])
    video_frame(slides[0], bgpic, p).convert("RGB").resize((540, 960)).save(out.with_suffix(".jpg"), quality=84)
    return total, bool(words)


# ------------------------------------------------------------------ тексты постов
def make_post(p):
    tags = " ".join(p["hashtags"])
    src = "\n".join(f"🔗 {s['name']}: {s['url']}" for s in p["sources"][:2])
    cred = "\n".join(i["credit"] for i in p["images"])
    link = f"{SITE}#/p/{p['slug']}"
    caption = f"{p['emoji']} {p['title']}\n\n{p['caption']}\n\n{tags}"
    if len(caption) > 2150:
        caption = caption[:2000].rsplit(" ", 1)[0] + "…\n\n" + tags
    yt_title = (p["title"][:85] + " #shorts")[:100]
    yt_desc = (f"{p.get('hook', '')}\n\n{p['caption']}\n\n{src}\n📷 {cred}\n\n"
               f"🚲 ВелоПульс — вело-контент каждый день: {link}\n\n{tags} #shorts")[:4900]
    tiktok = f"{p['title']} {p['emoji']}\n{p.get('hook', '')}\n\n{tags} #велосипед #рекомендации"[:2150]
    return {"caption": caption, "full": f"{caption}\n\n{src}\n📷 {cred}", "youtube_title": yt_title,
            "youtube_description": yt_desc, "tiktok": tiktok}


# ------------------------------------------------------------------ релиз
def gh(*a, check=True):
    return subprocess.run(["gh", *a], capture_output=True, text=True, check=check)


def upload_release(date, files):
    tag = f"day-{date}"
    if gh("release", "view", tag, "-R", REPO, check=False).returncode != 0:
        gh("release", "create", tag, "-R", REPO, "--title", f"ВелоПульс — {date}",
           "--notes", f"Слайды, аудио и вертикальные видео за {date}: {SITE}#/day/{date}", "--latest=false")
    for i in range(0, len(files), 8):
        for a in range(3):
            if gh("release", "upload", tag, "-R", REPO, "--clobber", *[str(f) for f in files[i:i + 8]], check=False).returncode == 0:
                break
            time.sleep(10)
    return f"https://github.com/{REPO}/releases/download/{tag}/"


def main():
    index = load_json(DATA / "index.json", {"days": []})
    date = os.environ.get("MEDIA_DATE") or index["days"][0]["date"]
    dp = DATA / f"{date}.json"
    day = load_json(dp, None)
    force = os.environ.get("MEDIA_FORCE") == "1"
    limit = int(os.environ.get("MEDIA_LIMIT") or 0)
    MEDIA.mkdir(exist_ok=True)
    made, stats = [], {"ok": 0, "fail": 0}
    for k, p in enumerate(day["posts"][:limit] if limit else day["posts"]):
        if p.get("files") and not force and (MEDIA / p["files"]["video"]).exists():
            continue
        log(f"медиа: {p['title']}")
        s = p["slug"]
        pics = [x for x in (fetch_image(i["url"]) for i in p["images"]) if x is not None]
        if not pics:
            log("  нет картинок"); stats["fail"] += 1; continue
        n = len(p["slides"]) + 2
        slides = [slide_cover(p, pics[0], n)]
        for i, sl in enumerate(p["slides"], 1):
            pic = pics[i % len(pics)] if len(pics) > 1 else (pics[0] if i % 2 else None)
            slides.append(slide_text(p, sl, i, n, pic, pics[0]))
        slides.append(slide_end(p, pics[0], n))
        names = []
        for i, im in enumerate(slides, 1):
            nm = f"{s}-{i}.png"
            im.convert("RGB").save(MEDIA / nm, optimize=True)
            im.convert("RGB").resize((540, 675), Image.LANCZOS).save(MEDIA / nm.replace(".png", ".jpg"), quality=82)
            names.append(nm)
        zp = MEDIA / f"{s}-slides.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
            for nm in names:
                z.write(MEDIA / nm, nm)
            z.writestr("текст-поста.txt", make_post(p)["full"])
        mp3 = MEDIA / f"{s}.mp3"
        voice = VOICES[k % len(VOICES)]
        words = tts(p["narration"], mp3, voice)
        mp4 = MEDIA / f"{s}.mp4"
        work = MEDIA / "_work"
        work.mkdir(exist_ok=True)
        try:
            total, synced = build_video(p, slides, pics[0], mp3, words, mp4, work)
        except Exception as e:  # noqa
            log("  видео:", e); stats["fail"] += 1; total, synced = 0, False
        for f in work.iterdir():
            f.unlink()
        p["voice"] = voice
        p["files"] = {"slides": names, "previews": [nm.replace(".png", ".jpg") for nm in names], "zip": zp.name, "audio": mp3.name, "audio_bytes": mp3.stat().st_size,
                      "audio_duration": round(duration(mp3), 1)}
        if mp4.exists():
            p["files"].update(video=mp4.name, poster=mp4.with_suffix(".jpg").name, video_duration=round(total, 1),
                              video_mb=round(mp4.stat().st_size / 1e6, 1), synced_subs=synced)
            made += [mp4, mp4.with_suffix(".jpg")]
        made += [MEDIA / nm for nm in names] + [MEDIA / nm.replace(".png", ".jpg") for nm in names] + [zp, mp3]
        p["post"] = make_post(p)
        stats["ok"] += 1
        log(f"  готово: аудио {p['files']['audio_duration']}s, видео {total:.1f}s")
    if made and os.environ.get("NO_RELEASE") != "1":
        base = upload_release(date, made)
        for p in day["posts"]:
            if p.get("files"):
                p["release"] = base
                p["files"]["audio_url"] = base + p["files"]["audio"]
    save_json(dp, day)
    # RSS
    import importlib
    gen = importlib.import_module("generate")
    posts = []
    for d in index["days"][:20]:
        posts += load_json(DATA / f"{d['date']}.json", {"posts": []})["posts"]
    gen.build_feed(index, posts)
    log("медиа:", stats)


if __name__ == "__main__":
    main()
