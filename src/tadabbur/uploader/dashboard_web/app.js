/* Upload pipeline tracking dashboard — read-only, loads data.json only. */

const state = { items: [], query: "", upload: "", rights: "" };

const APPROVED = new Set([
  "permission_confirmed", "license_confirmed", "public_domain",
  "creative_commons", "owned_by_operator",
]);

const el = {
  tbody: document.querySelector("#items tbody"),
  empty: document.getElementById("empty"),
  summary: document.getElementById("summary"),
  generated: document.getElementById("generated"),
  search: document.getElementById("search"),
  upload: document.getElementById("filter-upload"),
  rights: document.getElementById("filter-rights"),
};

function badge(text, cls) {
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtWhen(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toISOString().slice(0, 10);
}

function fmtDuration(sec) {
  if (!sec) return "";
  const m = Math.round(sec / 60);
  return `${m}m`;
}

function render() {
  const q = state.query.toLowerCase();
  const rows = state.items.filter((it) => {
    if (state.upload === "uploaded" && !it.uploaded) return false;
    if (state.upload === "not_queued" && it.upload_status !== "not_queued") return false;
    if (state.upload && state.upload !== "uploaded" &&
        it.upload_status !== state.upload) return false;
    if (state.rights === "approved" && !APPROVED.has(it.rights_status)) return false;
    if (state.rights && state.rights !== "approved" && it.rights_status !== state.rights)
      return false;
    if (q) {
      const hay = [it.title, it.original_title, it.speaker, it.source_name,
        it.source_key].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  el.tbody.innerHTML = rows.map((it) => {
    let upBadge;
    if (it.uploaded) {
      upBadge = `<a href="${esc(it.platform_url)}" target="_blank" rel="noopener">` +
                badge(`uploaded · ${fmtWhen(it.uploaded_at)}`, "uploaded") + "</a>";
      if (it.attempts > 1) upBadge += ` <span class="muted">${it.attempts} tries</span>`;
    } else if (it.upload_status === "failed" || it.error) {
      upBadge = badge("failed", "failed") +
        (it.error ? `<div class="err">${esc(it.error.slice(0, 90))}</div>` : "");
    } else if (!it.upload_authorized) {
      upBadge = badge(it.rights_status.replace(/_/g, " "), "blocked");
    } else if (it.rights_status === "manual_review_required") {
      upBadge = badge("needs review", "review");
    } else {
      upBadge = badge(it.state.replace(/_/g, " ").toLowerCase(), "neutral");
    }

    const rights = APPROVED.has(it.rights_status)
      ? badge(it.rights_status.replace(/_/g, " "), "uploaded")
      : badge(it.rights_status.replace(/_/g, " "),
              it.rights_status === "upload_not_authorized" ? "blocked" : "review");

    const titleCell = it.platform_url
      ? `<a href="${esc(it.source_url)}" target="_blank" rel="noopener">${esc(it.title)}</a>`
      : esc(it.title);

    return `<tr>
      <td>${titleCell}${it.published_at ? ` <span class="muted">${esc(it.published_at)}</span>` : ""}</td>
      <td>${esc(it.speaker || "—")}</td>
      <td>${esc(it.source_name)}</td>
      <td>${rights}</td>
      <td><span class="muted">${esc(it.state)}</span></td>
      <td>${upBadge}</td>
      <td class="muted">${fmtDuration(it.duration_seconds)}</td>
      <td class="muted">${it.sizes_mb.original}/${it.sizes_mb.audio}/${it.sizes_mb.video}</td>
    </tr>`;
  }).join("");

  document.getElementById("items").classList.toggle("hidden", rows.length === 0);
  el.empty.classList.toggle("hidden", rows.length !== 0);
}

function summarize(items) {
  const uploaded = items.filter((i) => i.uploaded).length;
  const failed = items.filter((i) => i.upload_status === "failed").length;
  const review = items.filter((i) => i.rights_status === "manual_review_required").length;
  const blocked = items.filter((i) => i.rights_status === "upload_not_authorized").length;
  const inFlight = items.length - uploaded - failed - blocked - review;
  el.summary.innerHTML = `
    <div class="stat"><b>${items.length}</b> total</div>
    <div class="stat"><b class="ok">${uploaded}</b> uploaded</div>
    <div class="stat"><b>${inFlight}</b> in pipeline</div>
    <div class="stat"><b class="warn">${review}</b> needs review</div>
    <div class="stat"><b class="bad">${blocked}</b> blocked</div>
    <div class="stat"><b class="bad">${failed}</b> failed</div>`;
}

async function load() {
  try {
    const data = await fetch("./data.json").then((r) => r.json());
    state.items = data.items || [];
    el.generated.textContent =
      `snapshot generated ${data.generated_at || "?"} — read-only view`;
  } catch (err) {
    el.generated.textContent = "no data.json found — run: upipeline export-dashboard";
    return;
  }
  summarize(state.items);
  render();
}

el.search.addEventListener("input", (e) => { state.query = e.target.value; render(); });
el.upload.addEventListener("change", (e) => { state.upload = e.target.value; render(); });
el.rights.addEventListener("change", (e) => { state.rights = e.target.value; render(); });

load();
