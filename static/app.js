let savedFunds = {};
let lastResult = null;
let lastPurchaseResult = null;
let analyzeController = null;
let purchaseController = null;
let analyzeLoading = false;
let purchaseLoading = false;
let analyzeFundInfo = null;
let purchaseFundInfo = null;

const form = document.querySelector("#fundForm");
const purchaseForm = document.querySelector("#purchaseForm");
const statusPill = document.querySelector("#statusPill");
const emptyState = document.querySelector("#emptyState");
const resultView = document.querySelector("#resultView");
const resultStack = document.querySelector(".result-stack");

function byId(id) {
  return document.getElementById(id);
}

function numberOrNull(value) {
  if (value === "" || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

const ESCAPE_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ESCAPE_MAP[c]);
}

function fmtPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  return `${num > 0 ? "+" : ""}${num.toFixed(digits)}%`;
}

function fmtMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function fmtNumber(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function pctColor(value) {
  const num = Number(value || 0);
  if (num > 0) return "#e24d5c";
  if (num < 0) return "#12a579";
  return "#7d8794";
}

function signalSourceLabel(value) {
  if (value === "nav_signal") return "手工/截图估值";
  if (value === "fund_platform") return "基金平台估值";
  if (value === "holdings") return "披露持仓估算";
  return value || "-";
}

function setStatus(text, type = "") {
  statusPill.textContent = text;
  statusPill.className = `server-pill ${type}`;
}

function syncStatusPill() {
  const activeTab = document.querySelector(".tab-button.active")?.dataset?.tab;
  if (analyzeLoading || purchaseLoading) {
    const isCurrentLoading = activeTab === "strategyPage" ? analyzeLoading : purchaseLoading;
    const currentInfo = activeTab === "strategyPage" ? analyzeFundInfo : purchaseFundInfo;
    if (isCurrentLoading) {
      setStatus("分析中", "busy");
    } else {
      setStatus("后台分析中", "busy");
    }
    if (isCurrentLoading && currentInfo) {
      setFundTip(currentInfo.code, currentInfo.name);
    } else {
      setFundTip(null);
    }
  } else {
    setStatus("就绪");
    setFundTip(null);
  }
}

function setFundTip(fundCode, fundName) {
  const tip = byId("fundTip");
  if (fundCode) {
    const display = fundName ? `${fundCode} ${fundName}` : fundCode;
    tip.textContent = `${display} 正在分析中`;
    tip.classList.remove("hidden");
  } else {
    tip.classList.add("hidden");
    tip.textContent = "";
  }
}

function showErrorInState(container, message) {
  if (!container) return;
  container.classList.remove("hidden");
  let el = container.querySelector(".error-text");
  if (!el) {
    el = document.createElement("p");
    el.className = "reason error-text";
    container.appendChild(el);
  }
  el.textContent = message || "操作失败";
}

function renderLoadingState() {
  resultStack.classList.add("is-loading");
  emptyState.classList.add("hidden");
  resultView.classList.remove("hidden");
  resultView.innerHTML = `
    <div class="loading-card">
      <div class="loading-head">
        <div class="skeleton loading-title"></div>
        <div class="skeleton loading-pill"></div>
      </div>
      <div class="loading-metrics">
        <div class="skeleton loading-metric"></div>
        <div class="skeleton loading-metric"></div>
        <div class="skeleton loading-metric"></div>
      </div>
      <div class="skeleton loading-line"></div>
      <div class="skeleton loading-line short"></div>
    </div>
  `;
  byId("signalChart").innerHTML = `
    <div class="loading-chart">
      <div class="skeleton loading-bar"></div>
      <div class="skeleton loading-bar"></div>
      <div class="skeleton loading-bar"></div>
    </div>
  `;
  byId("returnGauge").innerHTML = `
    <div class="loading-chart">
      <div class="skeleton loading-bar"></div>
      <div class="skeleton loading-bar"></div>
    </div>
  `;
  byId("driverBars").innerHTML = `
    <div class="loading-chart">
      <div class="skeleton loading-bar"></div>
      <div class="skeleton loading-bar"></div>
      <div class="skeleton loading-bar"></div>
      <div class="skeleton loading-bar"></div>
    </div>
  `;
  byId("perspectiveList").innerHTML = `
    <div class="loading-chart">
      <div class="skeleton loading-bar"></div>
      <div class="skeleton loading-bar"></div>
      <div class="skeleton loading-bar"></div>
    </div>
  `;
  byId("dataSourceList").innerHTML = "";
  byId("driverCopy").textContent = "";
  byId("signalSource").textContent = "分析中";
  byId("confidenceText").textContent = "分析中";
  byId("coverageText").textContent = "分析中";
  byId("dataSourceCount").textContent = "分析中";
}

function restoreResultTemplate() {
  resultView.innerHTML = `
    <div class="result-head">
      <div>
        <p class="eyebrow" id="fundMeta">基金</p>
        <h2 id="actionTitle">观察</h2>
      </div>
      <div class="result-actions">
        <button class="ghost" id="copyResultBtn" type="button">复制结论</button>
        <span class="action-badge" id="actionBadge">watch</span>
      </div>
    </div>
    <div class="metric-row">
      <article>
        <span id="amountLabel">建议金额</span>
        <strong id="amountValue">0</strong>
      </article>
      <article>
        <span id="ratioLabel">建议比例</span>
        <strong id="ratioValue">0%</strong>
      </article>
      <article>
        <span>预估日涨跌幅</span>
        <strong id="dailyValue">0%</strong>
      </article>
      <article>
        <span>预估持有收益</span>
        <strong id="returnValue">0%</strong>
      </article>
    </div>
    <p class="reason" id="reasonText"></p>
    <div class="diagnostic-row" id="diagnosticRow">
      <span>决策信号 <b id="diagDaily">-</b></span>
      <span>持仓估算 <b id="diagHolding">-</b></span>
      <span>模型差距 <b id="diagGap">-</b></span>
      <span>覆盖 <b id="diagCoverage">-</b></span>
    </div>
  `;
  byId("copyResultBtn").addEventListener("click", copyLastResult);
}

function formPayload() {
  const data = new FormData(form);
  return {
    fundCode: String(data.get("fundCode") || "").trim(),
    fundName: String(data.get("fundName") || "").trim(),
    holdingValue: numberOrNull(data.get("holdingValue")),
    costNav: numberOrNull(data.get("costNav")),
    lastNav: numberOrNull(data.get("lastNav")),
    returnRatePct: numberOrNull(data.get("returnRatePct")),
    navSignalPct: numberOrNull(data.get("navSignalPct")),
    firstTriggerPct: numberOrNull(data.get("firstTriggerPct")),
    mode: data.get("mode") || "auto",
    ignoreTimeGate: data.get("ignoreTimeGate") === "true",
  };
}

function fundRecordPayload() {
  const data = new FormData(form);
  const keys = ["fundCode", "fundName", "holdingValue", "costNav", "lastNav", "returnRatePct", "navSignalPct"];
  return Object.fromEntries(keys.map((key) => [key, String(data.get(key) || "").trim()]));
}

function renderFundOptions(selectedCode = "") {
  const select = document.querySelector("#sampleSelect");
  const rows = Object.values(savedFunds).sort((a, b) => String(a.fundCode).localeCompare(String(b.fundCode)));
  select.innerHTML = `<option value="">快速填入</option>`;
  for (const row of rows) {
    const option = document.createElement("option");
    option.value = row.fundCode;
    option.textContent = `${row.fundCode} ${row.fundName || ""}`.trim();
    select.appendChild(option);
  }
  if (selectedCode) select.value = selectedCode;
  refreshCustomSelect(select);
}

async function loadSavedFunds(preferredCode = "") {
  const response = await fetch("/api/funds");
  const data = await response.json();
  savedFunds = data.funds || {};
  renderFundOptions(preferredCode);
  const firstCode = preferredCode || Object.keys(savedFunds)[0];
  if (firstCode) fillSample(firstCode);
}

function fillSample(code) {
  const sample = savedFunds[code];
  if (!sample) return;
  for (const [key, value] of Object.entries(sample)) {
    const input = form.elements[key];
    if (input) input.value = value;
  }
  document.querySelectorAll("select").forEach(refreshCustomSelect);
}

function closeCustomSelects(except) {
  document.querySelectorAll(".custom-select.open").forEach((node) => {
    if (node !== except) node.classList.remove("open");
  });
}

function refreshCustomSelect(select) {
  if (!select || !select.dataset.enhanced) return;
  const wrapper = select.closest(".custom-select");
  if (!wrapper) return;
  const text = wrapper.querySelector(".custom-select-text");
  const menu = wrapper.querySelector(".custom-select-menu");
  const selected = select.options[select.selectedIndex];
  text.textContent = selected ? selected.textContent : "";
  menu.innerHTML = "";
  [...select.options].forEach((option) => {
    if (option.value === "") return;
    const item = document.createElement("button");
    item.type = "button";
    item.className = `custom-select-option${option.selected ? " active" : ""}`;
    item.textContent = option.textContent;
    item.dataset.value = option.value;
    item.addEventListener("click", () => {
      select.value = option.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      wrapper.classList.remove("open");
      refreshCustomSelect(select);
    });
    menu.appendChild(item);
  });
}

function enhanceSelect(select) {
  if (select.dataset.enhanced) return;
  select.dataset.enhanced = "true";
  select.classList.add("native-select-hidden");

  const wrapper = document.createElement("div");
  wrapper.className = "custom-select";
  select.parentNode.insertBefore(wrapper, select);
  wrapper.appendChild(select);

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "custom-select-trigger";
  trigger.innerHTML = `<span class="custom-select-text"></span><span class="custom-select-arrow"></span>`;

  const menu = document.createElement("div");
  menu.className = "custom-select-menu";
  wrapper.append(trigger, menu);

  trigger.addEventListener("click", () => {
    const willOpen = !wrapper.classList.contains("open");
    closeCustomSelects(wrapper);
    wrapper.classList.toggle("open", willOpen);
  });
  select.addEventListener("change", () => refreshCustomSelect(select));
  refreshCustomSelect(select);
}

document.addEventListener("click", (event) => {
  if (!event.target.closest(".custom-select")) closeCustomSelects();
});

document.querySelectorAll("select").forEach(enhanceSelect);

async function saveCurrentFund() {
  const payload = fundRecordPayload();
  if (!payload.fundCode) {
    setStatus("缺少代码", "error");
    return;
  }
  const saveButton = byId("saveFundBtn");
  saveButton.disabled = true;
  setStatus("保存中", "busy");
  try {
    const response = await fetch("/api/funds/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "保存失败");
    savedFunds = data.funds || {};
    renderFundOptions(payload.fundCode);
    setStatus("已保存");
  } catch (error) {
    setStatus("保存失败", "error");
  } finally {
    saveButton.disabled = false;
  }
}

async function deleteCurrentFund() {
  const fundCode = String(new FormData(form).get("fundCode") || "").trim();
  if (!fundCode) {
    setStatus("缺少代码", "error");
    return;
  }
  if (!window.confirm(`删除 ${fundCode} 的保存信息？`)) return;
  const deleteButton = byId("deleteFundBtn");
  deleteButton.disabled = true;
  setStatus("删除中", "busy");
  try {
    const response = await fetch("/api/funds/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fundCode }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "删除失败");
    savedFunds = data.funds || {};
    renderFundOptions();
    const nextCode = Object.keys(savedFunds)[0];
    if (nextCode) fillSample(nextCode);
    setStatus("已删除");
  } catch (error) {
    setStatus("删除失败", "error");
  } finally {
    deleteButton.disabled = false;
  }
}

function analysisSummary(decision) {
  if (!decision) return "";
  return [
    `${decision.fund_code} ${decision.fund_name || ""}`.trim(),
    `结论：${decision.action || "-"}`,
    `金额：${fmtMoney(decision.amount)} 元，比例：${fmtPct(decision.ratio_pct, 0)}`,
    `持有收益：${fmtPct(decision.estimated_position_return_pct)}`,
    `决策信号：${fmtPct(decision.estimated_fund_pct)}，持仓估算：${fmtPct(decision.holdings_estimated_fund_pct)}`,
    `基金平台估值：${fmtPct(decision.platform_estimated_fund_pct)}，手工估值：${fmtPct(decision.nav_signal_pct)}`,
    `原因：${decision.reason || "-"}`,
    `持仓驱动：${decision.driver_reason || "-"}`,
    `多角度：${(decision.analysis_perspectives || []).map((item) => `${item.angle}：${item.interpretation}`).join("；") || "-"}`,
    `数据源：${(decision.data_sources || []).join("，") || "-"}`,
  ].join("\n");
}

async function copyLastResult() {
  if (!lastResult) {
    setStatus("暂无结果", "error");
    return;
  }
  const text = analysisSummary(lastResult.decision);
  try {
    await navigator.clipboard.writeText(text);
    setStatus("已复制");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    setStatus("已复制");
  }
}

function purchaseAnalysisSummary(analysis) {
  if (!analysis) return "";
  const market = (analysis.market || []).map((m) => `${m.name} ${fmtPct(m.pct)}`).join("，");
  const usProxies = (analysis.usProxies || []).map((u) => `${u.symbol} ${fmtPct(u.pct)}`).join("，");
  const holdings = (analysis.holdings || []).slice(0, 5).map((h) => `${h.name} ${fmtPct(h.contribution_pct)}`).join("，");
  return [
    `${analysis.fundCode} ${analysis.fundName || ""}`.trim(),
    `结论：${analysis.verdict || "-"}（${analysis.score || 0}分）`,
    `主信号：${signalSourceLabel(analysis.signalSource)} ${fmtPct(analysis.estimatedDailyPct)}，预估净值：${fmtNumber(analysis.estimatedNav)}`,
    `平台估值：${fmtPct(analysis.platformEstimatedDailyPct)}，持仓估算：${fmtPct(analysis.holdingsEstimatedDailyPct)}，差距：${fmtPct(analysis.signalGapPct)}`,
    `置信度：${analysis.confidence || "-"}，持仓覆盖：${analysis.coveragePct ? Number(analysis.coveragePct).toFixed(1) + "%" : "-"}`,
    `原因：${analysis.reason || "-"}`,
    `长期判断：${analysis.longTerm || "-"} ${analysis.notes || ""}`.trim(),
    `多角度：${(analysis.analysisPerspectives || []).map((item) => `${item.angle}：${item.interpretation}`).join("；") || "-"}`,
    `数据源：${(analysis.dataSources || []).join("，") || "-"}`,
    `大盘：${market || "-"}`,
    `美股代理：${usProxies || "-"}`,
    `重仓贡献：${holdings || "-"}`,
  ].join("\n");
}

async function copyPurchaseResult() {
  if (!lastPurchaseResult) {
    setStatus("暂无结果", "error");
    return;
  }
  const text = purchaseAnalysisSummary(lastPurchaseResult.analysis);
  try {
    await navigator.clipboard.writeText(text);
    setStatus("已复制");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    setStatus("已复制");
  }
}

function renderSignalChart(decision) {
  const rows = [
    ["主信号", decision.estimated_fund_pct],
    ["持仓估算", decision.holdings_estimated_fund_pct],
    ["基金平台", decision.platform_estimated_fund_pct],
    ["手工估值", decision.nav_signal_pct],
  ].filter((row) => row[1] !== null && row[1] !== undefined);
  const maxAbs = Math.max(1, ...rows.map((row) => Math.abs(Number(row[1]))));
  const width = 560;
  const height = 42 + rows.length * 34;
  const axisX = 330;
  const scale = 150 / maxAbs;
  const bars = rows
    .map(([label, value], index) => {
      const y = 24 + index * 34;
      const num = Number(value);
      const barWidth = Math.abs(num) * scale;
      const x = num >= 0 ? axisX : axisX - barWidth;
      const color = pctColor(num);
      return `
        <text x="0" y="${y + 13}" fill="#5f6e7d" font-size="13">${label}</text>
        <rect x="${x}" y="${y}" width="${barWidth}" height="16" rx="8" fill="${color}" opacity="0.9"></rect>
        <text x="${num >= 0 ? x + barWidth + 8 : x - 8}" y="${y + 13}" text-anchor="${num >= 0 ? "start" : "end"}" fill="${color}" font-size="13" font-weight="650">${fmtPct(num)}</text>
      `;
    })
    .join("");
  byId("signalChart").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="涨跌信号">
      <line x1="${axisX}" y1="22" x2="${axisX}" y2="${height - 16}" stroke="#dfe5ec" stroke-width="1"></line>
      ${bars}
    </svg>
  `;
  byId("signalSource").textContent = signalSourceLabel(decision.signal_source);
}

function renderReturnGauge(decision) {
  const value = Number(decision.estimated_position_return_pct || 0);
  const min = -12;
  const max = 12;
  const clamped = Math.max(min, Math.min(max, value));
  const x = 40 + ((clamped - min) / (max - min)) * 300;
  const color = pctColor(value);
  byId("returnGauge").innerHTML = `
    <svg viewBox="0 0 380 118" role="img" aria-label="收益位置">
      <rect x="40" y="52" width="300" height="16" rx="8" fill="#edf1f5"></rect>
      <rect x="40" y="52" width="112" height="16" rx="8" fill="#e9faf4"></rect>
      <rect x="228" y="52" width="112" height="16" rx="8" fill="#fff0f2"></rect>
      <line x1="190" y1="40" x2="190" y2="82" stroke="#cfd8e3"></line>
      <circle cx="${x}" cy="60" r="13" fill="${color}"></circle>
      <circle cx="${x}" cy="60" r="5" fill="#fff"></circle>
      <text x="40" y="102" fill="#7d8794" font-size="12">-12%</text>
      <text x="190" y="102" text-anchor="middle" fill="#7d8794" font-size="12">0%</text>
      <text x="340" y="102" text-anchor="end" fill="#7d8794" font-size="12">+12%</text>
      <text x="${x}" y="28" text-anchor="middle" fill="${color}" font-size="18" font-weight="700">${fmtPct(value)}</text>
    </svg>
  `;
  byId("confidenceText").textContent = `置信度 ${decision.confidence || "-"}`;
}

function renderDrivers(decision, details) {
  const holdings = (details.holdings || []).filter((item) => item.contribution_pct !== null && item.contribution_pct !== undefined).slice(0, 8);
  const maxAbs = Math.max(0.1, ...holdings.map((item) => Math.abs(Number(item.contribution_pct || 0))));
  byId("coverageText").textContent = decision.coverage_pct
    ? `覆盖 ${Number(decision.coverage_pct).toFixed(1)}%`
    : "-";
  if (!holdings.length) {
    byId("driverBars").innerHTML = `<p class="reason">暂无持仓贡献明细</p>`;
  } else {
    byId("driverBars").innerHTML = holdings
      .map((item) => {
        const contribution = Number(item.contribution_pct || 0);
        const width = Math.max(3, (Math.abs(contribution) / maxAbs) * 50);
        const left = contribution >= 0 ? 50 : 50 - width;
        const cls = contribution >= 0 ? "pos" : "neg";
        return `
          <div class="driver-row" title="${escapeHtml(item.name)} ${escapeHtml(fmtPct(item.stock_pct))} 贡献 ${escapeHtml(fmtPct(contribution))}">
            <div class="driver-name">${escapeHtml(item.name)}</div>
            <div class="driver-track">
              <span class="driver-fill ${cls}" style="left:${left}%;width:${width}%"></span>
            </div>
            <div class="driver-value">${escapeHtml(fmtPct(contribution))}</div>
          </div>
        `;
      })
      .join("");
  }
  byId("driverCopy").textContent = decision.driver_reason || "";
}

function renderPerspectives(decision) {
  const perspectives = decision.analysis_perspectives || [];
  byId("perspectiveList").innerHTML = perspectives.length
    ? perspectives
        .map(
          (item) => `
          <article class="perspective-item">
            <div>
              <strong>${escapeHtml(item.angle || "-")}</strong>
              <span>${escapeHtml(item.source || "-")} · ${escapeHtml(item.confidence || "-")}</span>
            </div>
            <b style="color:${pctColor(item.signal_pct)}">${escapeHtml(item.signal_pct === null || item.signal_pct === undefined ? "-" : fmtPct(item.signal_pct))}</b>
            <p>${escapeHtml(item.interpretation || "")}</p>
          </article>
        `,
        )
        .join("")
    : `<p class="driver-copy">暂无多角度解读。</p>`;

  const sources = decision.data_sources || [];
  byId("dataSourceCount").textContent = sources.length ? `${sources.length} 个数据源` : "无数据源";
  byId("dataSourceList").innerHTML = sources.length
    ? sources.map((source) => `<span>${escapeHtml(source)}</span>`).join("")
    : "";
}

function renderResult(data) {
  resultStack.classList.remove("is-loading");
  restoreResultTemplate();
  lastResult = data;
  const decision = data.decision;
  const details = data.details || {};
  emptyState.classList.add("hidden");
  resultView.classList.remove("hidden");

  const modeClass = decision.mode === "sell" ? "sell" : decision.mode === "buy" ? "buy" : "watch";
  const activeRatio = Math.abs(Number(decision.ratio_pct || 0)) > 0;
  const tradeLabel = modeClass === "buy" ? "买入" : modeClass === "sell" ? "卖出" : "建议";
  const amountValue = byId("amountValue");
  const ratioValue = byId("ratioValue");
  byId("fundMeta").textContent = `${decision.fund_code} ${decision.fund_name || ""}`.trim();
  byId("actionTitle").textContent = decision.action || "观察";
  byId("actionBadge").textContent = decision.mode || "watch";
  byId("actionBadge").className = `action-badge ${modeClass}`;
  byId("amountLabel").textContent = activeRatio ? `${tradeLabel}金额` : "建议金额";
  byId("ratioLabel").textContent = activeRatio ? `${tradeLabel}比例` : "建议比例";
  amountValue.textContent = `${fmtMoney(decision.amount)} 元`;
  ratioValue.textContent = fmtPct(decision.ratio_pct, 0);
  amountValue.className = activeRatio ? `metric-${modeClass}` : "";
  ratioValue.className = activeRatio ? `metric-${modeClass}` : "";
  byId("dailyValue").textContent = fmtPct(decision.estimated_fund_pct);
  byId("dailyValue").style.color = pctColor(decision.estimated_fund_pct);
  byId("returnValue").textContent = fmtPct(decision.estimated_position_return_pct);
  byId("returnValue").style.color = pctColor(decision.estimated_position_return_pct);
  byId("reasonText").textContent = decision.reason || "";
  byId("diagDaily").textContent = fmtPct(decision.estimated_fund_pct);
  byId("diagHolding").textContent = fmtPct(decision.holdings_estimated_fund_pct);
  byId("diagGap").textContent = fmtPct(decision.signal_gap_pct);
  byId("diagCoverage").textContent = decision.coverage_pct ? `${Number(decision.coverage_pct).toFixed(1)}%` : "-";

  renderSignalChart(decision);
  renderReturnGauge(decision);
  renderDrivers(decision, details);
  renderPerspectives(decision);
}

function switchTab(targetId) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === targetId);
  });
  document.querySelectorAll(".tab-page").forEach((page) => {
    page.classList.toggle("active", page.id === targetId);
  });
  syncStatusPill();
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});

function purchasePayload() {
  const data = new FormData(purchaseForm);
  return {
    fundCode: String(data.get("fundCode") || "").trim(),
    fundName: String(data.get("fundName") || "").trim(),
    lastNav: numberOrNull(data.get("lastNav")),
  };
}

function renderPurchaseLoading() {
  byId("purchaseEmpty").classList.add("hidden");
  byId("purchaseResult").classList.remove("hidden");
  byId("purchaseResult").innerHTML = `
    <div class="loading-card">
      <div class="loading-head">
        <div class="skeleton loading-title"></div>
        <div class="skeleton loading-pill"></div>
      </div>
      <div class="loading-metrics">
        <div class="skeleton loading-metric"></div>
        <div class="skeleton loading-metric"></div>
        <div class="skeleton loading-metric"></div>
      </div>
      <div class="skeleton loading-line"></div>
    </div>
  `;
  byId("purchaseMarket").innerHTML = `<div class="loading-chart"><div class="skeleton loading-bar"></div><div class="skeleton loading-bar"></div></div>`;
  byId("purchaseHoldings").innerHTML = `<div class="loading-chart"><div class="skeleton loading-bar"></div><div class="skeleton loading-bar"></div><div class="skeleton loading-bar"></div></div>`;
  byId("purchaseNews").innerHTML = "";
  byId("purchaseLongTerm").innerHTML = `<div class="loading-chart"><div class="skeleton loading-bar"></div><div class="skeleton loading-bar"></div></div>`;
  byId("purchasePerspectives").innerHTML = `<div class="loading-chart"><div class="skeleton loading-bar"></div><div class="skeleton loading-bar"></div></div>`;
  byId("purchaseSources").innerHTML = "";
  byId("purchaseMarketStamp").textContent = "-";
  byId("purchaseLongBadge").textContent = "-";
  byId("purchaseReport").textContent = "-";
  byId("purchaseSourceCount").textContent = "分析中";
}

function restorePurchaseTemplate() {
  byId("purchaseResult").innerHTML = `
    <div class="result-head">
      <div>
        <p class="eyebrow" id="purchaseMeta">基金</p>
        <h2 id="purchaseVerdict">观察</h2>
      </div>
      <div class="result-actions">
        <button class="ghost" id="copyPurchaseBtn" type="button">复制结论</button>
        <span class="action-badge watch" id="purchaseScore">0</span>
      </div>
    </div>
    <div class="metric-row">
      <article>
        <span>预估日涨跌幅</span>
        <strong id="purchaseDaily">-</strong>
      </article>
      <article>
        <span>预估净值</span>
        <strong id="purchaseNav">-</strong>
      </article>
      <article>
        <span>置信度</span>
        <strong id="purchaseConfidence">-</strong>
      </article>
      <article>
        <span>持仓覆盖</span>
        <strong id="purchaseCoverage">-</strong>
      </article>
    </div>
    <p class="reason" id="purchaseReason"></p>
    <div class="diagnostic-row" id="purchaseThemes"></div>
    <div class="diagnostic-row">
      <span>主信号 <b id="purchaseSignalSource">-</b></span>
      <span>平台估值 <b id="purchasePlatform">-</b></span>
      <span>持仓估算 <b id="purchaseHoldingSignal">-</b></span>
      <span>信号差 <b id="purchaseSignalGap">-</b></span>
    </div>
  `;
  byId("copyPurchaseBtn").addEventListener("click", copyPurchaseResult);
}

function renderMarketList(analysis) {
  const marketRows = (analysis.market || []).map((item) => ({
    label: item.name,
    value: item.pct,
    source: "A股",
  }));
  const usRows = (analysis.usProxies || []).map((item) => ({
    label: item.symbol,
    value: item.pct,
    source: "美股/代理",
  }));
  const rows = [...marketRows, ...usRows];
  byId("purchaseMarket").innerHTML = rows.length
    ? rows
        .map(
          (item) => `
          <div class="market-row">
            <span>${escapeHtml(item.label)}</span>
            <b style="color:${pctColor(item.value)}">${escapeHtml(fmtPct(item.value))}</b>
            <em>${escapeHtml(item.source)}</em>
          </div>
        `,
        )
        .join("")
    : `<p class="reason">未取到大盘或美股代理行情。</p>`;
  byId("purchaseMarketStamp").textContent = analysis.checkedAt || "-";
}

function renderPurchaseHoldings(analysis) {
  const holdings = (analysis.holdings || []).slice(0, 8);
  const maxAbs = Math.max(0.1, ...holdings.map((item) => Math.abs(Number(item.contribution_pct || 0))));
  byId("purchaseHoldings").innerHTML = holdings.length
    ? holdings
        .map((item) => {
          const contribution = Number(item.contribution_pct || 0);
          const width = Math.max(3, (Math.abs(contribution) / maxAbs) * 50);
          const left = contribution >= 0 ? 50 : 50 - width;
          const cls = contribution >= 0 ? "pos" : "neg";
          return `
            <div class="driver-row" title="${escapeHtml(item.name)} ${escapeHtml(fmtPct(item.stock_pct))} 贡献 ${escapeHtml(fmtPct(contribution))}">
              <div class="driver-name">${escapeHtml(item.name)}</div>
              <div class="driver-track">
                <span class="driver-fill ${cls}" style="left:${left}%;width:${width}%"></span>
              </div>
              <div class="driver-value">${escapeHtml(fmtPct(contribution))}</div>
            </div>
          `;
        })
        .join("")
    : `<p class="reason">暂无持仓贡献明细。</p>`;
  byId("purchaseReport").textContent = analysis.reportDate ? `披露 ${analysis.reportDate}` : "-";
}

function renderPurchaseNews(analysis) {
  const news = analysis.news || [];
  byId("purchaseNews").innerHTML = news.length
    ? news
        .map(
          (item) => `
          <article class="news-item">
            <div>
              <strong>${escapeHtml(item.title)}</strong>
              <p>${escapeHtml(item.summary || item.date || "新闻摘要暂缺")}</p>
            </div>
            ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">查看</a>` : ""}
          </article>
        `,
        )
        .join("")
    : `<p class="driver-copy">最近新闻源暂不可用，当前结论主要来自持仓、A股大盘和美股代理行情。</p>`;
}

function renderPurchasePerspectives(analysis) {
  const perspectives = analysis.analysisPerspectives || [];
  byId("purchasePerspectives").innerHTML = perspectives.length
    ? perspectives
        .map(
          (item) => `
          <article class="perspective-item">
            <div>
              <strong>${escapeHtml(item.angle || "-")}</strong>
              <span>${escapeHtml(item.source || "-")} · ${escapeHtml(item.confidence || "-")}</span>
            </div>
            <b style="color:${pctColor(item.signal_pct)}">${escapeHtml(item.signal_pct === null || item.signal_pct === undefined ? "-" : fmtPct(item.signal_pct))}</b>
            <p>${escapeHtml(item.interpretation || "")}</p>
          </article>
        `,
        )
        .join("")
    : `<p class="driver-copy">暂无购入信号拆解。</p>`;
  const sources = analysis.dataSources || [];
  byId("purchaseSourceCount").textContent = sources.length ? `${sources.length} 个数据源` : "无数据源";
  byId("purchaseSources").innerHTML = sources.length
    ? sources.map((source) => `<span>${escapeHtml(source)}</span>`).join("")
    : "";
}

function renderPurchaseAnalysis(data) {
  const analysis = data.analysis;
  lastPurchaseResult = data;
  restorePurchaseTemplate();
  byId("purchaseEmpty").classList.add("hidden");
  byId("purchaseResult").classList.remove("hidden");
  const scoreClass = analysis.score >= 68 ? "buy" : analysis.score >= 52 ? "watch" : "sell";
  byId("purchaseMeta").textContent = `${analysis.fundCode} ${analysis.fundName || ""}`.trim();
  byId("purchaseVerdict").textContent = analysis.verdict || "观察";
  byId("purchaseScore").textContent = `${analysis.score || 0}分`;
  byId("purchaseScore").className = `action-badge ${scoreClass}`;
  byId("purchaseDaily").textContent = fmtPct(analysis.estimatedDailyPct);
  byId("purchaseDaily").style.color = pctColor(analysis.estimatedDailyPct);
  byId("purchaseNav").textContent = fmtNumber(analysis.estimatedNav);
  byId("purchaseConfidence").textContent = analysis.confidence || "-";
  byId("purchaseCoverage").textContent = analysis.coveragePct ? `${Number(analysis.coveragePct).toFixed(1)}%` : "-";
  byId("purchaseReason").textContent = analysis.reason || "";
  byId("purchaseSignalSource").textContent = signalSourceLabel(analysis.signalSource);
  byId("purchasePlatform").textContent = fmtPct(analysis.platformEstimatedDailyPct);
  byId("purchaseHoldingSignal").textContent = fmtPct(analysis.holdingsEstimatedDailyPct);
  byId("purchaseSignalGap").textContent = fmtPct(analysis.signalGapPct);
  byId("purchaseThemes").innerHTML = (analysis.themes || []).length
    ? analysis.themes.map((theme) => `<span>${escapeHtml(theme)}</span>`).join("")
    : `<span>主题不足</span>`;
  byId("purchaseLongTerm").textContent = `${analysis.longTerm || ""} ${analysis.notes || ""}`.trim();
  byId("purchaseLongBadge").textContent = analysis.verdict || "-";
  renderMarketList(analysis);
  renderPurchaseHoldings(analysis);
  renderPurchaseNews(analysis);
  renderPurchasePerspectives(analysis);
}

document.querySelector("#sampleSelect").addEventListener("change", (event) => {
  fillSample(event.target.value);
});

byId("saveFundBtn").addEventListener("click", saveCurrentFund);
byId("deleteFundBtn").addEventListener("click", deleteCurrentFund);
byId("copyResultBtn").addEventListener("click", copyLastResult);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = form.querySelector("button[type='submit']");
  if (analyzeController) analyzeController.abort();
  const controller = new AbortController();
  analyzeController = controller;
  submit.disabled = true;
  analyzeLoading = true;
  setStatus("分析中", "busy");
  renderLoadingState();
  const strategyPayload = formPayload();
  analyzeFundInfo = { code: strategyPayload.fundCode, name: strategyPayload.fundName };
  setFundTip(strategyPayload.fundCode, strategyPayload.fundName);
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(strategyPayload),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "分析失败");
    renderResult(data);
    analyzeLoading = false;
    syncStatusPill();
  } catch (error) {
    if (error.name === "AbortError") {
      analyzeLoading = false;
      setStatus("已取消", "error");
      return;
    }
    resultStack.classList.remove("is-loading");
    analyzeLoading = false;
    setStatus("失败", "error");
    resultView.classList.add("hidden");
    emptyState.classList.remove("hidden");
    byId("signalChart").innerHTML = "";
    byId("returnGauge").innerHTML = "";
    byId("driverBars").innerHTML = "";
    byId("perspectiveList").innerHTML = "";
    byId("dataSourceList").innerHTML = "";
    byId("driverCopy").textContent = "";
    byId("signalSource").textContent = "";
    byId("confidenceText").textContent = "";
    byId("coverageText").textContent = "";
    byId("dataSourceCount").textContent = "-";
    showErrorInState(emptyState, error.message || "分析失败");
  } finally {
    if (analyzeController === controller) analyzeController = null;
    submit.disabled = false;
  }
});

purchaseForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = purchaseForm.querySelector("button[type='submit']");
  if (purchaseController) purchaseController.abort();
  const controller = new AbortController();
  purchaseController = controller;
  submit.disabled = true;
  purchaseLoading = true;
  setStatus("分析中", "busy");
  renderPurchaseLoading();
  const purchasePayloadData = purchasePayload();
  purchaseFundInfo = { code: purchasePayloadData.fundCode, name: purchasePayloadData.fundName };
  setFundTip(purchasePayloadData.fundCode, purchasePayloadData.fundName);
  try {
    const response = await fetch("/api/purchase-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(purchasePayloadData),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "分析失败");
    renderPurchaseAnalysis(data);
    purchaseLoading = false;
    syncStatusPill();
  } catch (error) {
    if (error.name === "AbortError") {
      purchaseLoading = false;
      setStatus("已取消", "error");
      return;
    }
    purchaseLoading = false;
    setStatus("失败", "error");
    byId("purchaseResult").classList.add("hidden");
    byId("purchaseEmpty").classList.remove("hidden");
    byId("purchaseMarket").innerHTML = "";
    byId("purchaseHoldings").innerHTML = "";
    byId("purchaseNews").innerHTML = "";
    byId("purchaseLongTerm").textContent = "";
    byId("purchasePerspectives").innerHTML = "";
    byId("purchaseSources").innerHTML = "";
    byId("purchaseMarketStamp").textContent = "-";
    byId("purchaseLongBadge").textContent = "-";
    byId("purchaseReport").textContent = "-";
    byId("purchaseSourceCount").textContent = "-";
    showErrorInState(purchaseEmpty, error.message || "分析失败");
  } finally {
    if (purchaseController === controller) purchaseController = null;
    submit.disabled = false;
  }
});

loadSavedFunds("004241").catch(() => setStatus("加载失败", "error"));
