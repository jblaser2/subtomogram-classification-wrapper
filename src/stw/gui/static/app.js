const $ = (id) => document.getElementById(id);

let currentRunId = null;
let currentEventSource = null;
const jobRows = {}; // "package|k|seed" isn't known until finish_job; keyed by package for the live view

// ---------- package picker ----------

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
    row.innerHTML = `
      <input type="checkbox" value="${pkg.name}" ${pkg.installed ? "checked" : ""}>
      <span class="dot ${dotClass}"></span>
      <span class="pkg-name">${pkg.display_name}</span>
      <span class="pkg-tier">${pkg.tier}</span>
    `;
    container.appendChild(row);
  }
}

// ---------- form field show/hide ----------

function wireConditionalFields() {
  const maskKind = $("f-mask-kind");
  const sync = () => {
    const kind = maskKind.value;
    $("mask-sphere-fields").classList.toggle("hidden", kind !== "sphere");
    $("mask-cylinder-fields").classList.toggle("hidden", kind !== "cylinder");
    $("mask-file-fields").classList.toggle("hidden", kind !== "file");
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

function buildConfig() {
  const mask = { kind: $("f-mask-kind").value, edge: 3.0 };
  if (mask.kind === "sphere") mask.radius = numOrNull("f-mask-radius");
  if (mask.kind === "cylinder") {
    mask.radius = numOrNull("f-mask-radius");
    mask.half_height = numOrNull("f-mask-half-height");
    mask.axis = $("f-mask-axis").value;
  }
  if (mask.kind === "file") mask.path = $("f-mask-path").value;

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

function resetProgressPanel() {
  $("progress-list").innerHTML = "";
  for (const k of Object.keys(jobRows)) delete jobRows[k];
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

function renderResults(report) {
  const body = $("results-body");
  body.className = "";
  const rows = report.results
    .map((r) => {
      const classes = r.n_per_class && Object.keys(r.n_per_class).length
        ? Object.entries(r.n_per_class).map(([c, n]) => `${c}:${n}`).join(", ")
        : "—";
      const viewBtn = r.status === "ok" && r.class_averages && Object.keys(r.class_averages).length
        ? `<button class="link-btn" onclick="viewPanel('${r.package}', ${r.k}, ${r.seed})">class averages</button>`
        : "";
      return `<tr>
        <td>${r.package}</td><td>${r.k}</td><td>${r.seed}</td>
        <td>${statusBadge(r.status)}</td>
        <td>${r.elapsed_sec ? r.elapsed_sec.toFixed(1) + "s" : "—"}</td>
        <td>${classes}</td>
        <td>${r.error ? `<span class="muted">${r.error}</span>` : viewBtn}</td>
      </tr>`;
    })
    .join("");

  body.innerHTML = `
    <table>
      <thead><tr><th>package</th><th>k</th><th>seed</th><th>status</th><th>time</th><th>classes</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div id="panel-view"></div>
    ${report.comparison ? `<h2>Cross-package comparison</h2><img class="panel-img" src="/api/runs/${currentRunId}/comparison.png">` : ""}
  `;
}

function viewPanel(pkg, k, seed) {
  const el = $("panel-view");
  el.innerHTML = `<h2>${pkg} k=${k} seed=${seed}</h2><img class="panel-img" src="/api/runs/${currentRunId}/panel/${pkg}/${k}/${seed}">`;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- init ----------

document.addEventListener("DOMContentLoaded", () => {
  wireConditionalFields();
  loadPackages();
  $("run-btn").addEventListener("click", startRun);
});
