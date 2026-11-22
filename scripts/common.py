"""Общие функции ВелоПульс: конфиг, ИИ (Pollinations или свой API), Википедия, Wikimedia Commons."""
import datetime as dt
import html
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CFG = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))
TZ = ZoneInfo("Asia/Almaty")
TODAY = os.environ.get("DIGEST_DATE") or dt.datetime.now(TZ).date().isoformat()
SITE = CFG["site_url"].rstrip("/") + "/"
REPO = os.environ.get("GITHUB_REPOSITORY") or CFG["repo"]
UA = "VeloPulse/1.0 (https://github.com/avtomaster24bot-lab/velo-pulse; daily cycling digest)"
S = requests.Session()
S.headers["User-Agent"] = UA


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def slugify(s):
    tr = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                  ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u",
                   "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
    s = "".join(tr.get(c, c) for c in str(s).lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "post"


# ------------------------------------------------------------------ ИИ
def llm_providers(kind="write"):
    out = []
    gtok = os.environ.get("GITHUB_MODELS_TOKEN", "").strip()
    if gtok:  # GitHub Models: бесплатно в GitHub Actions (permissions: models: read)
        url = "https://models.github.ai/inference/chat/completions"
        models = [CFG.get("gh_model_write", "openai/gpt-4.1")] if kind == "write" else []
        models += [CFG.get("gh_model", "openai/gpt-4.1-mini")]
        for m in models:
            if m not in _exhausted:
                out.append(("github:" + m, url, {"Authorization": f"Bearer {gtok}"}, m))
    url, key = os.environ.get("LLM_API_URL", "").strip(), os.environ.get("LLM_API_KEY", "").strip()
    if url and key:
        u = url.rstrip("/")
        out.append(("custom", u if u.endswith("/chat/completions") else u + "/chat/completions",
                    {"Authorization": f"Bearer {key}"}, os.environ.get("LLM_MODEL") or CFG.get("model", "gpt-4o-mini")))
    if CFG.get("use_free_ai", True):
        out.append(("pollinations", "https://text.pollinations.ai/openai", {}, CFG.get("free_model", "openai")))
    return out


_exhausted = set()
LLM_STATS = {}


def llm_json(prompt, system="Отвечай только валидным JSON.", temperature=0.6, check=None, kind="write"):
    for name, url, headers, model in llm_providers(kind):
        body = {"model": model, "temperature": temperature, "response_format": {"type": "json_object"},
                "max_tokens": 6000,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if name == "pollinations":
            body["reasoning_effort"] = "low"
        for attempt in range(5):
            body["seed"] = random.randint(1, 10**6)
            try:
                r = requests.post(url, json=body, timeout=180,
                                  headers={"Content-Type": "application/json", **headers})
                if r.status_code in (402, 429):
                    m = re.search(r"(\d+)\s*s", r.text)
                    wait = int(r.headers.get("retry-after") or (m.group(1) if m else 20))
                    if name.startswith("github") and wait > 120:
                        log(f"  {name}: дневной лимит исчерпан, переключаюсь")
                        _exhausted.add(model)
                        break
                    wait = min(wait, 90)
                    log(f"  {name}: лимит, жду {wait}s")
                    time.sleep(wait + 2)
                    continue
                if r.status_code != 200:
                    log(f"  {name} {r.status_code}: {r.text[:200]}")
                    time.sleep(6)
                    continue
                content = r.json()["choices"][0]["message"]["content"] or ""
                LLM_STATS[name] = LLM_STATS.get(name, 0) + 1
                m = re.search(r"\{.*\}", content, re.S)
                raw = m.group(0) if m else content
                try:
                    data = json.loads(raw)
                except Exception:
                    from json_repair import repair_json
                    data = json.loads(repair_json(raw))
                if check and not check(data):
                    raise ValueError("неполный JSON")
                return data
            except Exception as e:  # noqa
                log(f"  {name}: {e}")
                time.sleep(5)
    return None


# ------------------------------------------------------------------ Википедия
def wiki_get(lang, **params):
    params.update(format="json", formatversion=2)
    for _ in range(3):
        try:
            r = S.get(f"https://{lang}.wikipedia.org/w/api.php", params=params, timeout=30)
            if r.ok:
                return r.json()
        except Exception as e:  # noqa
            log("wiki:", e)
        time.sleep(3)
    return {}


def wiki_page(lang, title, maxlen=7000):
    j = wiki_get(lang, action="query", prop="extracts|pageimages|info|images", explaintext=1, piprop="name",
                 inprop="url", redirects=1, titles=title, imlimit=50)
    pages = j.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    p = pages[0]
    text = p.get("extract", "")
    text = re.split(r"\n==\s*(Примечания|Литература|Ссылки|См\. также|References|See also|External links|Notes|Further reading)\s*==", text)[0]
    files = [i["title"].split(":", 1)[1] for i in p.get("images", [])]
    return {"lang": lang, "title": p["title"], "url": p.get("fullurl") or f"https://{lang}.wikipedia.org/wiki/{p['title']}",
            "text": text[:maxlen], "len": len(text), "pageimage": p.get("pageimage"), "files": files}


def wiki_category(lang, cat):
    j = wiki_get(lang, action="query", list="categorymembers", cmtitle=cat, cmlimit=500, cmnamespace=0)
    return [m["title"] for m in j.get("query", {}).get("categorymembers", [])]


# ------------------------------------------------------------------ Wikimedia Commons
BAD_NAME = re.compile(r"(logo|flag|map|karte|carte|mapa|coat[_ ]of[_ ]arms|signature|diagram|chart|graph|icon|symbol|"
                      r"profile|elevation|route[_ ]?map|locator|plan\b|seal|emblem|wappen|scheme|schema|\.svg|\.gif|\.tif)", re.I)
FREE = re.compile(r"(^cc|public domain|^pd|cc0|gfdl|free art|attribution|no restrictions|copyrighted free use)", re.I)


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def commons_info(files, width=1600):
    out = []
    files = [f for f in files if f]
    for i in range(0, len(files), 40):
        try:
            r = S.get("https://commons.wikimedia.org/w/api.php", timeout=40, params=dict(
                action="query", format="json", formatversion=2, prop="imageinfo|categories", clshow="!hidden", cllimit=500,
                iiprop="url|size|mime|extmetadata", iiurlwidth=width, titles="|".join("File:" + f for f in files[i:i + 40])))
            pages = r.json().get("query", {}).get("pages", [])
        except Exception as e:  # noqa
            log("commons:", e)
            continue
        for p in pages:
            ii = (p.get("imageinfo") or [None])[0]
            if not ii or p.get("missing"):
                continue
            out.append(_info(p, ii))
    return out


def _info(p, ii):
    m = ii.get("extmetadata", {})
    g = lambda k: strip_tags(m.get(k, {}).get("value", ""))  # noqa
    return {"file": p["title"].split(":", 1)[1], "url": ii.get("thumburl") or ii["url"], "orig": ii["url"],
            "w": ii.get("width", 0), "h": ii.get("height", 0), "mime": ii.get("mime", ""),
            "author": re.sub(r"\s+", " ", g("Artist"))[:120] or "неизвестен", "license": g("LicenseShortName") or g("UsageTerms"),
            "license_url": g("LicenseUrl"), "nonfree": g("NonFree").lower() == "true",
            "desc": re.sub(r"\s+", " ", g("ImageDescription"))[:300],
            "cats": [c["title"].split(":", 1)[1] for c in p.get("categories", [])][:12],
            "source": ii.get("descriptionurl", "")}


def commons_search(query, n=20, width=1600):
    try:
        r = S.get("https://commons.wikimedia.org/w/api.php", timeout=40, params=dict(
            action="query", format="json", formatversion=2, generator="search", gsrnamespace=6,
            gsrsearch=f"{query} filetype:bitmap", gsrlimit=n, prop="imageinfo|categories", clshow="!hidden", cllimit=500,
            iiprop="url|size|mime|extmetadata", iiurlwidth=width))
        pages = sorted(r.json().get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    except Exception as e:  # noqa
        log("commons search:", e)
        return []
    return [_info(p, p["imageinfo"][0]) for p in pages if p.get("imageinfo")]


def usable(info, min_w=800):
    if info["nonfree"] or not FREE.search(info["license"] or ""):
        return False
    if info["mime"] not in ("image/jpeg", "image/png", "image/webp"):
        return False
    if BAD_NAME.search(info["file"]):
        return False
    if info["w"] < min_w or info["h"] < 500:
        return False
    ar = info["w"] / max(info["h"], 1)
    return 0.5 <= ar <= 2.4


def credit(info):
    lic = info.get("license") or ""
    return f"Фото: {info.get('author') or 'неизвестен'}, {lic}, Wikimedia Commons"
