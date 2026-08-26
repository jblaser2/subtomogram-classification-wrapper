const $ = (id) => document.getElementById(id);

let currentRunId = null;
let currentEventSource = null;
const jobRows = {}; // "package|k|seed" isn't known until finish_job; keyed by package for the live view

// ---------- package picker ----------

function kLimitNote(caps) {
  if (!caps.variable_k) return "fixed k";
  const [lo, hi] = caps.k_range;
  if (hi != null) return `k ${lo}–${hi} only`;
  return "";
}

async function loadPackages() {
  const res = await fetch("/api/packages");
  const packages = await res.json();
  const container = $("package-picker");
  container.innerHTML = "";
  for (const pkg of packages) {
    const row = document.createElement("label");
    row.className = "pkg-row";
    const dotClass = pkg.installed ? "ok" : "bad";
    const title = pkg.installed
      ? "requirements satisfied"
      : "missing requirements: " + pkg.checks.filter((c) => !c.ok && !c.optional).map((c) => c.message).join("; ");
    row.title = title;
    const kNote = kLimitNote(pkg.capabilities);
    row.innerHTML = `
      <div class="pkg-row-top">
        <input type="checkbox" value="${pkg.name}" ${pkg.installed ? "checked" : ""}>
        <span class="dot ${dotClass}"></span>
        <span class="pkg-name">${pkg.display_name}</span>
        <span class="pkg-tier">${pkg.tier}</span>
        ${kNote ? `<span class="pkg-k-note">${kNote}</span>` : ""}
      </div>
      ${pkg.algorithm ? `<div class="pkg-algo">${pkg.algorithm}</div>` : ""}
    `;
    container.appendChild(row);
  }
}

// ---------- form field show/hide ----------

function wireConditionalFields() {
  const maskKind = $("f-mask-kind");
  const sync = () => {
    const kind = maskKind.value;
    const isSphere = kind === "sphere";
    const isCylinder = kind === "cylinder";
    $("mask-sphere-or-cylinder-fields").classList.toggle("hidden", !isSphere && !isCylinder);
    $("mask-cylinder-fields").classList.toggle("hidden", !isCylinder);
    $("mask-file-fields").classList.toggle("hidden", kind !== "file");
    $("mask-center-fields").classList.toggle("hidden", !isSphere && !isCylinder);
    $("f-mask-radius-label").firstChild.textContent = isCylinder
      ? "Radius (voxels, cross-section perpendicular to axis)"
      : "Radius (voxels)";
  };
  maskKind.addEventListener("change", sync);
  sync();

  const wedgeKind = $("f-wedge-kind");
  const syncWedge = () => {
    $("wedge-uniform-fields").classList.toggle("hidden", wedgeKind.value !== "uniform");
  };
  wedgeKind.addEventListener("change", syncWedge);
  syncWedge();
}

// ---------- building the config from the form ----------

function parseIntList(text) {
  const parts = text.split(",").map((s) => s.trim()).filter(Boolean).map(Number);
  if (parts.some((n) => Number.isNaN(n))) throw new Error(`not a number list: "${text}"`);
  return parts.length === 1 ? parts[0] : parts;
}

function numOrNull(id) {
  const v = $(id).value;
  return v === "" ? null : Number(v);
}

function buildMaskConfig() {
  const mask = { kind: $("f-mask-kind").value, edge: 3.0 };
  if (mask.kind === "sphere" || mask.kind === "cylinder") {
    mask.radius = numOrNull("f-mask-radius");
    const cz = numOrNull("f-mask-center-z");
    const cy = numOrNull("f-mask-center-y");
    const cx = numOrNull("f-mask-center-x");
    if (cz !== null && cy !== null && cx !== null) mask.center = [cz, cy, cx];
  }
  if (mask.kind === "cylinder") {
    mask.half_height = numOrNull("f-mask-half-height");
    mask.axis = $("f-mask-axis").value;
  }
  if (mask.kind === "file") mask.path = $("f-mask-path").value;
  return mask;
}

function buildConfig() {
  const mask = buildMaskConfig();
  const wedge = { kind: $("f-wedge-kind").value };
  if (wedge.kind === "uniform") {
    wedge.tilt_min = numOrNull("f-tilt-min");
    wedge.tilt_max = numOrNull("f-tilt-max");
  }

  const packages = Array.from(document.querySelectorAll("#package-picker input:checked")).map((el) => el.value);

  return {
    particles: $("f-particles").value,
    pattern: $("f-pattern").value,
    pixel_size: numOrNull("f-pixel-size"),
    alignment_state: $("f-alignment-state").value,
    mask,
    wedge,
    k: parseIntList($("f-k").value),
    seeds: parseIntList($("f-seeds").value),
    mode: $("f-mode").value,
    out_dir: $("f-out-dir").value,
    packages,
  };
}

// ---------- progress panel ----------

function setProgressCollapsed(collapsed) {
  $("progress-list").classList.toggle("hidden", collapsed);
  $("progress-toggle").textContent = collapsed ? "show" : "hide";
}

function resetProgressPanel() {
  $("progress-list").innerHTML = "";
  for (const k of Object.keys(jobRows)) delete jobRows[k];
  setProgressCollapsed(false); // a fresh run should always start visible
}

function ensureJobRow(pkg) {
  if (jobRows[pkg]) return jobRows[pkg];
  const el = document.createElement("div");
  el.className = "job-row";
  el.innerHTML = `
    <div class="job-head"><span>${pkg}</span><span class="job-status">starting…</span></div>
    <div class="bar-track"><div class="bar-fill"></div></div>
  `;
  $("progress-list").appendChild(el);
  jobRows[pkg] = el;
  return el;
}

function handleEvent(evt) {
  const { event, package: pkg, payload } = evt;
  if (event === "run_complete") {
    finishRun(payload);
    return;
  }
  const row = ensureJobRow(pkg);
  const status = row.querySelector(".job-status");
  const bar = row.querySelector(".bar-fill");
  if (event === "start_job") {
    status.textContent = "starting…";
  } else if (event === "step") {
    status.textContent = payload.name;
    const pct = payload.total ? (100 * payload.index) / payload.total : 0;
    bar.style.width = `${pct}%`;
  } else if (event === "substep") {
    status.textContent = payload.text;
  } else if (event === "finish_job") {
    row.classList.add(payload.ok ? "done" : "failed");
    status.textContent = payload.ok ? `done ${payload.message}` : `failed — ${payload.message}`;
    bar.style.width = "100%";
  }
}

// ---------- kicking off a run ----------

async function startRun() {
  const errBox = $("submit-error");
  errBox.classList.add("hidden");
  errBox.textContent = "";

  let config;
  try {
    config = buildConfig();
  } catch (e) {
    errBox.textContent = e.message;
    errBox.classList.remove("hidden");
    return;
  }
  if (!config.particles) {
    errBox.textContent = "particle directory is required";
    errBox.classList.remove("hidden");
    return;
  }
  if (!config.packages.length) {
    errBox.textContent = "select at least one package";
    errBox.classList.remove("hidden");
    return;
  }

  $("run-btn").disabled = true;
  resetProgressPanel();
  $("results-body").innerHTML = "";
  $("results-body").className = "muted";
  $("results-body").textContent = "Running…";

  const res = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    errBox.textContent = typeof detail.detail === "string" ? detail.detail : JSON.stringify(detail.detail, null, 2);
    errBox.classList.remove("hidden");
    $("run-btn").disabled = false;
    return;
  }
  const { run_id } = await res.json();
  currentRunId = run_id;

  if (currentEventSource) currentEventSource.close();
  currentEventSource = new EventSource(`/api/runs/${run_id}/events`);
  currentEventSource.onmessage = (msg) => handleEvent(JSON.parse(msg.data));
  currentEventSource.onerror = () => {
    currentEventSource.close();
    $("run-btn").disabled = false;
  };
}

// ---------- results panel ----------

async function finishRun(payload) {
  currentEventSource.close();
  $("run-btn").disabled = false;
  setProgressCollapsed(true); // auto-collapse on completion; "show" reopens it for errors/timing

  if (payload.status === "error") {
    $("results-body").innerHTML = `<div class="error">${payload.error}</div>`;
    return;
  }

  const res = await fetch(`/api/runs/${currentRunId}/report`);
  const report = await res.json();
  renderResults(report);
}

function statusBadge(status) {
  const cls = status === "ok" ? "ok" : status === "skipped" || status === "missing_requirements" ? "warn" : "fail";
  return `<span class="badge ${cls}">${status}</span>`;
}

function classesSummary(r) {
  return r.n_per_class && Object.keys(r.n_per_class).length
    ? Object.entries(r.n_per_class).map(([c, n]) => `${c}:${n}`).join(", ")
    : "—";
}

function resultRow(r, groupId) {
  const viewBtn = r.status === "ok" && r.class_averages && Object.keys(r.class_averages).length
    ? `<button class="link-btn" onclick="viewPanel('${r.package}', ${r.k}, ${r.seed})">class averages</button>`
    : "";
  const rowAttrs = groupId ? ` class="group-detail hidden" data-group="${groupId}"` : "";
  return `<tr${rowAttrs}>
    <td>${groupId ? "&nbsp;&nbsp;&nbsp;&nbsp;seed " + r.seed : r.package}</td>
    <td>${groupId ? "" : r.k}</td><td>${groupId ? "" : r.seed}</td>
    <td>${statusBadge(r.status)}</td>
    <td>${r.elapsed_sec ? r.elapsed_sec.toFixed(1) + "s" : "—"}</td>
    <td>${classesSummary(r)}</td>
    <td>${r.error ? `<span class="muted">${r.error}</span>` : viewBtn}</td>
  </tr>`;
}

// Groups rows crowding the table (many seeds and/or many k values for one package)
// into one collapsed summary row per (package, k) with an expand toggle -- there is
// no principled "best seed" without ground truth (not wired into the orchestrator),
// so this narrows the table down visually rather than picking a winner for you.
function groupResults(results) {
  const groups = new Map();
  for (const r of results) {
    const key = `${r.package}|${r.k}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  return [...groups.values()];
}

function renderResults(report) {
  const body = $("results-body");
  body.className = "";
  const groups = groupResults(report.results);
  const rows = groups
    .map((group, gi) => {
      if (group.length === 1) return resultRow(group[0], null);
      const nOk = group.filter((r) => r.status === "ok").length;
      const times = group.map((r) => r.elapsed_sec).filter((t) => t != null);
      const timeRange = times.length ? `${Math.min(...times).toFixed(1)}–${Math.max(...times).toFixed(1)}s` : "—";
      const groupId = `grp-${gi}`;
      const summaryRow = `<tr>
        <td>${group[0].package}</td><td>${group[0].k}</td>
        <td><button class="link-btn" onclick="toggleGroup('${groupId}')">${group.length} seeds &#9656;</button></td>
        <td>${nOk}/${group.length} ok</td>
        <td>${timeRange}</td>
        <td class="muted">varies by seed</td><td></td>
      </tr>`;
      const detailRows = group
        .sort((a, b) => a.seed - b.seed)
        .map((r) => resultRow(r, groupId))
        .join("");
      return summaryRow + detailRows;
    })
    .join("");

  const successful = report.results.filter((r) => r.status === "ok" && r.class_averages && Object.keys(r.class_averages).length);
  const allPanels = successful.length
    ? `<h2>All class averages</h2><div class="panel-grid">${successful
        .map((r) => `
          <div class="panel-grid-item">
            <div class="panel-grid-label">${r.package} k=${r.k} seed=${r.seed}</div>
            <a href="/api/runs/${currentRunId}/panel/${r.package}/${r.k}/${r.seed}" target="_blank" rel="noopener">
              <img class="panel-img" src="/api/runs/${currentRunId}/panel/${r.package}/${r.k}/${r.seed}">
            </a>
          </div>`)
        .join("")}</div>`
    : "";

  body.innerHTML = `
    <table>
      <thead><tr><th>package</th><th>k</th><th>seed</th><th>status</th><th>time</th><th>classes</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div id="panel-view"></div>
    ${report.comparison ? `
      <h2>Cross-package comparison <span class="muted" style="font-weight:400; text-transform:none;">(click to open full size)</span></h2>
      <a href="/api/runs/${currentRunId}/comparison.png" target="_blank" rel="noopener">
        <img class="panel-img" src="/api/runs/${currentRunId}/comparison.png">
      </a>` : ""}
    ${allPanels}
  `;
}

function toggleGroup(groupId) {
  const rows = document.querySelectorAll(`tr[data-group="${groupId}"]`);
  const nowHidden = !rows[0]?.classList.contains("hidden");
  rows.forEach((row) => row.classList.toggle("hidden", nowHidden));
}

function viewPanel(pkg, k, seed) {
  const el = $("panel-view");
  el.innerHTML = `<h2>${pkg} k=${k} seed=${seed}</h2>
    <a href="/api/runs/${currentRunId}/panel/${pkg}/${k}/${seed}" target="_blank" rel="noopener">
      <img class="panel-img" src="/api/runs/${currentRunId}/panel/${pkg}/${k}/${seed}">
    </a>`;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- dataset / mask preview (shared) ----------

function closePreviewBox(boxId) {
  const box = $(boxId);
  box.className = "preview-slot";
  box.innerHTML = "";
}

async function runPreview(endpoint, boxId, extraBody, closeLabel) {
  const box = $(boxId);
  box.className = "preview-slot";
  box.textContent = "Loading…";

  const body = {
    particles: $("f-particles").value,
    pattern: $("f-pattern").value,
    pixel_size: numOrNull("f-pixel-size"),
    ...extraBody,
  };
  if (!body.particles) {
    box.className = "preview-slot error";
    box.textContent = "particle directory is required";
    return;
  }

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    box.className = "preview-slot error";
    box.textContent = detail.detail;
    return;
  }
  const d = await res.json();
  box.className = "preview-slot preview-box";
  box.innerHTML = `
    <div class="preview-specs">${d.n_particles} particles &middot; box ${d.box}&sup3; &middot; ${d.pixel_size.toFixed(3)} Å/px</div>
    <img class="panel-img" src="data:image/png;base64,${d.preview_png_base64}">
    <button type="button" class="link-btn" onclick="closePreviewBox('${boxId}')">${closeLabel}</button>
  `;
}

function previewDataset() {
  return runPreview("/api/preview", "preview-result", {}, "Close preview");
}

function previewMask() {
  return runPreview("/api/preview-mask", "preview-mask-result", { mask: buildMaskConfig() }, "Close mask preview");
}

// ---------- init ----------

document.addEventListener("DOMContentLoaded", () => {
  wireConditionalFields();
  loadPackages();
  $("preview-btn").addEventListener("click", previewDataset);
  $("preview-mask-btn").addEventListener("click", previewMask);
  $("run-btn").addEventListener("click", startRun);
  $("progress-toggle").addEventListener("click", () => {
    setProgressCollapsed(!$("progress-list").classList.contains("hidden"));
  });
});
