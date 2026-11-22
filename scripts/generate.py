#!/usr/bin/env python3
"""ВелоПульс: ежедневная подборка вело-постов.

Для каждой рубрики дня берёт проверенный источник (новости из RSS, Википедия, справочник «Вело-вселенная»,
каталог маршрутов Velopark), пишет пост на русском только по фактам источника (ИИ + проверка фактов вторым проходом),
подбирает подходящие фото со свободной лицензией на Wikimedia Commons и сохраняет data/ДАТА.json.
Картинки, слайды, аудио и видео делает scripts/make_media.py.
"""
import datetime as dt
import email.utils
import hashlib
import json
import os
import random
import re
import xml.etree.ElementTree as ET

from common import (CFG, DATA, ROOT, SITE, TODAY, TZ, S, commons_info, commons_search, credit, llm_json, load_json, log,
                    save_json, slugify, strip_tags, usable, wiki_category, wiki_page)

FORCE = os.environ.get("FORCE") == "1"
ONLY = [x for x in os.environ.get("ONLY_RUBRICS", "").split(",") if x]
RUB = CFG["rubrics"]
BANK = json.loads((ROOT / "bank/bank.json").read_text(encoding="utf-8"))
USED = load_json(DATA / "used.json", {"ids": [], "links": [], "titles": []})
day_no = dt.date.fromisoformat(TODAY).toordinal()
RNG = random.Random(day_no)

SYSTEM = ("Ты — главный редактор популярного русскоязычного вело-медиа «ВелоПульс» (Казахстан, Россия, СНГ). "
          "Пишешь живо, образно, но строго по фактам: никаких выдуманных цифр, дат, имён, рекордов и цитат. "
          "Грамотный русский язык, без канцелярита; никаких английских слов, если есть русское (не «extreme», а «экстремальная»). Без бессмысленных метафор. Отвечай только валидным JSON.")

POST_PROMPT = """Рубрика: «{rubric}». Тема: «{title}».
{extra}
ИСТОЧНИК ({src_name}). Используй ТОЛЬКО факты из этого текста. Если в источнике нет цифры или подробности — не пиши её.
Источник может быть на английском — пиши по-русски, имена и названия передавай общепринятым русским написанием.
<<<
{text}
>>>

Сделай мега-интересный пост для Instagram-карусели, Telegram и коротких видео. Верни JSON:
{{
 "title": "цепляющий, но честный заголовок, 30–65 символов",
 "hook": "подзаголовок-интрига, одна фраза до 110 символов",
 "slides": [
   {{"h": "заголовок слайда до 30 символов", "t": "текст слайда 110–210 символов, конкретика из источника"}}
 ],
 "narration": "текст для озвучки голосом: 95–115 слов (40–50 секунд), не больше 115 слов. Начни с яркого крючка, расскажи самое интересное и полезное, закончи фразой «Подписывайтесь на ВелоПульс!». Без эмодзи, ссылок, скобок и списков. Числа пиши так, чтобы их легко прочитать вслух.",
 "caption": "текст поста 600–1000 символов: короткие абзацы, 2–4 уместных эмодзи, конкретные факты, в конце вопрос к подписчикам",
 "hashtags": ["6–8 хэштегов на русском, первым #ВелоПульс"],
 "image_queries": ["3 коротких запроса НА АНГЛИЙСКОМ для поиска фото по теме на Wikimedia Commons, конкретно: предмет, человек, место"],
 "keywords": ["3–6 английских слов — что обязательно должно быть на фото"]
}}
В "slides" ровно 4 слайда: 1) суть, 2) самое удивительное/важное, 3) детали или как это работает/как сделать, 4) практический вывод или совет."""

CHECK_PROMPT = """Проверь пост на соответствие источнику. Источник:
<<<
{text}
>>>
Пост (JSON):
{post}

Ты — строгий редактор и фактчекер. Найди:
1) утверждения, которых НЕТ в источнике или которые ему противоречат (цифры, даты, имена, рекорды, «самый», выдуманные подробности);
2) ошибки и корявости русского языка, бессмысленные метафоры, английские слова вместо русских.
Исправь их: удали или замени на факты из источника, сделай текст гладким и живым. Сохрани структуру и длину.
Верни JSON с теми же ключами, что у поста, плюс список замечаний:
{{"problems": ["кратко, что исправлено"], "title": "...", "hook": "...", "slides": [{{"h": "...", "t": "..."}}], "narration": "...", "caption": "..."}}"""

IMG_PROMPT = """Тема поста: «{title}». {hook}
Ключевые слова: {kw}.
Кандидаты — фото с Wikimedia Commons (номер: имя файла | описание | категории):
{cands}

Выбери фото, которые ДЕЙСТВИТЕЛЬНО показывают тему поста (тот самый предмет, человека, гонку, место или действие).
Не подходят: другие люди/места, логотипы, схемы, карты, случайные велосипеды не по теме, музейные таблички.
Верни JSON: {{"ok": [номера подходящих, от лучшего к худшему, максимум 4]}}"""


def post_ok(d):
    return (isinstance(d, dict) and d.get("title") and d.get("narration") and isinstance(d.get("slides"), list)
            and len(d["slides"]) >= 3 and d.get("caption") and all(isinstance(s, dict) and s.get("t") for s in d["slides"]))


# ------------------------------------------------------------------ источники
def news_items(rubric):
    skip = [w.lower() for w in CFG.get("news_skip", [])]
    out = []
    now = dt.datetime.now(dt.timezone.utc)
    for name, url, rub in CFG["news_feeds"]:
        if rub != rubric:
            continue
        try:
            r = S.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0 VeloPulse"})
            root = ET.fromstring(r.content)
        except Exception as e:  # noqa
            log("rss", name, e)
            continue
        for it in root.iter("item"):
            title = strip_tags(it.findtext("title") or "")
            link = (it.findtext("link") or "").strip()
            desc = strip_tags(it.findtext("description") or "")[:600]
            try:
                pub = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "")
            except Exception:  # noqa
                pub = None
            if not title or not link or link in USED["links"]:
                continue
            if pub and (now - pub).total_seconds() > 3 * 86400:
                continue
            low = (title + " " + link).lower()
            if any(w in low for w in skip):
                continue
            out.append({"source": name, "title": title, "link": link, "desc": desc,
                        "pub": pub.isoformat() if pub else ""})
    return out


def article_text(url):
    try:
        r = S.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) VeloPulse"})
        h = r.text
    except Exception as e:  # noqa
        log("article", e)
        return ""
    h = re.sub(r"(?is)<(script|style|aside|nav|footer|figure)[^>]*>.*?</\1>", " ", h)
    paras = [strip_tags(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", h)]
    paras = [re.sub(r"\s+", " ", p) for p in paras if len(p) > 70 and not re.search(r"(?i)(cookie|subscribe|sign up|newsletter|affiliate|commission|©)", p)]
    return "\n".join(paras)[:6000]


def pick_news(rubric, n_want=1):
    items = news_items(rubric)
    log(f"  {rubric}: свежих новостей {len(items)}")
    if not items:
        return []
    items = items[:40]
    lst = "\n".join(f"{i}. [{x['source']}] {x['title']} — {x['desc'][:160]}" for i, x in enumerate(items))
    j = llm_json(f"""Вот свежие заголовки вело-медиа:\n{lst}\n\nВыбери 4 новости, которые будут интереснее всего широкой
русскоязычной аудитории любителей велосипеда (громкие события, звёзды, необычные истории, полезные новинки).
Не бери рекламу, скидки, обзоры-подборки «лучших», платный контент. Верни JSON: {{"pick": [номера от лучшего к худшему]}}""",
                 check=lambda d: isinstance(d.get("pick"), list), kind="light")
    order = [int(i) for i in (j or {}).get("pick", []) if str(i).isdigit() and int(i) < len(items)] or list(range(len(items)))
    return [items[i] for i in order][: max(4, n_want)]


def bank_pick(rubric):
    rubs = {"hacks": ["hacks"], "facts": ["facts"], "history": ["history"], "tech": ["tech"], "service": ["service"], "routes": ["routes"]}[rubric]
    cands = [b for b in BANK if b["rubric"] in rubs and b["id"] not in USED["ids"] and len(b["text"]) >= 280]
    if not cands:  # банк исчерпан — начинаем новый круг
        cands = [b for b in BANK if b["rubric"] in rubs and len(b["text"]) >= 280]
    if rubric == "routes":  # чаще Казахстан и Центральная Азия
        kz = [b for b in cands if b.get("kz") or "Кыргыз" in b["text"]]
        if kz and RNG.random() < 0.5:
            cands = kz
    # предпочтение темам с фото и длинным текстом
    cands.sort(key=lambda b: (bool(b["photos"]), min(len(b["text"]), 2500) + RNG.random() * 1500), reverse=True)
    return cands[:6]


def wiki_candidates(rubric):
    out = []
    if rubric == "stars":
        pages = [tuple(x) for x in CFG["star_pages"]]
        for lang, cat, w in CFG["star_categories"]:
            for t in wiki_category(lang, cat):
                pages += [(lang, t)] * w
        RNG.shuffle(pages)
    else:
        pages = [tuple(x) for x in CFG["wiki_topics"].get(rubric, [])]
        RNG.shuffle(pages)
    seen = set()
    for lang, t in pages:
        key = f"wiki:{lang}:{t}"
        if key in USED["ids"] or key in seen:
            continue
        seen.add(key)
        out.append((lang, t))
        if len(out) >= 8:
            break
    return out


# ------------------------------------------------------------------ картинки
def score_kw(info, kws):
    hay = (info["file"] + " " + info["desc"] + " " + " ".join(info["cats"])).lower()
    return sum(1 for k in kws if k and k.lower() in hay)


def choose_images(post, trusted, wiki_files, queries, kws, need=3):
    """trusted — уже проверенные вручную фото (кураторские), wiki_files — фото из статьи-источника."""
    chosen = []
    if trusted:
        chosen += [i for i in commons_info([t["file"] for t in trusted]) if not i["nonfree"]]
    pool, seen = [], {c["file"] for c in chosen}
    if len(chosen) < need:
        if wiki_files:
            for i in commons_info(wiki_files[:30]):
                if usable(i, 640) and i["file"] not in seen:
                    pool.append(i); seen.add(i["file"])
        for q in queries[:3]:
            for i in commons_search(q, 15):
                if usable(i) and i["file"] not in seen:
                    pool.append(i); seen.add(i["file"])
    if pool:
        pool.sort(key=lambda i: -score_kw(i, kws + post["title"].split()))
        pool = pool[:24]
        cands = "\n".join(f"{n}. {i['file']} | {i['desc'][:150]} | {', '.join(i['cats'][:6])}" for n, i in enumerate(pool))
        j = llm_json(IMG_PROMPT.format(title=post["title"], hook=post.get("hook", ""), kw=", ".join(kws), cands=cands),
                     temperature=0.1, check=lambda d: isinstance(d.get("ok"), list), kind="light")
        ok = [int(x) for x in (j or {}).get("ok", []) if str(x).isdigit() and int(x) < len(pool)]
        for n in ok:
            if len(chosen) >= need:
                break
            chosen.append(pool[n])
    return chosen[:need]


# ------------------------------------------------------------------ пост
def write_post(rubric_name, title, text, src_name, extra=""):
    j = llm_json(POST_PROMPT.format(rubric=rubric_name, title=title, text=text[:6500], src_name=src_name, extra=extra),
                 system=SYSTEM, check=post_ok)
    if not j:
        return None
    j["slides"] = j["slides"][:5]
    chk = llm_json(CHECK_PROMPT.format(text=text[:6500], post=json.dumps({k: j[k] for k in ("title", "hook", "slides", "narration", "caption")}, ensure_ascii=False)),
                   system=SYSTEM, temperature=0.2, check=lambda d: post_ok(d.get("post") if isinstance(d.get("post"), dict) else d))
    if chk:
        fixed = chk["post"] if isinstance(chk.get("post"), dict) else chk
        probs = [p for p in chk.get("problems", []) if p]
        log(f"  проверка фактов: замечаний {len(probs)}", "; ".join(map(str, probs))[:400])
        for k in ("title", "hook", "slides", "narration", "caption"):
            if fixed.get(k):
                j[k] = fixed[k]
        j["fact_check"] = probs
    else:
        j["fact_check"] = None
    tags = [t if t.startswith("#") else "#" + t for t in (j.get("hashtags") or [])]
    tags = ["#ВелоПульс"] + [re.sub(r"[^\w#]", "", t) for t in tags if t.lower() != "#велопульс"]
    j["hashtags"] = list(dict.fromkeys(tags))[:9]
    j["slides"] = [{"h": str(s.get("h", "")).strip(), "t": str(s.get("t", "")).strip()} for s in j["slides"]][:5]
    return j


def make_item(rubric, title, text, src_name, sources, trusted=(), wiki_files=(), uid="", extra="", meta=None):
    r = RUB[rubric]
    log(f"• [{r['name']}] {title}")
    post = write_post(r["name"], title, text, src_name, extra)
    if not post:
        log("  ИИ не ответил")
        return None
    kws = [k for k in post.get("keywords", []) if isinstance(k, str)]
    qs = [q for q in post.get("image_queries", []) if isinstance(q, str)]
    imgs = choose_images(post, list(trusted), list(wiki_files), qs, kws)
    if not imgs:
        log("  нет подходящих фото — пропускаю тему")
        return None
    slug = slugify(post["title"])
    return {
        "id": uid, "date": TODAY, "slug": f"{TODAY}-{slug}", "rubric": rubric, "rubric_name": r["name"], "emoji": r["emoji"],
        "color": r["color"], "topic": title, "title": post["title"].strip(), "hook": post.get("hook", "").strip(),
        "slides": post["slides"], "narration": post["narration"].strip(), "caption": post["caption"].strip(),
        "hashtags": post["hashtags"], "fact_check": post.get("fact_check"),
        "images": [{"file": i["file"], "url": i["url"], "w": i["w"], "h": i["h"], "author": i["author"], "license": i["license"],
                    "license_url": i["license_url"], "source": i["source"], "credit": credit(i)} for i in imgs],
        "sources": [{"name": n, "url": u} for n, u in sources],
        **(meta or {}),
    }


def produce(rubric):
    """Пытается сделать пост рубрики; при неудаче берёт следующий кандидат."""
    if rubric in ("news", "gear"):
        for it in pick_news(rubric):
            body = article_text(it["link"]) or it["desc"]
            if len(body) < 400:
                body = (it["desc"] + "\n" + body).strip()
            if len(body) < 250:
                continue
            pub = it["pub"][:10]
            p = make_item(rubric, it["title"], f"{it['title']}\n{body}", f"{it['source']}, {pub}",
                          [(f"{it['source']}: {it['title']}", it["link"])], uid=it["link"],
                          extra=f"Это новость от {pub}. В тексте укажи, что это по данным {it['source']}. Не выдавай её за собственное расследование.",
                          meta={"news_date": pub})
            if p:
                USED["links"].append(it["link"])
                return p
        return None
    if rubric in ("stars", "health", "safety") or (rubric == "hacks" and RNG.random() < 0.5):
        for lang, t in wiki_candidates(rubric):
            w = wiki_page(lang, t)
            if not w or w["len"] < 1500:
                continue
            files = ([w["pageimage"]] if w.get("pageimage") else []) + w["files"]
            src_name = f"Википедия ({'рус.' if lang == 'ru' else 'англ.'}), статья «{w['title']}»"
            extra = "Пиши как практичный совет для велосипедиста: что делать, на что обратить внимание." if rubric in ("health", "safety", "hacks") else \
                    "Расскажи историю ярко: путь к успеху, главные победы, интересные эпизоды — только из источника."
            p = make_item(rubric, w["title"], w["text"], src_name, [(f"Википедия: {w['title']}", w["url"])],
                          wiki_files=files, uid=f"wiki:{lang}:{t}", extra=extra)
            if p:
                return p
        if rubric != "hacks":
            return None
    for b in bank_pick(rubric if rubric in ("hacks", "facts", "history", "tech", "service", "routes") else "hacks"):
        src_name = "справочник «Вело-вселенная»" if not b["id"].startswith("route-") else "каталог маршрутов Velopark (с источниками)"
        extra = ""
        if b["id"].startswith("route-"):
            extra = "Это велосипедный маршрут: передай атмосферу, сложность, когда ехать и практические советы."
        elif b["rubric"] in ("service", "hacks"):
            extra = "Это практическое руководство: сделай пошагово и понятно новичку."
        q = [b.get("img_query")] if b.get("img_query") else []
        p = make_item(rubric, b["title"], b["text"], src_name, b["src"], trusted=b["photos"],
                      uid=b["id"], extra=extra)
        if p:
            return p
    return None


def build_feed(index, posts):
    from xml.sax.saxutils import escape as x
    items = []
    for p in posts[:60]:
        link = f"{SITE}#/p/{p['slug']}"
        enc = ""
        if p.get("files", {}).get("audio_url"):
            enc = f'<enclosure url="{x(p["files"]["audio_url"])}" type="audio/mpeg" length="{p["files"].get("audio_bytes", 0)}"/>'
        pub = email.utils.format_datetime(dt.datetime.fromisoformat(p["date"] + "T08:00:00+05:00"))
        items.append(f"<item><title>{x(p['emoji'] + ' ' + p['title'])}</title><link>{x(link)}</link><guid>{x(link)}</guid>"
                     f"<pubDate>{pub}</pubDate><category>{x(p['rubric_name'])}</category>"
                     f"<description>{x(p['caption'])}</description>{enc}</item>")
    (ROOT / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>ВелоПульс — вело-контент каждый день</title><link>{SITE}</link>"
        "<description>Новости велоспорта, техника, маршруты, история и лайфхаки — каждый день с аудио и слайдами.</description>"
        f"<language>ru</language>{''.join(items)}</channel></rss>", encoding="utf-8")


def main():
    DATA.mkdir(exist_ok=True)
    day_path = DATA / f"{TODAY}.json"
    index = load_json(DATA / "index.json", {"days": []})
    if day_path.exists() and not FORCE and not ONLY:
        log(f"Подборка за {TODAY} уже есть")
        return
    old = load_json(day_path, {"posts": []})["posts"] if ONLY else []
    plan = [opts[day_no % len(opts)] for opts in CFG["daily_plan"]]
    if ONLY:
        plan = ONLY
    posts = []
    for rub in plan:
        try:
            p = produce(rub)
        except Exception as e:  # noqa
            log(f"ошибка в рубрике {rub}: {e}")
            p = None
        if not p:
            continue
        if any(p["slug"] == q["slug"] for q in posts + old):
            p["slug"] += "-" + hashlib.md5(p["id"].encode()).hexdigest()[:4]
        posts.append(p)
        USED["ids"].append(p["id"])
        USED["titles"].append(p["title"])
        save_json(DATA / "used.json", USED)
    if ONLY:
        keep = [q for q in old if q["rubric"] not in ONLY]
        posts = keep + posts
        order = {r: i for i, r in enumerate([o[day_no % len(o)] for o in CFG["daily_plan"]])}
        posts.sort(key=lambda q: order.get(q["rubric"], 99))
    if not posts:
        raise SystemExit("Не удалось сделать ни одного поста")
    save_json(day_path, {"date": TODAY, "posts": posts})
    index["days"] = [d for d in index["days"] if d["date"] != TODAY]
    index["days"].insert(0, {"date": TODAY, "count": len(posts), "titles": [p["title"] for p in posts],
                             "rubrics": [p["rubric"] for p in posts]})
    index["days"].sort(key=lambda d: d["date"], reverse=True)
    index["updated"] = dt.datetime.now(TZ).isoformat(timespec="minutes")
    index["rubrics"] = RUB
    save_json(DATA / "index.json", index)
    from common import LLM_STATS
    log(f"Готово: {len(posts)} постов за {TODAY}; ИИ: {LLM_STATS}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"## ВелоПульс {TODAY}\n\n" + "\n".join(f"- {p['emoji']} **{p['title']}** ({p['rubric_name']})" for p in posts) + "\n")


if __name__ == "__main__":
    main()
