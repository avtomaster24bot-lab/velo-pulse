#!/usr/bin/env python3
"""Рассылка подборки дня в Telegram-канал.

Нужно: TELEGRAM_BOT_TOKEN (секрет репозитория). Канал — TELEGRAM_CHAT_ID или "telegram_chat" в topics.json
(по умолчанию @velopark_kz). Бот должен быть администратором канала с правом публикации.
Для каждого поста (режим video, по умолчанию): вертикальное видео из слайдов (мужской голос + фоновая музыка)
с подписью. TELEGRAM_MODE=album — по-старому: альбом слайдов + аудио.
Уже отправленные посты запоминаются в data/telegram.json, повторно не уходят.
"""
import html
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CFG, DATA, ROOT, SITE, load_json, save_json  # noqa

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHATS = [c.strip() for c in (os.environ.get("TELEGRAM_CHAT_ID") or CFG.get("telegram_chat", "")).split(",") if c.strip()]
MODE = (os.environ.get("TELEGRAM_MODE") or CFG.get("telegram_mode") or "video").strip()  # video | album
MEDIA = ROOT / "media"
e = html.escape

if not TOKEN or not CHATS:
    print("Telegram не настроен — пропускаю")
    sys.exit(0)
API = f"https://api.telegram.org/bot{TOKEN}"


def call(method, **kw):
    for _ in range(4):
        try:
            r = requests.post(f"{API}/{method}", timeout=300, **kw)
        except Exception as ex:  # noqa
            print(method, "ошибка сети", type(ex).__name__); time.sleep(5); continue
        if r.status_code == 429:
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1); continue
        if not r.ok:
            print(method, r.status_code, r.text[:300])
        return r
    return None


def src(p, name):
    f = MEDIA / name
    return ("file", f) if f.exists() else ("url", p.get("release", "") + name)


def caption(p):
    link = f"{SITE}#/p/{p['slug']}"
    srcs = " · ".join(f"<a href=\"{e(s['url'])}\">{e(s['name'][:60])}</a>" for s in p["sources"][:2])
    tags = " ".join(p["hashtags"][:6])
    head = f"{p['emoji']} <b>{e(p['title'])}</b>\n<i>{e(p.get('hook', ''))}</i>\n\n"
    mus = f"\n🎵 Музыка: «{e(p['music']['title'])}», Kevin MacLeod (CC BY 4.0)" if p.get("music") else ""
    tail = f"\n\n📎 {srcs}\n🌐 <a href=\"{link}\">Пост на сайте</a>{mus}\n{e(tags)}"
    body = e(p["caption"])
    room = 1024 - len(head) - len(tail) - 5
    if len(body) > room:  # лимит подписи 1024 символа (с разметкой)
        body = body[:room].rsplit(" ", 1)[0] + "…"
    return head + body + tail


def send_video(chat, p):
    f = p["files"]
    data = {"chat_id": chat, "caption": caption(p), "parse_mode": "HTML", "supports_streaming": "true",
            "width": 1080, "height": 1920, "duration": int(f.get("video_duration") or 0)}
    kind, v = src(p, f["video"])
    if kind == "file":
        files = {"video": (v.name, open(v, "rb"), "video/mp4")}
        pk, pv = src(p, f.get("poster", ""))
        if f.get("poster") and pk == "file":
            files["thumbnail"] = (pv.name, open(pv, "rb"), "image/jpeg")
        try:
            r = call("sendVideo", data=data, files=files)
        finally:
            for x in files.values():
                x[1].close()
    else:
        r = call("sendVideo", data={**data, "video": v})
    return r is not None and r.ok


def send_post(chat, p):
    if MODE == "video" and p["files"].get("video"):
        return send_video(chat, p)
    files, media, opened = {}, [], []
    for i, nm in enumerate(p["files"]["slides"][:10]):
        kind, v = src(p, nm)
        item = {"type": "photo"}
        if kind == "file":
            fh = open(v, "rb"); opened.append(fh)
            files[f"f{i}"] = (nm, fh, "image/png"); item["media"] = f"attach://f{i}"
        else:
            item["media"] = v
        if i == 0:
            item.update(caption=caption(p), parse_mode="HTML")
        media.append(item)
    r = call("sendMediaGroup", data={"chat_id": chat, "media": json.dumps(media)}, files=files or None)
    for fh in opened:
        fh.close()
    ok = r is not None and r.ok
    kind, v = src(p, p["files"]["audio"])
    data = {"chat_id": chat, "title": p["title"][:60], "performer": "ВелоПульс",
            "caption": f"🎧 {e(p['title'])} — аудио-рассказ", "parse_mode": "HTML",
            "duration": int(p["files"].get("audio_duration") or 0)}
    if kind == "file":
        with open(v, "rb") as fh:
            r2 = call("sendAudio", data=data, files={"audio": (f"{p['slug']}.mp3", fh, "audio/mpeg")})
    else:
        r2 = call("sendAudio", data={**data, "audio": v})
    ok = ok and r2 is not None and r2.ok
    return ok


def main():
    index = load_json(DATA / "index.json", {"days": []})
    date = os.environ.get("TELEGRAM_DATE") or index["days"][0]["date"]
    day = load_json(DATA / f"{date}.json", {"posts": []})
    sent = load_json(DATA / "telegram.json", {})
    for chat in CHATS:
        done = set(sent.get(chat, {}).get(date, []))
        todo = [p for p in day["posts"] if p.get("files") and p["slug"] not in done]
        if not todo:
            print(f"{chat}: всё за {date} уже отправлено"); continue
        if not done:
            rubs = "\n".join(f"{p['emoji']} {e(p['title'])}" for p in todo)
            call("sendMessage", data={"chat_id": chat, "parse_mode": "HTML", "disable_web_page_preview": "true",
                                      "text": f"🚲 <b>ВелоПульс — {date}</b>\nСегодня в подборке {len(todo)} постов:\n\n{rubs}\n\n"
                                              f"🎬 Видео, слайды и тексты: {SITE}#/day/{date}"})
        okc = 0
        for p in todo:
            if send_post(chat, p):
                sent.setdefault(chat, {}).setdefault(date, []).append(p["slug"]); okc += 1
                save_json(DATA / "telegram.json", sent)
            time.sleep(3)
        print(f"{chat}: отправлено {okc} из {len(todo)}")


if __name__ == "__main__":
    main()
