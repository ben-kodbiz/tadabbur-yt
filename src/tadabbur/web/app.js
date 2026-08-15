/* Tadabbur Library display - loads exported JSON and renders lectures. */

const state = {
  lectures: [],
  speakers: [],
  category: "",
  speaker: "",
  query: "",
};

const el = {
  list: document.getElementById("lectures"),
  empty: document.getElementById("empty"),
  stats: document.getElementById("stats"),
  search: document.getElementById("search"),
  category: document.getElementById("filter-category"),
  speaker: document.getElementById("filter-speaker"),
  player: document.getElementById("player"),
  audio: document.getElementById("audio"),
  nowPlaying: document.getElementById("now-playing"),
  sourceLink: document.getElementById("source-link"),
};

function fmtDuration(sec) {
  if (!sec) return "?";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}j ${m}m`;
  return `${m}m`;
}

function fmtDate(d) {
  if (!d) return "";
  return d; // ISO date, keep simple
}

function slugToName(s) {
  if (!s) return s;
  return s.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

async function loadData() {
  try {
    const [lectures, speakers] = await Promise.all([
      fetch("/data/lectures.json").then((r) => r.json()),
      fetch("/data/speakers.json").then((r) => r.json()),
    ]);
    state.lectures = lectures;
    state.speakers = speakers;
  } catch (err) {
    el.list.innerHTML = "";
    el.empty.classList.remove("hidden");
    el.empty.textContent = "Tiada data. Jalankan: tadabbur export --mode library";
    return;
  }
  populateSpeakerFilter();
  render();
}

function populateSpeakerFilter() {
  const cur = el.speaker.value;
  el.speaker.innerHTML = '<option value="">Semua penceramah</option>';
  for (const s of state.speakers) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name;
    el.speaker.appendChild(opt);
  }
  el.speaker.value = cur;
}

function matchesFilters(lec) {
  const q = state.query.toLowerCase();
  const hay = [lec.title, lec.description, lec.surah, lec.speaker, (lec.tags || []).join(" ")].join(" ").toLowerCase();
  if (q && !hay.includes(q)) return false;
  if (state.category && lec.category !== state.category) return false;
  if (state.speaker && lec.speaker !== state.speaker) return false;
  return true;
}

function isFailed(lec) {
  return lec.status === "FAILED";
}

function render() {
  const filtered = state.lectures.filter(matchesFilters);
  el.list.innerHTML = "";

  const okCount = filtered.filter((l) => !isFailed(l)).length;
  const failCount = filtered.length - okCount;
  el.stats.textContent = `${filtered.length} kuliah (${okCount} sedia, ${failCount} gagal) daripada ${state.lectures.length} jumlah`;

  if (filtered.length === 0) {
    el.empty.classList.remove("hidden");
    el.list.classList.add("hidden");
    return;
  }
  el.empty.classList.add("hidden");
  el.list.classList.remove("hidden");

  for (const lec of filtered) {
    const li = document.createElement("li");
    li.className = "lecture";
    const failed = isFailed(lec);
    if (failed) li.classList.add("failed");

    const title = document.createElement("div");
    title.className = "title";
    title.appendChild(badge(lec.category));
    if (failed) title.appendChild(failedBadge());
    title.appendChild(document.createTextNode(lec.title));

    const meta = document.createElement("div");
    meta.className = "meta";
    const speaker = state.speakers.find((s) => s.id === lec.speaker);
    meta.textContent = [
      speaker ? speaker.name : slugToName(lec.speaker),
      fmtDate(lec.published_at),
      fmtDuration(lec.duration),
      lec.surah ? `Surah ${slugToName(lec.surah)}` : "",
      lec.ayah_start ? `Ayat ${lec.ayah_start}${lec.ayah_end && lec.ayah_end !== lec.ayah_start ? `-${lec.ayah_end}` : ""}` : "",
    ].filter(Boolean).join("  ·  ");

    const tags = document.createElement("div");
    tags.className = "tags";
    for (const t of (lec.tags || [])) {
      const span = document.createElement("span");
      span.className = "tag";
      span.textContent = t;
      tags.appendChild(span);
    }

    li.appendChild(title);
    li.appendChild(meta);
    if (tags.childNodes.length) li.appendChild(tags);

    if (!failed && lec.audio_url) {
      li.addEventListener("click", () => play(lec));
    }
    el.list.appendChild(li);
  }
}

function failedBadge() {
  const span = document.createElement("span");
  span.className = "badge failed-badge";
  span.textContent = "gagal";
  return span;
}

function badge(category) {
  const span = document.createElement("span");
  span.className = "badge";
  span.textContent = category || "lain";
  return span;
}

function play(lec) {
  if (!lec.audio_url) {
    alert("Tiada fail audio untuk kuliah ini.");
    return;
  }
  el.player.classList.remove("hidden");
  el.audio.src = lec.audio_url;
  el.audio.play().catch(() => {});
  const speaker = state.speakers.find((s) => s.id === lec.speaker);
  el.nowPlaying.textContent = `${speaker ? speaker.name : ""} — ${lec.title}`;
  el.sourceLink.href = lec.source_url || "#";
}

el.search.addEventListener("input", (e) => { state.query = e.target.value; render(); });
el.category.addEventListener("change", (e) => { state.category = e.target.value; render(); });
el.speaker.addEventListener("change", (e) => { state.speaker = e.target.value; render(); });

loadData();
