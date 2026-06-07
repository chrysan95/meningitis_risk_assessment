const CONFIG = JSON.parse(document.getElementById("app-config").textContent);
const FIELD_BY_KEY = {};
CONFIG.fields.forEach((f) => (FIELD_BY_KEY[f.key] = f));

const RISK_COLOR = { Low: "#4fc4a3", Moderate: "#efa85f", High: "#df5b54" };
const RISK_CLASS = { Low: "r-low", Moderate: "r-moderate", High: "r-high" };

/* ---------- helpers ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("error", isError);
  t.classList.add("show");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("show"), 3200);
}

function fmtNum(n) {
  return Number(n).toLocaleString("en-US");
}

/* ============================================================
   Tab switching
   ============================================================ */
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("is-active"));
    tab.classList.add("is-active");
    const target = tab.dataset.tab;
    $$(".view").forEach((v) =>
      v.classList.toggle("is-hidden", v.dataset.view !== target)
    );
  });
});

/* ============================================================
   Toggle buttons (gender, pathogen)
   ============================================================ */
$$(".toggle").forEach((group) => {
  group.addEventListener("click", (e) => {
    const btn = e.target.closest(".toggle-btn");
    if (!btn) return;
    $$(".toggle-btn", group).forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
  });
});
function toggleValue(name) {
  const active = $(`[data-toggle="${name}"] .toggle-btn.is-active`);
  return active ? active.dataset.value : "";
}

/* ============================================================
   SINGLE PATIENT
   ============================================================ */
const singleForm = $("#single-form");

/* live out-of-range hinting (informational, never blocks) */
singleForm.addEventListener("input", (e) => {
  const input = e.target;
  if (input.tagName !== "INPUT" || input.type !== "number") return;
  const f = FIELD_BY_KEY[input.name];
  const hint = $(`[data-hint-for="${input.name}"]`);
  input.classList.remove("is-error");
  if (hint) hint.classList.remove("is-error");
  if (!f || !hint || input.value === "") {
    if (hint) hint.classList.remove("out-of-range");
    return;
  }
  const v = parseFloat(input.value);
  const outOfNormal = !isNaN(v) && (v < f.low || v > f.high);
  hint.classList.toggle("out-of-range", outOfNormal);
});

function collectSingle() {
  const data = { errors: [], values: {} };
  // patient id (optional)
  data.values.patient_id = singleForm.patient_id.value.trim();

  // age
  const ageVal = singleForm.age.value.trim();
  const ageNum = parseFloat(ageVal);
  if (ageVal === "" || isNaN(ageNum) || ageNum < CONFIG.age.min || ageNum > CONFIG.age.max) {
    data.errors.push("age");
  } else {
    data.values.age = ageNum;
  }

  // numeric lab fields
  CONFIG.fields.forEach((f) => {
    const raw = singleForm[f.key].value.trim();
    const num = parseFloat(raw);
    if (raw === "" || isNaN(num) || num < f.min || num > f.max) {
      data.errors.push(f.key);
    } else {
      data.values[f.key] = num;
    }
  });

  // gender, pathogen, diagnosis
  const gender = toggleValue("gender");
  if (!gender) data.errors.push("gender"); else data.values.gender = gender;

  const pathogen = toggleValue("pathogen_present");
  if (!pathogen) data.errors.push("pathogen_present"); else data.values.pathogen_present = pathogen;

  const diag = singleForm.diagnosis.value;
  if (!diag) data.errors.push("diagnosis"); else data.values.diagnosis = diag;

  return data;
}

function markErrors(keys) {
  // clear
  $$("#single-form input").forEach((i) => i.classList.remove("is-error"));
  $$("#single-form .field-hint").forEach((h) => h.classList.remove("is-error"));
  keys.forEach((k) => {
    const input = singleForm[k];
    if (input && input.classList) input.classList.add("is-error");
    const hint = $(`[data-hint-for="${k}"]`);
    if (hint) hint.classList.add("is-error");
  });
}

singleForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const { errors, values } = collectSingle();
  if (errors.length) {
    markErrors(errors);
    const labels = errors.map((k) => (FIELD_BY_KEY[k] ? FIELD_BY_KEY[k].label : k));
    toast("Please correct: " + labels.join(", "), true);
    return;
  }
  markErrors([]);

  const btn = $("#single-run");
  btn.disabled = true;
  const orig = btn.innerHTML;
  btn.innerHTML = "Analysing…";

  try {
    const res = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    const json = await res.json();
    if (!json.ok) {
      markErrors(json.errors || []);
      toast("Validation failed on the server.", true);
      return;
    }
    renderSingleResult(json);
  } catch (err) {
    toast("Could not reach the prediction service.", true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
});

$("#single-clear").addEventListener("click", () => {
  singleForm.reset();
  $$("#single-form input").forEach((i) => i.classList.remove("is-error"));
  $$("#single-form .field-hint").forEach((h) => h.classList.remove("is-error", "out-of-range"));
  // reset toggles to defaults (Male active, pathogen none)
  $$('[data-toggle="gender"] .toggle-btn').forEach((b, i) => b.classList.toggle("is-active", i === 0));
  $$('[data-toggle="pathogen_present"] .toggle-btn').forEach((b) => b.classList.remove("is-active"));
  renderSingleEmpty();
});

let lastSingle = null;

function renderSingleEmpty() {
  $("#single-result-body").innerHTML = `
    <div class="empty-state" id="single-empty">
      <svg viewBox="0 0 24 24" width="58" height="58" fill="none" stroke="#9fc3c0" stroke-width="1.5"><path d="M6 3v6a5 5 0 0 0 10 0V3"/><path d="M6 3H4m12 0h2M11 19a4 4 0 0 0 8 0v-3"/><circle cx="19" cy="13" r="2.5"/></svg>
      <p class="empty-title">Enter all lab values and click predict</p>
      <p class="empty-sub">Results include risk level, model confidence, class probabilities and AI-generated clinical insights.</p>
    </div>`;
}

function renderSingleResult(data) {
  lastSingle = data;
  const { result, insights } = data;
  const color = RISK_COLOR[result.risk];
  const order = ["Low", "Moderate", "High"];
  const pid = data.patient_id || "—";

  const probRows = order
    .map((name) => {
      const pct = result.probabilities[name];
      const isPred = name === result.risk;
      return `
        <div class="prob-row ${isPred ? "is-pred" : ""}">
          <span class="p-name">${name}</span>
          <span class="prob-track"><span class="prob-fill" style="width:${pct}%;background:${RISK_COLOR[name]}"></span></span>
          <span class="p-val">${pct}%</span>
        </div>`;
    })
    .join("");

  const recItems = insights.recommendations
    .map((r) => `<li>${escapeHtml(r)}</li>`)
    .join("");

  $("#single-result-body").innerHTML = `
    <p class="result-pid-label">Patient ID</p>
    <p class="result-pid">${escapeHtml(pid)}</p>

    <div class="risk-ring" style="border-color:${color}">
      <span class="ring-label">Risk Level</span>
      <span class="ring-value" style="color:${color}">${result.risk}</span>
    </div>
    <p class="confidence-line">Confidence: <strong>${result.confidence}%</strong></p>

    <div class="prob-list">${probRows}</div>

    <button class="btn btn-ghost export-single" id="export-single">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3v12m0 0-4-4m4 4 4-4M5 21h14"/></svg>
      Export result
    </button>

    <div class="insights-head">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#4d97c4" stroke-width="1.6"><path d="M9 3v6l-4.5 8A2 2 0 0 0 6.3 20h11.4a2 2 0 0 0 1.8-3L15 9V3M8 3h8"/></svg>
      <h3>AI Generated Insights</h3>
    </div>
    <p class="insights-summary">${escapeHtml(insights.summary)}</p>
    <ul class="insights-list">${recItems}</ul>
    <p class="insight-source">Source: ${insights.source === "gemini" ? "Google AI Studio (Gemini)" : "rule-based clinical reference"}</p>

    <div class="disclaimer">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#efa85f" stroke-width="1.8"><path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v5M12 18h.01"/></svg>
      <span><strong>For research and decision support only.</strong> Does not replace clinical diagnosis.</span>
    </div>`;

  $("#export-single").addEventListener("click", exportSingle);
}

function exportSingle() {
  if (!lastSingle) return;
  const r = lastSingle.result;
  const rows = [
    ["patient_id", lastSingle.patient_id || ""],
    ["risk_level", r.risk],
    ["confidence_pct", r.confidence],
    ["prob_low", r.probabilities.Low],
    ["prob_moderate", r.probabilities.Moderate],
    ["prob_high", r.probabilities.High],
    ["high_risk_flag", r.risk === "High" ? "YES" : "NO"],
    ["insight_summary", lastSingle.insights.summary],
  ];
  lastSingle.insights.recommendations.forEach((rec, i) =>
    rows.push([`recommendation_${i + 1}`, rec])
  );
  downloadCsv(
    rows.map((r) => r.map(csvCell).join(",")).join("\n"),
    `prediction_${lastSingle.patient_id || "patient"}.csv`
  );
}

/* ============================================================
   BATCH UPLOAD
   ============================================================ */
const dropzone = $("#dropzone");
const csvInput = $("#csv-input");
let chosenFile = null;
let batchData = null;
let activeFilter = "ALL";
let searchTerm = "";
let currentPage = 1;
const PAGE_SIZE = 10;

$("#download-template").addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  window.location = "/api/template";
});

["dragover", "dragenter"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  })
);
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) setFile(file);
});
csvInput.addEventListener("change", () => {
  if (csvInput.files[0]) setFile(csvInput.files[0]);
});

function setFile(file) {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    toast("Please select a .csv file.", true);
    return;
  }
  chosenFile = file;
  $("#dz-filename").textContent = file.name;
  $("#dz-default").classList.add("is-hidden");
  $("#dz-filled").classList.remove("is-hidden");
  $("#batch-run").disabled = false;
}

$("#batch-clear").addEventListener("click", resetBatch);
$("#new-upload").addEventListener("click", resetBatch);

function resetBatch() {
  chosenFile = null;
  batchData = null;
  csvInput.value = "";
  $("#dz-filled").classList.add("is-hidden");
  $("#dz-default").classList.remove("is-hidden");
  $("#batch-run").disabled = true;
  $("#batch-input-state").classList.remove("is-hidden");
  $("#batch-results-state").classList.add("is-hidden");
}

$("#batch-run").addEventListener("click", async () => {
  if (!chosenFile) return;
  const btn = $("#batch-run");
  btn.disabled = true;
  const orig = btn.innerHTML;
  btn.innerHTML = "Processing…";

  const fd = new FormData();
  fd.append("file", chosenFile);
  try {
    const res = await fetch("/api/predict-batch", { method: "POST", body: fd });
    const json = await res.json();
    if (!json.ok) {
      toast(json.error || "Upload failed.", true);
      return;
    }
    batchData = json;
    activeFilter = "ALL";
    searchTerm = "";
    currentPage = 1;
    $("#patient-search").value = "";
    showBatchResults();
  } catch (err) {
    toast("Could not reach the prediction service.", true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
});

function showBatchResults() {
  $("#batch-input-state").classList.add("is-hidden");
  $("#batch-results-state").classList.remove("is-hidden");

  $("#result-filename").textContent = batchData.filename;
  const errs = batchData.counts.Errors;
  $("#result-stats").innerHTML =
    `${batchData.processed} rows processed` +
    (errs ? ` &middot; <span class="err">${errs} rows flagged error</span>` : "");

  renderStatCards();
  renderDonut();
  renderTable();
  fetchBatchSummary();
}

function fetchBatchSummary() {
  const body = $("#batch-summary-body");
  body.innerHTML =
    '<div class="summary-loading"><span class="spinner"></span>' +
    "<span>Generating cohort summary from aggregate results&hellip;</span></div>";

  fetch("/api/summarize-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: batchData.filename,
      processed: batchData.processed,
      counts: batchData.counts,
      percentages: batchData.percentages,
    }),
  })
    .then((r) => r.json())
    .then((j) => {
      if (!j.ok) throw new Error("summary failed");
      renderBatchSummary(j.summary);
    })
    .catch(() => {
      $("#batch-summary-body").innerHTML =
        '<p class="insights-summary">Cohort summary unavailable right now.</p>';
    });
}

function renderBatchSummary(s) {
  const recItems = s.recommendations.map((r) => `<li>${escapeHtml(r)}</li>`).join("");
  $("#batch-summary-body").innerHTML = `
    <p class="insights-summary">${escapeHtml(s.summary)}</p>
    <ul class="insights-list">${recItems}</ul>
    <p class="insight-source">Source: ${
      s.source === "gemini" ? "Google AI Studio (Gemini)" : "rule-based clinical reference"
    }</p>`;
}

function renderStatCards() {
  const c = batchData.counts;
  const cards = [
    { key: "ALL", label: "All", num: batchData.processed, cls: "sc-all" },
    { key: "High", label: "High Risk", num: c.High, cls: "sc-high" },
    { key: "Moderate", label: "Moderate Risk", num: c.Moderate, cls: "sc-moderate" },
    { key: "Low", label: "Low Risk", num: c.Low, cls: "sc-low" },
    { key: "Errors", label: "Errors", num: c.Errors, cls: "sc-errors" },
  ];
  $("#stat-cards").innerHTML = cards
    .map(
      (s) => `
      <div class="stat-card ${s.cls} ${activeFilter === s.key ? "is-active" : ""}" data-filter="${s.key}">
        <div class="sc-label">${s.label}</div>
        <div class="sc-num">${s.num}</div>
      </div>`
    )
    .join("");
  $$("#stat-cards .stat-card").forEach((card) =>
    card.addEventListener("click", () => {
      activeFilter = card.dataset.filter;
      currentPage = 1;
      renderStatCards();
      renderTable();
    })
  );
}

function renderDonut() {
  const p = batchData.percentages;
  const segs = [
    { v: p.Low, c: RISK_COLOR.Low },
    { v: p.Moderate, c: RISK_COLOR.Moderate },
    { v: p.High, c: RISK_COLOR.High },
  ];
  const R = 15.9155; // circumference 100
  let offset = 25; // start at top
  let svg = `<circle cx="21" cy="21" r="${R}" fill="none" stroke="#f0ece8" stroke-width="6"/>`;
  segs.forEach((s) => {
    if (s.v <= 0) return;
    svg += `<circle cx="21" cy="21" r="${R}" fill="none" stroke="${s.c}" stroke-width="6"
      stroke-dasharray="${s.v} ${100 - s.v}" stroke-dashoffset="${offset}"/>`;
    offset -= s.v;
  });
  $("#donut").innerHTML = svg;
  $("#donut-legend").innerHTML = `
    <div><span class="leg-name">Low</span><span class="leg-val">${p.Low}%</span></div>
    <div><span class="leg-name">Moderate</span><span class="leg-val">${p.Moderate}%</span></div>
    <div><span class="leg-name">High</span><span class="leg-val">${p.High}%</span></div>`;
}

function filteredRows() {
  let rows = batchData.results;
  if (activeFilter === "Errors") rows = rows.filter((r) => r.error);
  else if (activeFilter !== "ALL") rows = rows.filter((r) => r.risk === activeFilter);
  if (searchTerm) {
    const q = searchTerm.toLowerCase();
    rows = rows.filter((r) => String(r.patient_id).toLowerCase().includes(q));
  }
  return rows;
}

function renderTable() {
  const rows = filteredRows();
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * PAGE_SIZE;
  const pageRows = rows.slice(start, start + PAGE_SIZE);

  $("#result-tbody").innerHTML = pageRows
    .map((r) => {
      if (r.error) {
        return `<tr class="row-error">
          <td class="td-pid">${escapeHtml(r.patient_id)}</td>
          <td colspan="5"><span class="err-msg">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16h.01"/></svg>
            ${escapeHtml(r.error)}</span></td>
        </tr>`;
      }
      return `<tr>
        <td class="td-pid">${escapeHtml(r.patient_id)}</td>
        <td>${r.age}</td>
        <td>${escapeHtml(r.gender)}</td>
        <td class="td-result ${RISK_CLASS[r.risk]}">${r.risk}</td>
        <td>
          <div class="conf-cell">
            <span class="conf-track"><span class="conf-fill" style="width:${r.confidence}%;background:${RISK_COLOR[r.risk]}"></span></span>
            <span class="conf-pct">${r.confidence}%</span>
          </div>
        </td>
        <td>${r.flag ? `<svg class="flag-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 21V4m0 0 9 1.5L20 4v10l-6 1.5L5 14"/></svg>` : ""}</td>
      </tr>`;
    })
    .join("");

  if (!pageRows.length) {
    $("#result-tbody").innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:34px">No matching patients.</td></tr>`;
  }

  $("#showing-label").textContent = `Showing ${pageRows.length} of ${rows.length} results`;
  renderPagination(totalPages);
}

function renderPagination(totalPages) {
  let html = "";
  for (let p = 1; p <= totalPages; p++) {
    html += `<button class="page-btn ${p === currentPage ? "is-active" : ""}" data-page="${p}">${p}</button>`;
  }
  html += `<button class="page-btn" data-page="next" ${currentPage >= totalPages ? "disabled" : ""}>
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="m9 6 6 6-6 6"/></svg></button>`;
  $("#pagination").innerHTML = html;
  $$("#pagination .page-btn").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.dataset.page === "next") currentPage = Math.min(totalPages, currentPage + 1);
      else currentPage = parseInt(b.dataset.page, 10);
      renderTable();
    })
  );
}

$("#patient-search").addEventListener("input", (e) => {
  searchTerm = e.target.value.trim();
  currentPage = 1;
  renderTable();
});

$("#batch-export").addEventListener("click", () => {
  if (!batchData) return;
  const header = [
    "patient_id", "age", "gender", "risk_level", "confidence_pct",
    "prob_low", "prob_moderate", "prob_high", "high_risk_flag", "error",
  ];
  const lines = [header.join(",")];
  batchData.results.forEach((r) => {
    if (r.error) {
      lines.push([r.patient_id, "", "", "", "", "", "", "", "", r.error].map(csvCell).join(","));
    } else {
      lines.push(
        [
          r.patient_id, r.age, r.gender, r.risk, r.confidence,
          r.probabilities.Low, r.probabilities.Moderate, r.probabilities.High,
          r.flag ? "YES" : "NO", "",
        ].map(csvCell).join(",")
      );
    }
  });
  downloadCsv(lines.join("\n"), `batch_results_${batchData.filename || "export"}.csv`);
});

/* ============================================================
   small utilities
   ============================================================ */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}
function csvCell(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function downloadCsv(content, filename) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  toast("Result exported.");
}
