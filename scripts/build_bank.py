#!/usr/bin/env python3
"""Собирает «банк тем» bank/bank.json из проверенного контента семейства Velo:
Вело-вселенная (справочник: детали, ремонт, история, типы, производители, статьи)
и Velopark (веломаршруты мира и Казахстана, с источниками).
Запускается вручную, когда в справочниках появились новые материалы:
  python scripts/build_bank.py ../velouniverse ../velopark-routes
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VU = Path(sys.argv[1] if len(sys.argv) > 1 else "../velouniverse").resolve()
VP = Path(sys.argv[2] if len(sys.argv) > 2 else "../velopark-routes").resolve()
VU_URL = "https://avtomaster24bot-lab.github.io/velo-universe/"
VP_URL = "https://avtomaster24bot-lab.github.io/velopark/"


def clean(t):
    t = re.sub(r"\[\[[a-z]+:[^\]|]+\|([^\]]+)\]\]", r"\1", str(t))
    t = re.sub(r"\[\[[a-z]+:([^\]|]+)\]\]", r"\1", t)
    return t.strip()


def load_mod(path, name):
    ns = {"__file__": str(path)}
    exec(open(path, encoding="utf-8").read(), ns)
    return ns


def photo(cred, key):
    if isinstance(key, (list, tuple)):
        key = key[0] if key else None
    if isinstance(key, dict):
        key = key.get("key") or key.get("id")
    c = cred.get(key) if isinstance(key, str) else None
    if not c:
        return None
    return {"file": c["file"], "author": c.get("author", ""), "license": c.get("license", ""),
            "license_url": c.get("license_url", ""), "source": c.get("source", ""), "desc": c.get("desc", "")[:200]}


items = []


def add(**k):
    k["photos"] = [p for p in k.get("photos", []) if p]
    items.append(k)


sys.path.insert(0, str(VU / "content"))
cred = json.loads((VU / "content/credits.json").read_text(encoding="utf-8"))
import parts, history, guides, biketypes, makers, toollist, round3, art_compat, art_other, art_susp_ebike  # noqa

for p in parts.PARTS:
    txt = clean(p["text"]) + "\n" + "\n".join(clean(s) for s in p.get("specs", []))
    add(id="part-" + p["id"], rubric="tech", title=p["ru"], en=p.get("en", ""), text=clean(p["short"]) + "\n" + txt,
        photos=[photo(cred, p["id"])], img_query=f"bicycle {p.get('en','')}",
        src=[["Вело-вселенная: " + p["ru"], f"{VU_URL}parts/{p['id']}/"]])
for g in guides.GUIDES + round3.GUIDES3:
    steps = "\n".join(f"{i+1}. {clean(s)}" for i, s in enumerate(g["steps"]))
    add(id="guide-" + g["id"], rubric="service", title=g["title"], en="", text=clean(g["intro"]) + "\n" + steps +
        ("\nВажно: " + clean(g["warn"]) if g.get("warn") else ""),
        photos=[photo(cred, g.get("img"))] if g.get("img") else [], img_query="",
        src=[["Вело-вселенная: " + g["title"], f"{VU_URL}guides/{g['id']}/"]])
for t in round3.TROUBLE:
    add(id="trouble-" + t["id"], rubric="hacks", title=t["title"], en="",
        text="Признаки: " + "; ".join(clean(x) for x in t["signs"]) + "\nПричины и что делать: " +
             "; ".join(clean(x) if isinstance(x, str) else " — ".join(clean(y) for y in x) for x in t["causes"]),
        photos=[], img_query="", src=[["Вело-вселенная: неисправности", f"{VU_URL}trouble/"]])
for h in history.HISTORY:
    add(id="hist-" + re.sub(r"\W+", "-", h["title"].lower())[:40].strip("-"), rubric="history", title=h["title"],
        en="", text=f"{h['year']}. " + clean(h["text"]), photos=[photo(cred, h.get("img"))] if h.get("img") else [],
        img_query="", src=[["Вело-вселенная: история велосипеда", f"{VU_URL}history/"]])
for b in biketypes.TYPES:
    add(id="type-" + b["id"], rubric="facts", title=b["ru"], en=b.get("en", ""),
        text=clean(b["short"]) + "\n" + clean(b["text"]) + "\nОсобенности: " + "; ".join(clean(x) for x in b.get("features", [])),
        photos=[photo(cred, b.get("img"))], img_query=b.get("en", ""),
        src=[["Вело-вселенная: " + b["ru"], f"{VU_URL}types/{b['id']}/"]])
for m in makers.MAKERS:
    add(id="maker-" + re.sub(r"\W+", "-", m["name"].lower()).strip("-"), rubric="history", title=m["name"], en=m["name"],
        text=f"{m['name']} ({m.get('country','')}, {m.get('city','')}, осн. {m.get('founded','')}). " + clean(m["text"]),
        photos=[], img_query=m["name"] + " bicycle", src=[["Вело-вселенная: производители", f"{VU_URL}makers/"]])
for t in toollist.TOOLS + round3.TOOLS3:
    add(id="tool-" + t["id"], rubric="service", title=t["ru"], en=t.get("en", ""),
        text=clean(t["text"]) + "\nСоветы: " + "; ".join(clean(x) for x in t.get("tips", [])),
        photos=[photo(cred, t.get("img"))] if t.get("img") else [], img_query=t.get("en", ""),
        src=[["Вело-вселенная: инструмент", f"{VU_URL}tools/"]])
arts = art_compat.A_COMPAT + art_other.A_BUY + art_other.A_FRAMES + art_other.A_HIST + art_susp_ebike.A_SUSP + art_susp_ebike.A_EBIKE + round3.A_R3
for a in arts:
    secs = []
    for s in a["sections"]:
        if isinstance(s, (list, tuple)):
            secs.append(" ".join(clean(x) if isinstance(x, str) else " ".join(map(clean, x)) for x in s))
        elif isinstance(s, dict):
            secs.append(" ".join(clean(v) if isinstance(v, str) else " ".join(map(clean, v)) if isinstance(v, list) else "" for v in s.values()))
        else:
            secs.append(clean(s))
    add(id="art-" + a["id"], rubric="tech" if a.get("cat") != "hist" else "history", title=a["title"], en="",
        text=clean(a["intro"]) + "\n" + "\n".join(secs)[:5000], photos=[photo(cred, a.get("img"))] if a.get("img") else [],
        img_query="", src=[["Вело-вселенная: " + a["title"], f"{VU_URL}a/{a['id']}/"]])

# ---- маршруты
ns = load_mod(VP / "content/routes.py", "routes")
rcred = json.loads((VP / "content/credits.json").read_text(encoding="utf-8"))
by_route = {}
for k, c in rcred.items():
    by_route.setdefault(c.get("route"), []).append(k)
for r in ns["R"]:
    desc = "\n".join(r.get("desc", []))
    facts = (f"Страны: {', '.join(r.get('countries', []))}. Регион: {r.get('region','')}. "
             f"Длина: {r.get('dist_note') or (str(r.get('dist')) + ' км' if r.get('dist') else '—')}. "
             f"Набор/рельеф: {r.get('gain_note') or r.get('gain') or '—'}. Покрытие: {r.get('surface','')}. "
             f"Сложность: {r.get('diff','')}. Лучшие месяцы: {', '.join(map(str, r.get('season', [])))}.")
    add(id="route-" + r["slug"], rubric="routes", title=r["title"], en="",
        kz=any("Казахстан" in c for c in r.get("countries", [])),
        text=r.get("summary", "") + "\n" + desc + "\n" + facts + "\nСамое интересное: " + "; ".join(r.get("highlights", [])) +
             "\nСоветы: " + "; ".join(r.get("tips", [])),
        photos=[photo(rcred, k) for k in sorted(by_route.get(r["slug"], []))][:3], img_query="",
        src=[[s[0], s[1]] for s in r.get("src", []) if isinstance(s, (list, tuple)) and len(s) > 1] +
            [["Velopark: " + r["title"], f"{VP_URL}route.html?id={r['slug']}"]])

out = ROOT / "bank/bank.json"
out.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
from collections import Counter
print(len(items), Counter(i["rubric"] for i in items), "с фото:", sum(1 for i in items if i["photos"]))
