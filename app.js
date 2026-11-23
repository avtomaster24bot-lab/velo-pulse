(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const state = { index: null, days: {}, local: new Set(), rub: "", list: [], queue: [], qi: 0 };
  const MONTHS = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
  const fmtDate = (d) => { const [y, m, dd] = d.split("-").map(Number); return `${dd} ${MONTHS[m - 1]} ${y}`; };
  const toast = (t) => { const el = $("#toast"); el.textContent = t; el.classList.add("on"); clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("on"), 2200); };
  const murl = (p, name) => (state.local.has(p.date) || !p.release ? "media/" : p.release) + name;
  const thumb = (url, w = 800) => url.replace(/\/(\d+)px-/, `/${w}px-`);

  async function getJSON(u) { const r = await fetch(u, { cache: "no-cache" }); if (!r.ok) throw new Error(u); return r.json(); }
  async function day(d) { if (!state.days[d]) state.days[d] = await getJSON(`data/${d}.json`); return state.days[d]; }

  async function load() {
    try { state.local = new Set((await getJSON("media/days.json")).days); } catch (e) {}
    state.index = await getJSON("data/index.json");
    if (state.index.updated) $("#updated").textContent = "Обновлено: " + state.index.updated.replace("T", " ") + " (Алматы)";
    chips(); route();
  }

  function chips() {
    const r = state.index.rubrics || {};
    $("#chips").innerHTML = `<button class="chip ${state.rub ? "" : "on"}" data-rub="" style="--c:#fff">Все рубрики</button>` +
      Object.entries(r).map(([id, x]) => `<button class="chip ${state.rub === id ? "on" : ""}" data-rub="${id}" style="--c:${x.color}">${x.emoji} ${esc(x.name)}</button>`).join("");
  }

  function card(p) {
    const f = p.files || {};
    const img = p.images?.[0];
    const prev = (f.previews || []).map((n, i) => `<img loading="lazy" src="${murl(p, n)}" alt="Слайд ${i + 1}" data-slide="${esc(p.slug)}" data-i="${i}">`).join("");
    const media = f.video
      ? `<div class="vid"><video controls playsinline preload="none" poster="${murl(p, f.poster)}" src="${murl(p, f.video)}"></video>
           <span class="rub">${p.emoji} ${esc(p.rubric_name)}</span>${f.video_duration ? `<span class="dur">🎬 ${Math.round(f.video_duration)} с</span>` : ""}</div>`
      : `<div class="cover" data-open="${esc(p.slug)}">${f.photo ? `<img loading="lazy" src="${murl(p, f.photo)}" alt="${esc(p.title)}">` : img ? `<img loading="lazy" src="${esc(thumb(img.url))}" alt="${esc(p.title)}">` : ""}
           <span class="rub">${p.emoji} ${esc(p.rubric_name)}</span></div>`;
    return `<article class="card" style="--c:${p.color}">
      ${media}
      <div class="body">
        <h3><a href="#/p/${esc(p.slug)}">${esc(p.title)}</a></h3>
        <p class="hook">${esc(p.hook)}</p>
        <p class="cap">${esc(p.caption)}</p>
        <div class="acts">
          ${f.video ? `<a class="btn primary sm" href="${murl(p, f.video)}" download>⬇ Скачать видео</a>` : ""}
          <button class="btn" data-copy="caption" data-slug="${esc(p.slug)}">📋 Скопировать текст</button>
          <a class="btn" href="#/p/${esc(p.slug)}">Слайды и тексты →</a>
          ${f.audio ? `<button class="btn" data-play="${esc(p.slug)}" title="Только голос, без музыки">🎧 Аудио</button>` : ""}
        </div>
      </div></article>`;
  }

  function findPost(slug) { return state.list.find((p) => p.slug === slug); }

  async function viewDay(d) {
    const dd = await day(d);
    let posts = dd.posts; state.list = posts;
    if (state.rub) posts = posts.filter((p) => p.rubric === state.rub);
    $("#view").innerHTML = `<div class="dayhead"><h2>Подборка за ${fmtDate(d)}</h2><span class="muted">${dd.posts.length} постов · 🎧 аудио · 🖼 слайды · 🎬 видео</span></div>` +
      (posts.length ? `<div class="grid">${posts.map(card).join("")}</div>` : `<div class="empty">В этой рубрике сегодня постов нет — загляните в <a href="#/archive">архив</a>.</div>`);
    state.queue = state.list.filter((p) => p.files?.audio);
  }

  async function viewRubric(rub) {
    const days = state.index.days.slice(0, 30);
    const all = [];
    for (const d of days) { try { all.push(...(await day(d.date)).posts.filter((p) => p.rubric === rub)); } catch (e) {} }
    state.list = all; state.queue = all.filter((p) => p.files?.audio);
    const r = state.index.rubrics[rub];
    $("#view").innerHTML = `<div class="dayhead"><h2>${r.emoji} ${esc(r.name)}</h2><span class="muted">${all.length} постов</span></div><div class="grid">${all.map(card).join("")}</div>`;
  }

  async function viewPost(slug) {
    const d = slug.slice(0, 10);
    const dd = await day(d); state.list = dd.posts;
    const p = findPost(slug);
    if (!p) { $("#view").innerHTML = `<div class="empty">Пост не найден.</div>`; return; }
    const f = p.files || {};
    const slides = (f.previews || []).map((n, i) => `<img loading="lazy" src="${murl(p, n)}" data-slide="${esc(p.slug)}" data-i="${i}" alt="Слайд ${i + 1}">`).join("");
    const img = p.images[0];
    $("#view").innerHTML = `<a href="#/day/${d}" class="muted">← Подборка за ${fmtDate(d)}</a>
    <div class="post" style="--c:${p.color}">
      <div>
        <span class="rub" style="position:static;display:inline-block;background:${p.color}">${p.emoji} ${esc(p.rubric_name)}</span>
        <h2>${esc(p.title)}</h2><p class="hook">${esc(p.hook)}</p>
        ${f.video ? `<div class="mainvid"><video controls playsinline preload="metadata" poster="${murl(p, f.poster)}" src="${murl(p, f.video)}"></video></div>
          <div class="acts" style="justify-content:center;margin:10px 0"><a class="btn primary" href="${murl(p, f.video)}" download>⬇ Скачать видео (${f.video_mb} МБ)</a></div>` :
          `<img class="big" src="${f.photo ? murl(p, f.photo) : esc(img.url)}" alt="${esc(p.title)}">`}
        <p class="credit">${p.images.map((i) => `<a href="${esc(i.source)}" target="_blank" rel="noopener">${esc(i.credit)}</a>`).join(" · ")}${p.music ? ` · 🎵 <a href="${esc(p.music.source)}" target="_blank" rel="noopener">«${esc(p.music.title)}» — ${esc(p.music.author)}</a>, <a href="${esc(p.music.license_url)}" target="_blank" rel="noopener">${esc(p.music.license)}</a>` : ""}</p>
        <div class="acts" style="margin:14px 0">
          ${f.audio ? `<button class="btn primary" data-play="${esc(p.slug)}">▶ Слушать (${Math.round(f.audio_duration || 0)} с)</button>` : ""}
          <button class="btn" data-copy="caption" data-slug="${esc(p.slug)}">📋 Скопировать текст</button>
          <button class="btn" data-share="${esc(p.slug)}">↗ Поделиться</button>
        </div>
        <div class="text">${esc(p.caption)}</div>
        <p>${p.hashtags.map(esc).join(" ")}</p>
        <div class="box"><h4>📚 Источники</h4>${p.sources.map((s) => `<div class="src"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a></div>`).join("")}</div>
        <div class="box"><h4>🖼 Карусель для Instagram / Telegram (${(f.slides || []).length} слайдов, 1080×1350)</h4><div class="slides">${slides}</div>
          <div class="acts" style="margin-top:12px">${f.zip ? `<a class="btn" href="${murl(p, f.zip)}" download>⬇ Скачать все слайды (ZIP)</a>` : ""}</div></div>
      </div>
      <div>
        ${f.video ? `<div class="box"><h4>🎬 Видео для Reels / Shorts / TikTok / Telegram</h4>
          <p class="muted">1080×1920 · ${f.video_duration} с · ${f.video_mb} МБ · мужской голос, фоновая музыка, субтитры вшиты</p></div>` : ""}
        ${f.photo ? `<div class="box"><h4>📷 Фото</h4><img class="big" src="${murl(p, f.photo)}" alt=""></div>` : ""}
        <div class="box"><h4>✍️ Готовые тексты</h4><div class="acts">
          <button class="btn" data-copy="caption" data-slug="${esc(p.slug)}">Instagram / Telegram</button>
          <button class="btn" data-copy="youtube" data-slug="${esc(p.slug)}">YouTube Shorts</button>
          <button class="btn" data-copy="tiktok" data-slug="${esc(p.slug)}">TikTok</button>
          <button class="btn" data-copy="narration" data-slug="${esc(p.slug)}">Текст озвучки</button></div></div>
        ${f.audio ? `<div class="box"><h4>🎧 Аудио (только голос)</h4><audio controls preload="none" src="${murl(p, f.audio)}" style="width:100%"></audio>
          <div class="acts" style="margin-top:8px"><a class="btn" href="${murl(p, f.audio)}" download>⬇ MP3</a></div></div>` : ""}
      </div>
    </div>`;
    state.queue = dd.posts.filter((x) => x.files?.audio);
    scrollTo(0, 0);
  }

  function viewArchive() {
    $("#view").innerHTML = `<div class="dayhead"><h2>Архив</h2><span class="muted">${state.index.days.length} дней</span></div><div class="archive">` +
      state.index.days.map((d) => `<a class="arch" href="#/day/${d.date}"><b>${fmtDate(d.date)}</b> <span class="muted">· ${d.count} постов</span><ul>${d.titles.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></a>`).join("") + "</div>";
  }

  async function route() {
    const h = location.hash.replace(/^#\/?/, "");
    const [a, b] = h.split("/").map(decodeURIComponent);
    document.querySelectorAll(".nav a").forEach((x) => x.classList.toggle("on", (x.dataset.nav === "today" && !a) || x.dataset.nav === a));
    $("#chips").style.display = a === "p" || a === "archive" ? "none" : "";
    try {
      if (a === "p" && b) await viewPost(b);
      else if (a === "archive") viewArchive();
      else if (a === "rubric" && b) { state.rub = b; chips(); await viewRubric(b); }
      else if (a === "day" && b) await viewDay(b);
      else await viewDay(state.index.days[0].date);
    } catch (e) { console.error(e); $("#view").innerHTML = `<div class="empty">Не удалось загрузить. Обновите страницу.</div>`; }
  }

  // ---------- плеер
  const audio = $("#plAudio");
  function play(slug) {
    const i = state.queue.findIndex((p) => p.slug === slug);
    state.qi = Math.max(0, i); startQ();
  }
  function startQ() {
    const p = state.queue[state.qi]; if (!p) return;
    $("#player").classList.remove("hidden");
    $("#plTitle").textContent = `${p.emoji} ${p.title}`;
    $("#plSub").textContent = `${state.qi + 1} из ${state.queue.length} · ${p.rubric_name}`;
    audio.src = murl(p, p.files.audio); audio.play().catch(() => {});
  }
  audio.onended = () => { if (state.qi < state.queue.length - 1) { state.qi++; startQ(); } };
  $("#plNext").onclick = () => { if (state.qi < state.queue.length - 1) { state.qi++; startQ(); } };
  $("#plPrev").onclick = () => { if (state.qi > 0) { state.qi--; startQ(); } };
  $("#plClose").onclick = () => { audio.pause(); $("#player").classList.add("hidden"); };
  $("#playAll").onclick = async () => { if (!state.queue.length) await viewDay(state.index.days[0].date); state.qi = 0; startQ(); };

  // ---------- модалка
  let slideCtx = null;
  function modal(html) { $("#modalBody").innerHTML = html; $("#modal").classList.remove("hidden"); }
  function showSlide() {
    const { p, i } = slideCtx; const f = p.files;
    modal(`<img src="${murl(p, f.slides[i])}" alt=""><div class="nav-sl"><button class="btn" data-sl="-1">← Назад</button><span class="muted">${i + 1} / ${f.slides.length}</span><button class="btn" data-sl="1">Дальше →</button></div>`);
  }
  $("#modal").onclick = (e) => { if (e.target.id === "modal" || e.target.dataset.close) { $("#modal").classList.add("hidden"); $("#modalBody").innerHTML = ""; } };

  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); } catch (e) { const ta = document.createElement("textarea"); ta.value = t; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
  }
  function postText(p, kind) {
    const post = p.post || {};
    const link = location.origin + location.pathname + "#/p/" + p.slug;
    if (kind === "youtube") return `${post.youtube_title || p.title}\n\n${post.youtube_description || p.caption}`;
    if (kind === "tiktok") return post.tiktok || `${p.title}\n${p.hashtags.join(" ")}`;
    if (kind === "narration") return p.narration;
    return post.full || `${p.emoji} ${p.title}\n\n${p.caption}\n\n${p.hashtags.join(" ")}\n\n${link}`;
  }

  document.addEventListener("click", async (e) => {
    const t = e.target.closest("[data-rub],[data-play],[data-video],[data-copy],[data-open],[data-slide],[data-sl],[data-share]");
    if (!t) return;
    const d = t.dataset;
    if (d.rub !== undefined) { state.rub = d.rub; chips(); if (d.rub) location.hash = "#/rubric/" + d.rub; else location.hash = "#/"; }
    else if (d.play) play(d.play);
    else if (d.video) { const p = findPost(d.video); modal(`<video controls autoplay playsinline src="${murl(p, p.files.video)}" poster="${murl(p, p.files.poster)}" style="max-height:86vh"></video><div class="acts" style="justify-content:center;margin-top:10px"><a class="btn" href="${murl(p, p.files.video)}" download>⬇ Скачать видео</a><a class="btn" href="#/p/${p.slug}" data-close="1">Тексты для соцсетей →</a></div>`); }
    else if (d.copy) { const p = findPost(d.slug); await copyText(postText(p, d.copy)); toast({ caption: "Текст поста скопирован", youtube: "Название и описание для YouTube скопированы", tiktok: "Подпись для TikTok скопирована", narration: "Текст озвучки скопирован" }[d.copy]); }
    else if (d.open) location.hash = "#/p/" + d.open;
    else if (d.slide) { slideCtx = { p: findPost(d.slide), i: +d.i }; showSlide(); }
    else if (d.sl) { const n = slideCtx.p.files.slides.length; slideCtx.i = (slideCtx.i + +d.sl + n) % n; showSlide(); }
    else if (d.share) { const url = location.origin + location.pathname + "#/p/" + d.share; if (navigator.share) navigator.share({ title: "ВелоПульс", url }).catch(() => {}); else { await copyText(url); toast("Ссылка скопирована"); } }
  });
  document.addEventListener("play", (e) => { if (e.target.tagName === "VIDEO") { document.querySelectorAll("video").forEach((v) => v !== e.target && v.pause()); audio.pause(); } }, true);
  window.addEventListener("hashchange", route);
  load();
})();
