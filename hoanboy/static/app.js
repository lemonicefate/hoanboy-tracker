"use strict";
const $ = (selector) => document.querySelector(selector);
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let csrf = "",
  routeVersion = 0;
let backupFailed = false;
function backupWarning(failed) {
  backupFailed = failed;
  $("#backup-warning").hidden = !failed;
  $("#backup-warning").textContent =
    "資料已保存，但備份失敗。請到備份頁檢查並重新備份；其他操作成功不代表備份成功。";
}
const statusLabel = {
  verified: "已核對",
  unverified: "未驗證",
  missing: "缺值",
  invalid: "解析失敗",
  invalid_time: "時間無效",
};
function notice(message, error = false) {
  $("#notice").textContent = message;
  $("#notice").className = error ? "error" : "";
  $("#notice").hidden = false;
}
async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (response.headers.has("X-Backup-Failed")) backupWarning(true);
  if (path === "/backups" && response.ok)
    backupWarning(method === "GET" ? Boolean(result.error) : false);
  if (response.status === 401) {
    $("#workspace").hidden = true;
    $("#login").hidden = false;
  }
  if (!response.ok) throw new Error(result.error || "操作失敗");
  return result;
}
const head = (kicker, title, description, action = "") =>
  `<div class="page-head"><div><div class="kicker">${kicker}</div><h1>${title}</h1><p class="muted">${description}</p></div>${action}</div>`;
function metric(m, key) {
  const v = m.metrics[key];
  return `<span>${v.value === null ? "—" : escape(v.value)} <small>${escape(v.unit)}</small></span> <span class="badge ${v.status === "verified" ? "" : "warn"}">${statusLabel[v.status]}</span>`;
}
function rows(items, extra = false) {
  return items
    .map(
      (m) =>
        `<tr><td>${escape(m.source_time || "時間缺值")}<div class="small">設備時間未校準</div></td><td>${escape(m.source_identifier || "未提供")} ${m.changed_from ? '<span class="badge warn">同鍵變更</span>' : ""}</td><td>${metric(m, "weight")}</td><td>${metric(m, "bmi")}</td><td>${metric(m, "fat_rate")}</td><td><a href="#measurement/${m.id}">${extra ? "查看明細" : "核對歸檔"} →</a></td></tr>`,
    )
    .join("");
}
const table = (items, extra = false) =>
  items.length
    ? `<div class="panel flush"><table><thead><tr><th>量測時間</th><th>來源識別</th><th>體重</th><th>BMI</th><th>體脂率</th><th></th></tr></thead><tbody>${rows(items, extra)}</tbody></table></div>`
    : '<div class="panel empty">目前沒有量測紀錄。</div>';
async function syncStatus() {
  const s = await api("/sync");
  $("#sync-status").textContent = s.running
    ? "同步進行中"
    : s.last_success
      ? "上次同步 " +
        new Date(s.last_success).toLocaleString("zh-TW", {
          timeZone: "Asia/Taipei",
        })
      : "尚未同步";
  if (s.latest?.status === "failed") notice(s.latest.error, true);
}
async function route() {
  const version = ++routeVersion;
  const [page = "pending", id] = location.hash.slice(1).split("/");
  document
    .querySelectorAll("[data-nav]")
    .forEach((a) =>
      a.classList.toggle(
        "active",
        a.dataset.nav ===
          (page === "patient"
            ? "patients"
            : page === "measurement"
              ? "pending"
              : page),
      ),
    );
  try {
    const renderers = {
      pending: renderPending,
      patients: renderPatients,
      patient: renderPatient,
      measurement: renderMeasurement,
      backups: renderBackups,
    };
    const render = renderers[page];
    if (render) await render(id, version);
    else location.hash = "pending";
  } catch (error) {
    notice(error.message, true);
  }
}
async function renderPending(id, version) {
  let html = "";
  const ignored = id === "ignored";
  const items = await api("/measurements" + (ignored ? "?state=ignored" : ""));
  html =
    head(
      "MEASUREMENT INBOX",
      ignored ? "已忽略量測" : "待歸檔量測",
      "同步後，請核對來源與數值，再選擇病人。",
      `<a class="button quiet" href="#pending${ignored ? "" : "/ignored"}">${ignored ? "返回待歸檔" : "查看已忽略"}</a>`,
    ) +
    `<div class="warning">來源手機僅供提示，不是病歷號。同一來源键的變更版本需重新確認歸屬。</div>` +
    table(items) +
    (items.length === 100 ? '<button id="more">載入更多</button>' : "");
  if (version !== routeVersion) return;
  $("#content").innerHTML = html;
  let last = items.at(-1)?.id;
  if ($("#more"))
    $("#more").onclick = () =>
      action(async () => {
        const more = await api(
          `/measurements?state=${ignored ? "ignored" : "pending"}&before=${last}`,
        );
        if (version !== routeVersion) return;
        $("tbody").insertAdjacentHTML("beforeend", rows(more));
        last = more.at(-1)?.id;
        $("#more").hidden = more.length < 100;
      });
}

async function renderPatients(id, version) {
  let html = "";
  html =
    head(
      "PATIENT DIRECTORY",
      "病人與追蹤",
      "以病歷號管理病人，依量測時間追蹤變化。",
    ) +
    `<div class="panel"><form id="patient-form"><h2>建立病人</h2>${patientFields()}<button>建立病人</button></form></div><div class="toolbar"><input id="search" aria-label="搜尋病人" placeholder="病歷號、姓名或手機"><button id="search-button">搜尋</button><span class="small">每次最多 100 筆；可輸入關鍵字縮小範圍。</span></div><div id="patient-list"></div>`;
  if (version !== routeVersion) return;
  $("#content").innerHTML = html;
  let searchVersion = 0;
  const search = async () => {
    const currentSearch = ++searchVersion;
    const patients = await api(
      "/patients?q=" + encodeURIComponent($("#search").value),
    );
    if (version !== routeVersion || currentSearch !== searchVersion) return;
    $("#patient-list").innerHTML = patientTable(patients);
  };
  $("#search-button").onclick = () => action(search);
  $("#search").onkeydown = (e) => {
    if (e.key === "Enter") action(search);
  };
  $("#patient-form").onsubmit = (e) => {
    e.preventDefault();
    action(async () => {
      const p = await api(
        "/patients",
        "POST",
        Object.fromEntries(new FormData(e.target)),
      );
      location.hash = "patient/" + p.id;
    });
  };
  await search();
}

async function renderPatient(id, version) {
  let html = "";
  const p = await api("/patients/" + id);
  const latest = p.latest;
  html =
    head(
      "PATIENT TIMELINE",
      escape(p.patient.name),
      `病歷號 ${escape(p.patient.mrn)} · ${escape(p.patient.phone || "未填手機")}`,
      '<a class="button quiet" href="#patients">返回病人列表</a>',
    ) +
    `<div class="cards">${["weight", "bmi", "fat_rate"].map((k) => `<div class="metric"><small>${{ weight: "最新體重", bmi: "最新 BMI", fat_rate: "最新體脂率" }[k]}</small><b>${latest ? metric(latest, k) : "—"}</b><small>${latest ? escape(latest.source_time) : "尚無有效時間量測"}</small></div>`).join("")}</div><div class="chart-row">${["weight", "fat_rate"].map((k) => `<section class="panel"><h2>${k === "weight" ? "體重 kg" : "體脂率 %"}</h2><div id="chart-${k}"></div><p class="small">較首次 ${p.differences[k].first ?? "—"} · 較前次 ${p.differences[k].previous ?? "—"}</p></section>`).join("")}</div><p class="small">僅已核對欄位進入正式曲線。缺值／未驗證保留空點；設備時鐘與時區仍待校準。</p><h2>歷次量測 <span class="badge">${p.measurements.length}</span></h2>${table(p.measurements, true)}<details class="panel"><summary>修改病人資料</summary><form id="edit-patient">${patientFields(p.patient)}<button>保存修改</button><p class="small">已保存報告維持原版本，不隨姓名或手機修改。</p></form></details>`;
  if (version !== routeVersion) return;
  $("#content").innerHTML = html;
  for (const k of ["weight", "fat_rate"]) chart($("#chart-" + k), p.trends[k]);
  $("#edit-patient").onsubmit = (e) => {
    e.preventDefault();
    action(async () => {
      await api(
        "/patients/" + id,
        "PUT",
        Object.fromEntries(new FormData(e.target)),
      );
      notice("病人資料已保存。");
      await route();
    });
  };
}

async function renderMeasurement(id, version) {
  let html = "";
  const m = await api("/measurements/" + id);
  html =
    head(
      "MEASUREMENT DETAIL",
      "量測核對",
      `${escape(m.source_time || "時間缺值")} · 來源 ${escape(m.source_identifier || "未提供")}`,
      '<a class="button quiet" href="#pending">返回待歸檔</a>',
    ) +
    `<div class="warning">${m.changed_from ? `來源鍵變更：保留原版本 #${m.changed_from}，本版本需獨立確認。 ` : ""}設備時區、代碼與候選單位未驗證。來源值不等同臨床判定。</div><div class="split"><section class="panel"><h2>人工歸檔</h2><p>目前：${m.patient_id ? `<a href="#patient/${m.patient_id}">病人 #${m.patient_id}</a>` : m.ignored ? "已忽略" : "待歸檔"}</p><p class="small">來源手機候選：${m.candidates.length ? m.candidates.map((p) => `${escape(p.mrn)} ${escape(p.name)}`).join("、") : "無"}。請自行確認，不會自動選取。</p><div class="toolbar"><input id="assign-search" aria-label="搜尋歸檔病人" placeholder="搜尋病歷號、姓名或手機"><button id="assign-search-button" class="quiet">搜尋</button></div><form id="assignment-form"><label>選擇已確認病人<select id="patient-select" required><option value="">請搜尋並選擇病人</option></select></label><button>確認歸檔到所選病人</button></form><p><a href="#patients">建立新病人 →</a></p><div class="actions">${m.patient_id ? '<button id="unassign" class="danger">解除歸檔</button><button id="report">保存／查看報告核對稿</button>' : `<button id="ignore" class="quiet">${m.ignored ? "恢復待歸檔" : "忽略這筆量測"}</button>`}</div></section><section class="panel"><h2>保存資訊</h2><div class="definition"><span>量測版本</span><strong>#${m.id}</strong><span>設備 / 來源鍵</span><strong>${escape(m.device)} / ${escape(m.source_key)}</strong><span>取得時間</span><strong>${escape(m.captured_at)}</strong><span>映射版本</span><strong>${escape(m.mapping_version)}</strong><span>原始輸入</span><strong>年齡 ${escape(m.raw.age ?? "缺值")} · 身高 ${escape(m.raw.height ?? "缺值")} · 性別代碼 ${escape(m.raw.gender ?? "缺值")}</strong></div><p class="small">原始時間保留；時鐘狀態：未驗證。所有更改的來源版本均保留。</p></section></div><section class="panel flush"><table><thead><tr><th>欄位與来源</th><th>數值</th><th>狀態</th><th>候選範圍 / 原始 Level</th></tr></thead><tbody>${Object.entries(
      m.metrics,
    )
      .map(
        ([k, v]) =>
          `<tr><td>${escape(v.label)}<div class="source">${escape(v.source)}</div></td><td>${v.value ?? "—"} ${escape(v.unit)}</td><td>${statusLabel[v.status]}</td><td>${escape(v.minimum ?? "—")} – ${escape(v.maximum ?? "—")} / ${escape(v.level ?? "—")}</td></tr>`,
      )
      .join(
        "",
      )}</tbody></table></section><section class="panel"><h2>歸檔修改紀錄</h2>${m.events.length ? m.events.map((e) => `<p class="small">${escape(e.at)} · ${escape(e.actor)} · ${escape(e.action)} · ${e.before_patient ?? "未歸檔"} → ${e.after_patient ?? "未歸檔"}</p>`).join("") : '<p class="muted">尚無歸檔操作。</p>'}<details><summary>原始欄位快照</summary><pre>${escape(JSON.stringify(m.raw, null, 2))}</pre></details></section>`;
  if (version !== routeVersion) return;
  $("#content").innerHTML = html;
  let searchVersion = 0;
  const search = async () => {
    const currentSearch = ++searchVersion;
    const patients = await api(
      "/patients?q=" + encodeURIComponent($("#assign-search").value),
    );
    if (version !== routeVersion || currentSearch !== searchVersion) return;
    $("#patient-select").innerHTML =
      '<option value="">請確認後選擇</option>' +
      patients
        .map(
          (p) =>
            `<option value="${p.id}">${escape(p.mrn)} · ${escape(p.name)} · ${escape(p.phone)}</option>`,
        )
        .join("");
  };
  const versions = document.createElement("section");
  versions.className = "panel";
  versions.innerHTML = `<h2>欄位核對版本</h2><p class="small">取得原廠核對證據並更新本機設定後，可明確套用到這筆量測。保留原始資料、所有舊核對版本及已保存報告。</p><button id="revalidate" class="quiet">套用目前已核對欄位設定</button>${m.normalizations.map((n) => `<p class="small">${escape(n.at)} · ${escape(n.actor)} · ${escape(n.mapping_version)}</p>`).join("")}<h3>已保存報告</h3>${m.reports.map((r) => `<p class="small">${r.invalidated_at ? "已失效" : `<a href="/api/reports/${r.id}/html">查看核對稿 #${r.id}</a>`} · ${escape(r.created_at)} · ${escape(r.mapping_version)}</p>`).join("") || '<p class="small">尚未保存報告。</p>'}`;
  $("#content").append(versions);
  $("#revalidate").onclick = () =>
    action(async () => {
      const result = await api(`/measurements/${id}/revalidate`, "POST");
      notice(
        result.changed
          ? "已保存新的核對版本，原始資料與舊報告維持不變。"
          : "目前設定與此量測相同，沒有建立新版本。",
      );
      if (version === routeVersion) await route();
    });
  $("#assign-search-button").onclick = () => action(search);
  $("#assign-search").onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      action(search);
    }
  };
  $("#assignment-form").onsubmit = (e) => {
    e.preventDefault();
    action(async () => {
      await api(`/measurements/${id}/assignment`, "POST", {
        patient_id: Number($("#patient-select").value),
      });
      notice("歸檔已保存。");
      await route();
    });
  };
  if ($("#unassign"))
    $("#unassign").onclick = () =>
      action(async () => {
        await api(`/measurements/${id}/assignment`, "POST", {
          patient_id: null,
        });
        await route();
      });
  if ($("#ignore"))
    $("#ignore").onclick = () =>
      action(async () => {
        await api(
          `/measurements/${id}/${m.ignored ? "restore" : "ignore"}`,
          "POST",
        );
        await route();
      });
  if ($("#report"))
    $("#report").onclick = () =>
      action(async () => {
        const r = await api(`/measurements/${id}/reports`, "POST");
        if (backupFailed) {
          notice(
            "報告已存入本機，但备份未完成。請先處理備份，或使用此連結查看：",
            true,
          );
          const link = document.createElement("a");
          link.href = `/api/reports/${r.id}/html`;
          link.textContent = "開啟報告核對稿";
          $("#notice").append(link);
          return;
        }
        location.href = `/api/reports/${r.id}/html`;
      });
}

async function renderBackups(id, version) {
  let html = "";
  const b = await api("/backups");
  html =
    head(
      "DATA CONTINUITY",
      "備份與還原",
      "每個有變更的使用日自動保存，保留最近 30 份。",
      '<button id="backup-now">立即備份</button>',
    ) +
    `<div class="warning">正式使用前，請在設定檔將備份位置設到另一儲存裝置。還原先在隔離位置驗證；啟用需停止程式。</div>${b.error ? `<div class="warning">${escape(b.error)}</div>` : ""}<p class="small">備份位置：${escape(b.directory)}</p><div class="panel flush"><table><thead><tr><th>備份</th><th>大小</th><th>還原驗證</th></tr></thead><tbody>${b.files.map((f) => `<tr><td>${escape(f.name)}</td><td>${Math.round(f.bytes / 1024)} KB</td><td><button class="quiet restore-backup" data-name="${escape(f.name)}">隔離還原並驗證</button></td></tr>`).join("")}</tbody></table>${b.files.length ? "" : '<div class="empty">尚無備份。建立資料後會自動備份。</div>'}</div><div id="restore-result"></div>`;
  if (version !== routeVersion) return;
  $("#content").innerHTML = html;
  $("#backup-now").onclick = () =>
    action(async () => {
      await api("/backups", "POST");
      notice("手動備份已完成並通過完整性檢查。");
      await route();
    });
  document.querySelectorAll(".restore-backup").forEach(
    (button) =>
      (button.onclick = () =>
        action(async () => {
          const r = await api(
            `/backups/${encodeURIComponent(button.dataset.name)}/restore`,
            "POST",
          );
          if (version !== routeVersion) return;
          $("#restore-result").innerHTML =
            `<section class="panel"><h2>隔離還原驗證通過</h2><p>病人 ${r.counts.patients} · 量測 ${r.counts.measurements} · 歸檔事件 ${r.counts.assignment_events} · 報告 ${r.counts.reports}</p><p>目前資料未被覆寫。先停止程式，再於專案資料夾執行：</p><pre>uv run python -m hoanboy restore ${escape(r.id)}</pre><p class="small">若使用自訂資料目錄，指令前需加上 --data-dir 路徑。啟用前會再次備份目前資料。</p></section>`;
        })),
  );
}

function patientFields(p = {}) {
  return `<div class="form-grid">${[
    ["mrn", "病歷號", true],
    ["name", "姓名", true],
    ["phone", "手機（可共用）", false],
  ]
    .map(
      ([key, label, required]) =>
        `<label>${label}<input name="${key}" value="${escape(p[key] || "")}" maxlength="200" ${required ? "required" : ""} autocomplete="off"></label>`,
    )
    .join("")}</div>`;
}
function patientTable(patients) {
  return patients.length
    ? `<div class="panel flush"><table><thead><tr><th>病歷號</th><th>姓名</th><th>手機</th><th></th></tr></thead><tbody>${patients.map((p) => `<tr><td>${escape(p.mrn)}</td><td>${escape(p.name)}</td><td>${escape(p.phone || "—")}</td><td><a href="#patient/${p.id}">查看追蹤 →</a></td></tr>`).join("")}</tbody></table></div>`
    : '<div class="panel empty">沒有符合的病人。</div>';
}
function chart(container, points) {
  const valid = points.filter((p) => p.value !== null);
  if (!valid.length) {
    container.innerHTML = '<div class="empty">尚無已核對的有效數值。</div>';
    return;
  }
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 480 190");
  svg.classList.add("chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "依量測時間繪製，缺值不連線");
  const values = valid.map((p) => p.value),
    min = Math.min(...values),
    max = Math.max(...values),
    lower = min === max ? min - 0.5 : min,
    upper = min === max ? max + 0.5 : max,
    span = upper - lower;
  const times = points.map((p) =>
    Date.parse(String(p.time).replaceAll("/", "-").replace(" ", "T")),
  );
  const finite = times.filter(Number.isFinite),
    start = Math.min(...finite),
    end = Math.max(...finite);
  const node = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text) n.textContent = text;
    svg.append(n);
    return n;
  };
  for (let i = 0; i < 3; i++) {
    let y = 25 + i * 55;
    node("line", { x1: 45, x2: 465, y1: y, y2: y });
    node("text", { x: 0, y: y + 4 }, (upper - (i * span) / 2).toFixed(1));
  }
  let path = "",
    connected = false;
  points.forEach((p, i) => {
    if (p.value === null || !Number.isFinite(times[i])) {
      connected = false;
      return;
    }
    const x =
        45 + (end === start ? 210 : ((times[i] - start) / (end - start)) * 410),
      y = 135 - ((p.value - lower) / span) * 110;
    path += `${connected ? "L" : "M"}${x},${y} `;
    connected = true;
    const circle = node("circle", { cx: x, cy: y, r: 4 });
    const title = document.createElementNS(ns, "title");
    title.textContent = `${p.time}: ${p.value} (#${p.id})`;
    circle.append(title);
  });
  node("path", { d: path });
  node("text", { x: 45, y: 178 }, String(points[0]?.time || ""));
  node(
    "text",
    { x: 465, y: 178, "text-anchor": "end" },
    String(points.at(-1)?.time || ""),
  );
  container.replaceChildren(svg);
}
async function action(fn) {
  try {
    await fn();
  } catch (e) {
    notice(e.message, true);
  }
}
$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  const button = e.target.querySelector("button");
  button.disabled = true;
  try {
    const r = await api("/login", "POST", {
      password: new FormData(e.target).get("password"),
    });
    csrf = r.csrf;
    e.target.reset();
    $("#login-error").textContent = "";
    await enter();
  } catch (e) {
    $("#login-error").textContent = e.message;
  } finally {
    button.disabled = false;
  }
};
$("#logout").onclick = () =>
  action(async () => {
    await api("/logout", "POST");
    csrf = "";
    $("#content").replaceChildren();
    $("#workspace").hidden = true;
    $("#login").hidden = false;
  });
$("#sync-button").onclick = () =>
  action(async () => {
    const button = $("#sync-button");
    button.disabled = true;
    button.textContent = "同步中…";
    try {
      const r = await api("/sync", "POST");
      notice(
        `同步完成：新增 ${r.added}、變更 ${r.updated}、未變 ${r.unchanged}。`,
      );
      await route();
    } finally {
      button.disabled = false;
      button.textContent = "同步設備";
      await syncStatus();
    }
  });
async function enter() {
  $("#login").hidden = true;
  $("#workspace").hidden = false;
  await syncStatus();
  await api("/backups");
  await route();
}
window.addEventListener("hashchange", () => {
  if (csrf) route();
});
(async () => {
  try {
    const r = await api("/session");
    csrf = r.csrf;
    await enter();
  } catch {}
})();
