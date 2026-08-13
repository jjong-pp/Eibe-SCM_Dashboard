const fmtWon = (n) => Math.round(n || 0).toLocaleString("ko-KR") + "원";
const fmtPct = (n, unit = "%") => {
  const abs = Math.abs(n).toFixed(1) + unit;
  return n >= 0 ? `▲ ${abs}` : `▼ ${abs}`;
};

const mixColors = [
  "var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)",
  "var(--chart-6)", "var(--chart-7)", "var(--chart-8)", "var(--chart-9)", "var(--chart-10)",
  "#059669", "#db2777", "#0284c7", "#ca8a04", "#4f46e5",
  "#ea580c", "#0d9488", "#be185d", "#334155", "#65a30d",
];

function resolveMixColors() {
  const styles = getComputedStyle(document.documentElement);
  return mixColors.map((c) => {
    const m = String(c).match(/^var\((--[\w-]+)\)$/);
    if (!m) return c;
    return styles.getPropertyValue(m[1]).trim() || c;
  });
}

let dash = null;
let detailCatalog = {};
let trendChart = null;
let mixChart = null;
let dashboardRequestToken = 0;
let knownBrands = [];
let lastDashBrand = null;

let hubBusyToken = null;
let refreshDashTimer = null;

let trendSelectedLabels = null;
let lastTrendBasis = null;
let trendSeriesUiBound = false;
const dashboardOptions = {
  category: "",
  trendValue: "sales",
  trendUnit: "week",
  trendRange: 12,
  trendBasis: "simplifiedChannel",
  minQtyPortfolio: 5,
  anchor: "",
};

function showHubBusy(title, hint, ownerToken) {
  const modal = document.getElementById("savingModal");
  const titleEl = document.getElementById("savingTitle");
  const hintEl = document.getElementById("savingHint");
  if (titleEl) titleEl.textContent = title || "불러오는 중…";
  if (hintEl) hintEl.textContent = hint || "잠시만 기다려 주세요.";
  if (ownerToken != null) hubBusyToken = ownerToken;
  if (modal) modal.hidden = false;
}

function hideHubBusy(ownerToken) {
  if (ownerToken != null && hubBusyToken !== ownerToken) return;
  hubBusyToken = null;
  const modal = document.getElementById("savingModal");
  if (modal) modal.hidden = true;
}

function forceHideHubBusy() {
  hubBusyToken = null;
  const modal = document.getElementById("savingModal");
  if (modal) modal.hidden = true;
}

window.showHubBusy = showHubBusy;
window.hideHubBusy = hideHubBusy;
window.forceHideHubBusy = forceHideHubBusy;

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function deltaClass(n) {
  if (n > 0) return "up";
  if (n < 0) return "down";
  return "flat";
}

function fmtWowQty(row) {
  if (row.neu != null) {
    return `<span class="delta up">신규 진입 (${row.neu}개)</span>`;
  }
  if (row.wowQty === 0 && row.wowPct === 0) {
    return `<span class="delta flat">- 0개 (0.0%)</span>`;
  }
  const sign = row.wowQty > 0 ? "▲" : "▼";
  const cls = row.wowQty > 0 ? "up" : "down";
  return `<span class="delta ${cls}">${sign} ${Math.abs(row.wowQty)}개 (${Number(row.wowPct).toFixed(1)}%)</span>`;
}

function reasonKindLabel(kind) {
  switch (kind) {
    case "event":
      return "행사";
    case "hypothesis":
      return "가설";
    case "driver":
      return "드라이버";
    case "gap":
      return "공백";
    default: {
      const _exhaustive = kind;
      return _exhaustive || "기타";
    }
  }
}

function openDetail(key) {
  const data = detailCatalog[key];
  if (!data) return;
  document.getElementById("detailTitle").textContent = data.title;
  document.getElementById("detailCol1").textContent = data.col1;
  document.getElementById("detailTableCaption").textContent =
    data.col1 === "채널" ? "채널별 기여 분해" : "세부 채널 기여 분해";

  const insight = data.insight;
  const verdictEl = document.getElementById("insightVerdict");
  const summaryEl = document.getElementById("insightSummary");
  const reasonsEl = document.getElementById("insightReasons");
  const eventsEl = document.getElementById("insightEvents");

  if (insight) {
    verdictEl.textContent = insight.verdict;
    const s = insight.summary || {};
    const wow =
      s.wowPct == null ? "—" : `${s.wowPct >= 0 ? "▲" : "▼"} ${Math.abs(s.wowPct).toFixed(1)}%`;
    summaryEl.innerHTML = `
      <div><dt>금주 수량</dt><dd>${(s.curQty || 0).toLocaleString("ko-KR")}개</dd></div>
      <div><dt>전주 수량</dt><dd>${(s.prevQty || 0).toLocaleString("ko-KR")}개</dd></div>
      <div><dt>WoW</dt><dd class="${deltaClass(s.wowPct || 0)}">${wow}</dd></div>
      <div><dt>금주 매출</dt><dd>${fmtWon(s.curSales)}</dd></div>`;
    reasonsEl.innerHTML = (insight.reasons || [])
      .map(
        (r) => `
        <li class="reason reason-${r.kind || "gap"}">
          <span class="reason-tag">${reasonKindLabel(r.kind)}</span>
          <div>
            <strong>${r.title}</strong>
            <p>${r.detail}</p>
          </div>
        </li>`
      )
      .join("");
    const evs = insight.relatedEvents || [];
    eventsEl.innerHTML = evs.length
      ? evs
          .map(
            (e) => `
          <li class="${e.overlapWeek ? "is-week" : ""}">
            <div class="ev-top">
              <strong>${e.label}</strong>
              ${e.overlapWeek ? '<span class="pill-week">금주 겹침</span>' : '<span class="pill-near">근접</span>'}
            </div>
            <p>${e.product || "전체"} · ${e.period}</p>
            <p class="ev-meta">${e.qty.toLocaleString("ko-KR")}개 · ${fmtWon(e.sales)}${
              e.price ? ` · ${e.price}` : ""
            }${e.gifts ? ` · ${e.gifts}` : ""}</p>
          </li>`
          )
          .join("")
      : `<li class="empty">등록·매칭된 연계 행사가 없습니다.</li>`;
  } else {
    verdictEl.textContent = "상세 인사이트 없음 — 기여 표만 표시합니다.";
    summaryEl.innerHTML = "";
    reasonsEl.innerHTML = "";
    eventsEl.innerHTML = `<li class="empty">연계 행사 데이터 없음</li>`;
  }

  document.getElementById("detailBody").innerHTML = (data.rows || [])
    .map(
      (r) => `
      <tr>
        <td>${r.name}</td>
        <td class="num">${r.qty.toLocaleString("ko-KR")}개</td>
        <td class="num">${fmtWowQty(r)}</td>
        <td class="num">${fmtWon(r.sales)}</td>
      </tr>`
    )
    .join("");
  document.getElementById("detailModal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeDetail() {
  document.getElementById("detailModal").hidden = true;
  if (document.getElementById("calendarModal").hidden) {
    document.body.style.overflow = "";
  }
}

function srcAttrs(key, className) {
  return typeof DashSource !== "undefined" && DashSource.attrs
    ? DashSource.attrs(key, className)
    : className
      ? ` class="${escapeHtml(className)}"`
      : "";
}

function renderAlerts() {
  const box = document.getElementById("alerts");
  const list = dash.alerts?.length
    ? dash.alerts
    : [
        {
          type: "flat",
          text: dash.meta?.category
            ? `「${escapeHtml(dash.meta.category)}」 카테고리에 금주 변동 알림이 없습니다.`
            : "금주 유의미한 변동 알림이 없습니다.",
          key: "",
        },
      ];
  box.innerHTML = list
    .map(
      (a) => `
      <article${srcAttrs("alerts", `alert alert-${a.type === "up" ? "up" : a.type === "down" ? "down" : "flat"}`)}>
        <span class="alert-bar"></span>
        <div class="alert-body">
          <p>${a.text}</p>
          ${a.why ? `<p class="alert-why">${a.why}</p>` : ""}
        </div>
        ${a.key ? `<button type="button" class="link-btn" data-detail="${a.key}">세부보기 →</button>` : "<span></span>"}
      </article>`
    )
    .join("");
  box.querySelectorAll("[data-detail]").forEach((el) => {
    el.addEventListener("click", () => openDetail(el.dataset.detail));
  });
}

function renderCorrelations() {
  const body = document.getElementById("whyBody");
  const meta = document.getElementById("whyMeta");
  if (!body) return;
  const rows = dash.correlations || [];
  if (meta) {
    meta.textContent = `기준주 ${dash.meta?.weekKey || ""} · 금주 겹침 행사 ${dash.meta?.weekEventCount ?? rows.length}건`;
    if (typeof DashSource !== "undefined") DashSource.applyEl(meta, "correlations");
  }
  if (!rows.length) {
    body.innerHTML = `<tr${srcAttrs("correlations")}><td colspan="6">금주와 겹치는 프로모션이 없습니다. 행사 일정 공백이거나 프로모션 시트를 확인해 주세요.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((r) => {
      const clickable = detailCatalog[r.detailKey] ? "mix-row" : "";
      const attr = detailCatalog[r.detailKey] ? ` data-detail="${r.detailKey}"` : "";
      return `
      <tr${srcAttrs("correlations", clickable)}${attr}>
        <td>${r.event}</td>
        <td>${r.product}</td>
        <td>${r.period}</td>
        <td class="num">${r.eventQty.toLocaleString("ko-KR")}개<br><span class="muted">${fmtWon(r.eventSales)}</span></td>
        <td class="num delta ${deltaClass(r.wowQtyPct)}">${fmtPct(r.wowQtyPct)}</td>
        <td class="story-cell">${r.story}</td>
      </tr>`;
    })
    .join("");
  body.querySelectorAll("[data-detail]").forEach((el) => {
    el.addEventListener("click", () => openDetail(el.dataset.detail));
  });
}

function renderKpis() {
  const k = dash.kpi;
  const grid = document.getElementById("kpiGrid");
  const weekTitle = k.weekLabel || "이번 주";
  grid.innerHTML = `
    <article class="kpi kpi-week">
      <div class="kpi-label">
        <span class="kpi-icon" aria-hidden="true">주</span>
        <span>이번 주 매출</span>
        <span class="tag">${weekTitle}</span>
      </div>
      <div class="kpi-value">${fmtWon(k.week.sales).replace("원", "")}<span class="unit">원</span></div>
      <div class="kpi-sub">판매 ${k.week.qty.toLocaleString("ko-KR")}개</div>
      <div class="kpi-delta">
        <span class="${deltaClass(k.weekSalesPct)}">${fmtPct(k.weekSalesPct).replace("▲ ", "▲ 매출 ").replace("▼ ", "▼ 매출 ")}</span>
        <span class="${deltaClass(k.weekQtyPct)}">${fmtPct(k.weekQtyPct).replace("▲ ", "▲ 수량 ").replace("▼ ", "▼ 수량 ")}</span>
      </div>
      <p class="kpi-ref">지난주 ${fmtWon(k.prevWeek.sales)} · ${k.prevWeek.qty.toLocaleString("ko-KR")}개</p>
      <p class="kpi-hint">전주 대비 (WoW)</p>
    </article>
    <article class="kpi kpi-month">
      <div class="kpi-label">
        <span class="kpi-icon" aria-hidden="true">월</span>
        <span>이번 달 매출</span>
        <span class="tag">${k.monthLabel || "MoM"}</span>
      </div>
      <div class="kpi-value">${fmtWon(k.month.sales).replace("원", "")}<span class="unit">원</span></div>
      <div class="kpi-sub">판매 ${k.month.qty.toLocaleString("ko-KR")}개</div>
      <div class="kpi-delta">
        <span class="${deltaClass(k.monthSalesPct)}">${fmtPct(k.monthSalesPct).replace("▲ ", "▲ 매출 ").replace("▼ ", "▼ 매출 ")}</span>
        <span class="${deltaClass(k.monthQtyPct)}">${fmtPct(k.monthQtyPct).replace("▲ ", "▲ 수량 ").replace("▼ ", "▼ 수량 ")}</span>
      </div>
      <p class="kpi-ref">지난달 ${k.fullMonth ? "전체" : "동기간"} ${fmtWon(k.prevMonth.sales)} · ${k.prevMonth.qty.toLocaleString("ko-KR")}개</p>
      <p class="kpi-hint">${k.fullMonth ? "1일~말일 vs 전월 1일~말일" : "1일~오늘 vs 지난달 같은 일수"}</p>
    </article>
    <article class="kpi kpi-momentum">
      <div class="kpi-label">
        <span class="kpi-icon" aria-hidden="true">모</span>
        <span>모멘텀</span>
        <span class="tag">4주 평균 대비</span>
      </div>
      <div class="kpi-value ${k.momentumSales < 0 ? "neg" : ""}">${fmtWon(k.momentumSales).replace("원", "")}<span class="unit">원</span></div>
      <div class="kpi-sub">수량 갭 ${Math.round(k.momentumQty).toLocaleString("ko-KR")}개</div>
      <div class="kpi-delta">
        <span class="${deltaClass(k.momentumSalesPct)}">${fmtPct(k.momentumSalesPct).replace("▲ ", "▲ 매출 ").replace("▼ ", "▼ 매출 ")}</span>
        <span class="${deltaClass(k.momentumQtyPct)}">${fmtPct(k.momentumQtyPct).replace("▲ ", "▲ 수량 ").replace("▼ ", "▼ 수량 ")}</span>
      </div>
      <p class="kpi-ref">4주 평균 ${fmtWon(k.avg4.sales)} · ${Math.round(k.avg4.qty).toLocaleString("ko-KR")}개</p>
      <p class="kpi-hint">이번 주 − 직전 4주 평균</p>
    </article>`;
}

function renderMixTable() {
  const body = document.getElementById("mixBody");
  const mixRows = dash.mixRows || [];
  const mixLabel = document.getElementById("mixWeekLabel");
  if (mixLabel) {
    mixLabel.textContent = `(${dash.meta.weekKey} 기준)`;
    if (typeof DashSource !== "undefined") DashSource.applyEl(mixLabel, "mix");
  }
  if (!mixRows.length) {
    body.innerHTML = `<tr${srcAttrs("mix")}><td colspan="5">선택 조건에 해당하는 채널 매출이 없습니다.</td></tr>`;
    return;
  }
  body.innerHTML = mixRows
    .map((r) => {
      const key = `channel:${r.ch}`;
      const clickable = detailCatalog[key] ? "mix-row" : "";
      const attr = detailCatalog[key] ? ` data-detail="${key}"` : "";
      return `
      <tr${srcAttrs("mix", clickable)}${attr}>
        <td>${r.ch}</td>
        <td class="num">${fmtWon(r.sales)}</td>
        <td class="num">${r.share.toFixed(1)}%</td>
        <td class="num ${deltaClass(r.wow)} delta">${fmtPct(r.wow, "%p")}</td>
        <td class="num ${deltaClass(r.mom)} delta">${fmtPct(r.mom, "%p")}</td>
      </tr>`;
    })
    .join("");
  body.querySelectorAll("[data-detail]").forEach((el) => {
    el.addEventListener("click", () => openDetail(el.dataset.detail));
  });
}

function renderRank(listId, rows) {
  const el = document.getElementById(listId);
  const tipKey = listId === "growthList" ? "portfolioGrowth" : "portfolioDecline";
  if (!rows?.length) {
    el.innerHTML = `<li${srcAttrs(tipKey)}><div class="rank-meta" style="grid-column:1/-1;padding:8px">표시할 항목이 없습니다.</div></li>`;
    return;
  }
  el.innerHTML = rows
    .map((r, i) => {
      const key = `product:${r.name}`;
      const can = !!detailCatalog[key];
      const badge = r.neu ? `<span class="badge-new">신규</span>` : "";
      const delta =
        r.delta == null
          ? `<span class="rank-delta up">신규</span>`
          : `<span class="rank-delta ${deltaClass(r.delta)}">${fmtPct(r.delta)}</span>`;
      const baseClass = can ? "rank-click" : "";
      return `
        <li${srcAttrs(tipKey, baseClass)}${can ? ` data-detail="${key}"` : ""}>
          <span class="rank-no">${i + 1}</span>
          <div>
            <div class="rank-name">${r.name}${badge}</div>
            <div class="rank-meta">${r.qty.toLocaleString("ko-KR")}개 · ${fmtWon(r.sales)}</div>
          </div>
          ${delta}
        </li>`;
    })
    .join("");
  el.querySelectorAll("[data-detail]").forEach((node) => {
    node.addEventListener("click", () => openDetail(node.dataset.detail));
  });
}

function renderEvents() {
  const body = document.getElementById("eventBody");
  const events = dash.events || [];
  if (!events.length) {
    body.innerHTML = `<tr${srcAttrs("roi")}><td colspan="8">프로모션 시트와 raw가 매칭되는 행사가 없습니다.</td></tr>`;
    return;
  }
  body.innerHTML = events
    .map((row) => {
      const lift = row[7];
      const key = `product:${row[2]}`;
      const can = !!detailCatalog[key];
      const baseClass = can ? "mix-row" : "";
      return `
        <tr${srcAttrs("roi", baseClass)}${can ? ` data-detail="${key}"` : ""}>
          <td>${row[0]}</td>
          <td>${row[1]}</td>
          <td>${row[2]}</td>
          <td>${row[3]}</td>
          <td class="num">${row[4]}</td>
          <td class="num">${row[5]}</td>
          <td class="num">${row[6]}</td>
          <td class="num delta ${deltaClass(lift)}">${lift >= 99999 ? "▲ NEW" : fmtPct(lift)}</td>
        </tr>`;
    })
    .join("");
  body.querySelectorAll("[data-detail]").forEach((el) => {
    el.addEventListener("click", () => openDetail(el.dataset.detail));
  });
}

function buildTrendChart() {
  const labels = dash.trend?.labels || [];
  const allSeries = dash.trend?.series || [];
  const basis = dash.trend?.basis || dashboardOptions.trendBasis || "simplifiedChannel";
  if (basis !== lastTrendBasis) {
    lastTrendBasis = basis;
    trendSelectedLabels = null;
  }
  if (!trendSelectedLabels) {
    trendSelectedLabels = defaultTrendSelection(allSeries, basis);
  } else {
    const alive = new Set(allSeries.map((s) => s.label));
    const next = new Set([...trendSelectedLabels].filter((n) => alive.has(n)));
    if (!next.size && allSeries.length) {
      trendSelectedLabels = defaultTrendSelection(allSeries, basis);
    } else {
      trendSelectedLabels = next;
    }
  }
  syncTrendSeriesPanel(allSeries);
  const series = allSeries.filter((s) => trendSelectedLabels.has(s.label));
  if (trendChart) trendChart.destroy();
  const canvas = document.getElementById("trendChart");
  if (!canvas || typeof Chart === "undefined") return;
  const palette = resolveMixColors();
  const many = series.length > 14;
  trendChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: series.map((s, i) => ({
        label: s.label,
        data: s.data,
        borderColor: palette[i % palette.length],
        backgroundColor: palette[i % palette.length],
        borderWidth: 2,
        pointRadius: many ? 0 : 2,
        pointHoverRadius: 4,
        tension: 0.25,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: !many,
          position: "bottom",
          labels: { boxWidth: 12, usePointStyle: true, pointStyle: "circle", font: { family: "Pretendard Variable, Pretendard, sans-serif", size: 11 } },
        },
        tooltip: {
          callbacks: {
            label: (ctx) =>
              `${ctx.dataset.label}: ${
                dash.trend?.value === "qty"
                  ? `${Number(ctx.parsed.y || 0).toLocaleString("ko-KR")}개`
                  : fmtWon(ctx.parsed.y)
              }`,
          },
        },
      },
      scales: {
        x: { grid: { color: "#eef1f4" }, ticks: { font: { family: "JetBrains Mono", size: 10 } } },
        y: {
          grid: { color: "#eef1f4" },
          ticks: {
            font: { family: "JetBrains Mono", size: 10 },
            callback: (v) =>
              dash.trend?.value === "qty"
                ? Number(v).toLocaleString("ko-KR")
                : (v / 1_000_000).toLocaleString("ko-KR") + "M",
          },
        },
      },
    },
  });
}

function defaultTrendSelection(series, basis) {
  const names = (series || []).map((s) => s.label);
  if (!names.length) return new Set();
  const showAll =
    basis === "simplifiedChannel" ||
    basis === "channelType" ||
    basis === "category" ||
    names.length <= 12;
  if (showAll && names.length <= 24) return new Set(names);
  return new Set(names.slice(0, 12));
}

function updateTrendSeriesToggleLabel() {
  const btn = document.getElementById("trendSeriesToggle");
  if (!btn) return;
  const all = dash?.trend?.series || [];
  const n = trendSelectedLabels ? trendSelectedLabels.size : 0;
  if (!all.length) {
    btn.textContent = "항목 없음";
    return;
  }
  if (n === 0) btn.textContent = "선택 없음";
  else if (n === all.length) btn.textContent = `전체 ${n}개`;
  else btn.textContent = `${n} / ${all.length}개`;
}

function syncTrendSeriesPanel(allSeries) {
  const list = document.getElementById("trendSeriesList");
  const hint = document.getElementById("trendSeriesHint");
  if (!list) return;
  const selected = trendSelectedLabels || new Set();
  const palette = resolveMixColors();
  list.innerHTML = (allSeries || [])
    .map((s, i) => {
      const id = `trend-series-${i}`;
      const checked = selected.has(s.label) ? "checked" : "";
      const swatch = palette[i % palette.length];
      return `<label class="series-dd-item" for="${id}">
        <input type="checkbox" id="${id}" data-series="${encodeURIComponent(s.label)}" ${checked} />
        <span class="series-swatch" style="background:${swatch}"></span>
        <span class="series-name">${escapeHtml(s.label)}</span>
      </label>`;
    })
    .join("");
  if (hint) {
    const bits = [];
    if (dash?.trend?.truncated) bits.push("항목이 많아 하위는 「기타(나머지)」로 묶었습니다");
    bits.push(`기준 · ${trendBasisLabel(dash?.trend?.basis)}`);
    hint.textContent = bits.join(" · ");
  }
  updateTrendSeriesToggleLabel();
}

function trendBasisLabel(basis) {
  switch (basis) {
    case "simplifiedChannel":
      return "채널 (주요 + 기타)";
    case "channel":
      return "채널별 (상세)";
    case "channelType":
      return "채널구분별";
    case "lineup":
      return "라인업별";
    case "product":
      return "제품별";
    case "category":
      return "카테고리별";
    default: {
      const _exhaustive = basis;
      return String(_exhaustive || "채널");
    }
  }
}

function setTrendSeriesOpen(open) {
  const panel = document.getElementById("trendSeriesPanel");
  const btn = document.getElementById("trendSeriesToggle");
  if (!panel || !btn) return;
  panel.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}

function bindTrendSeriesUi() {
  if (trendSeriesUiBound) return;
  trendSeriesUiBound = true;
  const toggle = document.getElementById("trendSeriesToggle");
  const panel = document.getElementById("trendSeriesPanel");
  const list = document.getElementById("trendSeriesList");
  toggle?.addEventListener("click", (e) => {
    e.stopPropagation();
    setTrendSeriesOpen(panel?.hidden !== false);
  });
  document.getElementById("trendSeriesAll")?.addEventListener("click", () => {
    const all = dash?.trend?.series || [];
    trendSelectedLabels = new Set(all.map((s) => s.label));
    buildTrendChart();
  });
  document.getElementById("trendSeriesNone")?.addEventListener("click", () => {
    trendSelectedLabels = new Set();
    buildTrendChart();
  });
  document.getElementById("trendSeriesTop")?.addEventListener("click", () => {
    const all = dash?.trend?.series || [];
    trendSelectedLabels = new Set(all.slice(0, 12).map((s) => s.label));
    buildTrendChart();
  });
  list?.addEventListener("change", (e) => {
    const input = e.target;
    if (!(input instanceof HTMLInputElement) || input.type !== "checkbox") return;
    const label = decodeURIComponent(input.dataset.series || "");
    if (!trendSelectedLabels) trendSelectedLabels = new Set();
    if (input.checked) trendSelectedLabels.add(label);
    else trendSelectedLabels.delete(label);
    buildTrendChart();
  });
  document.addEventListener("click", (e) => {
    const dd = document.getElementById("trendSeriesDd");
    if (!dd || dd.contains(e.target)) return;
    setTrendSeriesOpen(false);
  });
}

function initShellChrome() {
  const shell = document.getElementById("shell");
  const collapseBtn = document.getElementById("sidebarCollapseBtn");
  if (!shell) return;


  const applySidebar = (collapsed) => {
    shell.classList.toggle("is-sidebar-collapsed", collapsed);
    if (collapseBtn) {
      collapseBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      collapseBtn.title = collapsed ? "메뉴 펼치기" : "메뉴 접기";
      collapseBtn.textContent = collapsed ? "›" : "‹";
      collapseBtn.setAttribute("aria-label", collapsed ? "메뉴 펼치기" : "메뉴 접기");
    }
  };

  applySidebar(false);
  collapseBtn?.addEventListener("click", () => {
    applySidebar(!shell.classList.contains("is-sidebar-collapsed"));
  });
}

function buildMixChart() {
  const mixRows = dash.mixRows || [];
  if (mixChart) {
    mixChart.destroy();
    mixChart = null;
  }
  const canvas = document.getElementById("mixChart");
  const wrap = canvas?.closest(".donut-wrap") || canvas?.parentElement;
  if (!canvas || typeof Chart === "undefined") return;

  let emptyEl = wrap?.querySelector(".donut-empty");
  if (!mixRows.length) {
    canvas.style.display = "none";
    if (wrap && !emptyEl) {
      emptyEl = document.createElement("div");
      emptyEl.className = "donut-empty";
      emptyEl.textContent = "표시할 채널 매출이 없습니다.";
      wrap.appendChild(emptyEl);
    } else if (emptyEl) {
      emptyEl.hidden = false;
    }
    return;
  }
  canvas.style.display = "block";
  if (emptyEl) emptyEl.hidden = true;

  mixChart = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: mixRows.map((r) => r.ch),
      datasets: [
        {
          data: mixRows.map((r) => r.sales),
          backgroundColor: resolveMixColors().slice(0, Math.max(mixRows.length, 1)),
          borderWidth: 2,
          borderColor: "#fff",
          hoverOffset: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "62%",
      layout: { padding: 4 },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const row = mixRows[ctx.dataIndex];
              if (!row) return "";
              return `${row.ch}: ${fmtWon(row.sales)} (${row.share.toFixed(1)}%)`;
            },
          },
        },
      },
      onClick: (_evt, elements) => {
        if (!elements?.length) return;
        const row = mixRows[elements[0].index];
        if (!row) return;
        const key = `channel:${row.ch}`;
        if (detailCatalog[key]) openDetail(key);
      },
    },
  });

  requestAnimationFrame(() => {
    try {
      mixChart?.resize();
    } catch {
      
    }
  });
}

if (typeof window !== "undefined" && !window.__eibeMixChartResizeBound) {
  window.__eibeMixChartResizeBound = true;
  window.addEventListener("resize", () => {
    try {
      mixChart?.resize();
    } catch {
      
    }
  });
}

function renderMeta() {
  const meta = document.getElementById("metaDate");
  if (meta) {
    const m = dash.meta || {};
    const cat = m.category ? ` · 카테고리「${m.category}」` : " · 전체 카테고리";
    const sheet = Number(m.rawSheetCount) || 0;
    const all = Number(m.rawAllCount) || 0;
    const used = Number(m.rawCount) || 0;
    const skipped = Number(m.rawSkipped) || 0;
    const promo = Number(m.promoCount) || 0;
    let rawLabel = `raw 집계 ${used.toLocaleString("ko-KR")}행`;
    if (sheet !== used || all !== used) {
      rawLabel += ` (시트 ${sheet.toLocaleString("ko-KR")} · 출고일OK ${all.toLocaleString("ko-KR")}`;
      if (skipped > 0) rawLabel += ` · 출고일없음 ${skipped.toLocaleString("ko-KR")}`;
      rawLabel += ")";
    }
    meta.textContent = `기준일 ${m.refDate || ""} · ${m.weekKey || ""} (${m.weekRange || ""}) · ${dash.kpi?.monthLabel || ""}${
      m.fullMonth ? " · 월전체" : ""
    } · ${rawLabel}${cat} · promo ${promo}행`;
    if (typeof DashSource !== "undefined") DashSource.applyEl(meta, "meta");
  }
}

function formatMonthAnchorLabel(mKey) {
  const parts = String(mKey || "").split("-M");
  if (parts.length !== 2) return mKey;
  return `${parts[0]}년 ${parseInt(parts[1], 10)}월`;
}

function populateAnchorSelect() {
  const sel = document.getElementById("anchorSelect");
  if (!sel || !dash?.meta) return;
  const monthKeys = dash.meta.monthKeys || [];
  const weekKeys = dash.meta.weekKeys || [];
  const prev = dashboardOptions.anchor || "";
  let html = '<option value="">최신 데이터 (기본)</option>';
  if (monthKeys.length) {
    html +=
      '<optgroup label="월별 (1일~말일 전체 비교)">' +
      monthKeys
        .map((m) => `<option value="month:${escapeHtml(m)}">${escapeHtml(formatMonthAnchorLabel(m))}</option>`)
        .join("") +
      "</optgroup>";
  }
  if (weekKeys.length) {
    html +=
      '<optgroup label="주별">' +
      weekKeys.map((w) => `<option value="week:${escapeHtml(w)}">${escapeHtml(w)}</option>`).join("") +
      "</optgroup>";
  }
  sel.innerHTML = html;
  sel.value = prev;
  if (sel.value !== prev) {
    dashboardOptions.anchor = "";
    sel.value = "";
  }
}

let currentViewBrand =
  typeof SheetSchema !== "undefined" ? SheetSchema.DEFAULT_BRAND_SLUG : "dreame";

let viewMode = "single"; 

function activeBrand() {
  return currentViewBrand;
}

function brandDisplayName(brandId) {
  const brand = knownBrands.find((item) => item.id === brandId);
  const name = brand?.name || brandId;
  return `${String(brand?.slug || brandId || "").toUpperCase()} / ${name}`;
}

async function refreshBrandNav() {
  const nav = document.getElementById("brandNav");
  if (!nav || typeof Repository === "undefined") return;
  const fallback = [
    typeof SheetSchema !== "undefined"
      ? { ...SheetSchema.DEFAULT_BRAND }
      : { id: "dreame", name: "드리미", slug: "dreame" },
  ];

  
  if (!knownBrands.length) {
    knownBrands = fallback.slice();
    nav.innerHTML = knownBrands
      .map(
        (b) => `
      <button type="button" class="nav-item nav-btn nav-brand ${b.id === currentViewBrand ? "is-active" : ""}" data-brand="${b.id}">
        ${b.name}
      </button>`
      )
      .join("");
    nav.querySelectorAll("[data-brand]").forEach((btn) => {
      btn.addEventListener("click", () => selectBrand(btn.dataset.brand));
    });
  }

  try {
    const remote = await Repository.getBrands();
    if (Array.isArray(remote) && remote.length) {
      knownBrands = remote;
      if (!knownBrands.some((b) => b.id === fallback[0].id)) {
        knownBrands = [fallback[0], ...knownBrands];
      }
    } else {
      knownBrands = fallback.slice();
    }
  } catch (error) {
    console.warn("[Dashboard] getBrands failed", error);
    knownBrands = fallback.slice();
  }
  if (!knownBrands.some((b) => b.id === currentViewBrand)) {
    currentViewBrand = knownBrands[0].id;
  }
  nav.innerHTML = knownBrands
    .map(
      (b) => `
      <button type="button" class="nav-item nav-btn nav-brand ${b.id === currentViewBrand && viewMode === "single" ? "is-active" : ""}" data-brand="${b.id}">
        ${b.name}
      </button>`
    )
    .join("");
  nav.querySelectorAll("[data-brand]").forEach((btn) => {
    btn.addEventListener("click", () => selectBrand(btn.dataset.brand));
  });
  document.getElementById("activeBrandLabel").textContent = brandDisplayName(currentViewBrand);
}

function selectBrand(name) {
  viewMode = "single";
  currentViewBrand = name;
  document.getElementById("viewModePill").textContent = "단일 브랜드";
  document.getElementById("activeBrandLabel").textContent = brandDisplayName(name);
  document.getElementById("brandAllBtn")?.classList.remove("is-active");
  refreshBrandNav();
  refreshDashboard();
}

async function refreshDashboard() {
  const requestedBrand = activeBrand();
  const token = ++dashboardRequestToken;
  const meta = document.getElementById("metaDate");
  const heavyLoad = !dash || lastDashBrand !== requestedBrand;
  const cacheAt = Repository._bundleCacheAt?.[requestedBrand] || 0;
  const hasFreshCache =
    Boolean(Repository._bundleCache?.[requestedBrand]) &&
    Date.now() - cacheAt < (Repository.BUNDLE_CACHE_TTL_MS || 120000);
  const showBusy = heavyLoad && !hasFreshCache;
  if (meta) meta.textContent = "loading…";
  if (showBusy) {
    showHubBusy(
      "대시보드 불러오는 중…",
      "시트 데이터를 확인하는 중…",
      token
    );
  }
  try {
    const result = await window.computeDashboardAsync(requestedBrand, dashboardOptions);
    if (token !== dashboardRequestToken || requestedBrand !== activeBrand()) return;
    dash = result;
    lastDashBrand = requestedBrand;
  } catch (error) {
    if (token !== dashboardRequestToken) return;
    console.error("[Dashboard] load failed", error);
    const msg = String(error?.message || error || "");
    const isPerm =
      error?.code === "permission-denied" ||
      /permission|chunks 읽기 권한|Rules/i.test(msg);
    const isLegacy =
      error?.code === "legacy-too-large" || /레거시 행 문서|행=문서/i.test(msg);
    const isTimeout = error?.code === "deadline-exceeded" || /타임아웃/i.test(msg);
    
    dash = window.computeDashboard
      ? window.computeDashboard(requestedBrand, {
          brand: requestedBrand,
          promo: [],
          raw: [],
          channelGroup: [],
          lineup: [],
          channelSetting: [],
        }, dashboardOptions)
      : dash;
    lastDashBrand = requestedBrand;
    if (meta) {
      meta.textContent = isPerm
        ? "권한 오류 · Rules·서버 Auth 확인 (데이터 없음으로 표시)"
        : isLegacy
          ? "레거시 과다 · 엑셀 재업로드 필요"
          : isTimeout
            ? "로드 타임아웃 · 빈 대시보드로 표시"
            : `로드 실패 · ${msg.slice(0, 60)}`;
    }
    if ((isPerm || isLegacy || isTimeout) && !window.__eibeSalesPermAlerted) {
      window.__eibeSalesPermAlerted = true;
      alert("대시보드를 불러오지 못했습니다.\n\n" + msg);
    }
  } finally {
    
    if (token === dashboardRequestToken) forceHideHubBusy();
    else if (showBusy) hideHubBusy(token);
  }
  if (token !== dashboardRequestToken || !dash) return;
  detailCatalog = dash.detailCatalog || {};
  renderAlerts();
  renderCorrelations();
  renderKpis();
  renderMixTable();
  renderRank("growthList", dash.growth);
  renderRank("declineList", dash.decline);
  renderEvents();
  buildTrendChart();
  buildMixChart();
  renderMeta();
  populateAnchorSelect();
  bindDetailUiOnce();
  const categoryFilter = document.getElementById("categoryFilter");
  if (categoryFilter) {
    const selected = dashboardOptions.category;
    categoryFilter.innerHTML =
      `<option value="">전체</option>` +
      (dash.meta.categories || [])
        .map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`)
        .join("");
    categoryFilter.value = selected;
  }
  document.getElementById("activeBrandLabel").textContent = brandDisplayName(activeBrand());
  if (typeof DashSource !== "undefined") DashSource.applyStatic();
}

function scheduleRefreshDashboard(delayMs = 80) {
  if (refreshDashTimer) clearTimeout(refreshDashTimer);
  refreshDashTimer = setTimeout(() => {
    refreshDashTimer = null;
    void refreshDashboard();
  }, delayMs);
}

window.refreshBrandNav = refreshBrandNav;

let detailUiBound = false;
function bindDetailUiOnce() {
  if (detailUiBound) return;
  detailUiBound = true;
  document.getElementById("detailClose").addEventListener("click", closeDetail);
  document.getElementById("detailModal").addEventListener("click", (e) => {
    if (e.target.id === "detailModal") closeDetail();
  });
  document.getElementById("openCalendarBtn").addEventListener("click", () => {
    openCalendar().catch((err) => console.error(err));
  });
  document.getElementById("calendarClose").addEventListener("click", closeCalendar);
  document.getElementById("calendarModal").addEventListener("click", (e) => {
    if (e.target.id === "calendarModal") closeCalendar();
  });
  document.getElementById("brandAllBtn")?.addEventListener("click", () => {
    alert(
      "전체 브랜드 통합 대시보드는 다음 단계에 연결합니다.\n" +
        "지금은 좌측 Brand 목록에서 등록된 브랜드를 하나씩 선택해 보세요.\n" +
        "(새 브랜드는 앱에서 추가하지 않습니다. 운영/설계에서 프로비저닝합니다.)"
    );
  });
  initMonitorNav();
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeDetail();
      closeCalendar();
      const brandModal = document.getElementById("brandModal");
      if (brandModal && !brandModal.hidden) brandModal.hidden = true;
    }
  });
}


const MONITOR_SECTION_IDS = ["sec-overview", "sec-why", "sec-mix", "sec-portfolio", "sec-events"];

function monitorNavLinks() {
  return [...document.querySelectorAll(".sidebar-nav a.nav-item[href^='#']")];
}

function setMonitorActive(sectionId) {
  const href = `#${sectionId}`;
  monitorNavLinks().forEach((a) => {
    a.classList.toggle("is-active", a.getAttribute("href") === href);
  });
}

function scrollMonitorToSection(sectionId) {
  const root = document.querySelector(".main-scroll");
  const target = document.getElementById(sectionId);
  if (!root || !target) return;
  const rootRect = root.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const nextTop = root.scrollTop + (targetRect.top - rootRect.top) - 12;
  root.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
}

function syncMonitorFromScroll() {
  const root = document.querySelector(".main-scroll");
  if (!root) return;
  const marker = root.getBoundingClientRect().top + Math.min(120, root.clientHeight * 0.22);
  let current = MONITOR_SECTION_IDS[0];
  MONITOR_SECTION_IDS.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.getBoundingClientRect().top <= marker) current = id;
  });
  setMonitorActive(current);
}

function initMonitorNav() {
  const root = document.querySelector(".main-scroll");
  if (!root) return;
  if (root.dataset.spyBound === "1") {
    syncMonitorFromScroll();
    return;
  }
  root.dataset.spyBound = "1";

  monitorNavLinks().forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = (a.getAttribute("href") || "").replace(/^#/, "");
      if (!document.getElementById(id)) return;
      e.preventDefault();
      setMonitorActive(id);
      scrollMonitorToSection(id);
      if (id === "sec-mix" || id === "sec-overview") {
        requestAnimationFrame(() => {
          try {
            mixChart?.resize();
            trendChart?.resize();
          } catch {
            
          }
        });
      }
    });
  });

  let ticking = false;
  root.addEventListener(
    "scroll",
    () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        syncMonitorFromScroll();
        ticking = false;
      });
    },
    { passive: true }
  );
  setMonitorActive(MONITOR_SECTION_IDS[0]);
  syncMonitorFromScroll();
}


function calendarFocusDate() {
  const d = typeof window.REF_DATE !== "undefined" ? window.REF_DATE : new Date();
  return d instanceof Date && !Number.isNaN(d.getTime()) ? d : new Date();
}

const channelClass = {
  백화점: "dept",
  하이마트: "himart",
  신세계백화점: "shinsegae",
  쿠팡: "coupang",
  네이버: "naver",
  "11번가(유튜버)": "eleven",
  "11번가(유부림)": "eleven",
  기타온라인: "coupang",
};

let calendarEvents = [];
let selectedCalDay = 2;

function numOr0(v) {
  const n = Number(String(v ?? "").replace(/,/g, "").replace(/%/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function parseYmd(s) {
  if (typeof window.parseDate === "function") {
    const d = window.parseDate(s);
    if (d) return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }
  const str = String(s || "").trim();
  const m = str.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (!m) return new Date(NaN);
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}


function calYmd(y, m, d) {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function cellToYmd(v) {
  if (typeof window.parseDate === "function" && typeof window.ymd === "function") {
    const d = window.parseDate(v);
    if (d) return window.ymd(d);
  }
  const str = String(v ?? "").trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(str)) return str.slice(0, 10);
  return "";
}

function fmtPeriod(start, end) {
  const a = String(start || "").split("-");
  const b = String(end || "").split("-");
  if (a.length < 3 || b.length < 3) return `${start} ~ ${end}`;
  const s = parseYmd(start);
  const e = parseYmd(end);
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return `${start} ~ ${end}`;
  const days = Math.round((e - s) / 86400000) + 1;
  return `${Number(a[1])}/${Number(a[2])} ~ ${Number(b[1])}/${Number(b[2])} (${days}일간)`;
}

async function buildCalendarFromPromo() {
  const brand = activeBrand();
  let rows = [];
  try {
    if (typeof Repository !== "undefined") {
      const cached = Repository._bundleCache?.[brand]?.promo;
      if (Array.isArray(cached) && cached.length) {
        rows = cached;
      } else {
        const bundle = await Repository.getBrandBundle(brand);
        rows = Array.isArray(bundle?.promo) ? bundle.promo : [];
      }
    }
  } catch (error) {
    console.warn("[Calendar] promo 로드 실패", error);
    rows = [];
  }

  const map = new Map();
  let skipped = 0;
  rows.forEach((row) => {
    if (!Array.isArray(row)) {
      skipped += 1;
      return;
    }
    const start = cellToYmd(row[0]);
    const end = cellToYmd(row[1]);
    const channel = String(row[2] ?? "").trim();
    const eventName = String(row[4] ?? row[3] ?? "").trim();
    const product = String(row[5] ?? "").trim();
    if (!start || !end || !channel || !eventName) {
      skipped += 1;
      return;
    }
    const key = `${channel}|${eventName}|${start}|${end}`;
    if (!map.has(key)) map.set(key, { channel, name: eventName, start, end, products: [] });
    if (product) {
      map.get(key).products.push({
        name: product,
        was: numOr0(row[6]),
        now: numOr0(row[7]),
        period: fmtPeriod(start, end),
        gifts: String(row[10] ?? "").trim() || "-",
      });
    }
  });


  if (!map.size && Array.isArray(dash?.promoEvents) && dash.promoEvents.length) {
    dash.promoEvents.forEach((e) => {
      const start = cellToYmd(e.start) || String(e.periodLabel || "").slice(0, 10);
      const endMatch = String(e.periodLabel || "").match(/~\s*(\d{4}-\d{2}-\d{2})/);
      const end = cellToYmd(e.end) || (endMatch ? endMatch[1] : start);
      const channel = String(e.channel || "").trim();
      const eventName = String(e.eventName || "").trim();
      if (!start || !end || !channel || !eventName) return;
      const key = `${channel}|${eventName}|${start}|${end}`;
      if (!map.has(key)) {
        map.set(key, {
          channel,
          name: eventName,
          start,
          end,
          products: e.product ? [{ name: e.product, was: 0, now: 0, period: fmtPeriod(start, end), gifts: "-" }] : [],
        });
      }
    });
  }

  calendarEvents = [...map.values()];
  calendarEvents._meta = { sheetRows: rows.length, skipped, valid: calendarEvents.length };
  if (!calendarEvents.length) {
    console.warn(
      "[Calendar] 유효 행사 0건 · promo 시트",
      rows.length,
      "행 · 스킵",
      skipped,
      "(시작일·종료일·채널·행사명 필요, 엑셀 날짜 시리얼/포맷 확인)"
    );
  }
}

function eventsOnDay(day) {
  const focus = calendarFocusDate();
  const date = parseYmd(calYmd(focus.getFullYear(), focus.getMonth() + 1, day));
  return calendarEvents.filter((ev) => {
    const a = parseYmd(ev.start);
    const b = parseYmd(ev.end);
    return date >= a && date <= b;
  });
}

function discountPct(was, now) {
  if (!was) return "0.0";
  return (((was - now) / was) * 100).toFixed(1);
}

function renderCalLegend() {
  const items = [
    ["dept", "백화점"],
    ["himart", "하이마트"],
    ["coupang", "쿠팡"],
    ["naver", "네이버"],
    ["shinsegae", "신세계백화점"],
    ["eleven", "11번가"],
  ];
  document.getElementById("calLegend").innerHTML = items
    .map(([cls, label]) => `<span><span class="cal-chip ${cls}" style="width:auto;padding:2px 6px">${label}</span></span>`)
    .join("");
}

function renderCalGrid() {
  const grid = document.getElementById("calGrid");
  const focus = calendarFocusDate();
  const year = focus.getFullYear();
  const month = focus.getMonth() + 1;
  const firstDow = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const dows = ["일", "월", "화", "수", "목", "금", "토"];
  let html = dows.map((d) => `<div class="cal-dow">${d}</div>`).join("");
  for (let i = 0; i < firstDow; i++) html += `<div class="cal-cell is-empty"></div>`;
  for (let day = 1; day <= daysInMonth; day++) {
    const evs = eventsOnDay(day);
    const chips = evs
      .slice(0, 4)
      .map((ev) => {
        const cls = channelClass[ev.channel] || "dept";
        return `<span class="cal-chip ${cls}">${ev.channel} · ${ev.name}</span>`;
      })
      .join("");
    const more = evs.length > 4 ? `<span class="cal-chip dept">+${evs.length - 4}</span>` : "";
    const sel = day === selectedCalDay ? " is-selected" : "";
    html += `
      <button type="button" class="cal-cell${sel}" data-day="${day}">
        <div class="cal-day">${day}</div>
        ${chips}${more}
      </button>`;
  }
  grid.innerHTML = html;
  grid.querySelectorAll("[data-day]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedCalDay = Number(btn.dataset.day);
      renderCalGrid();
      renderCalDetail();
    });
  });
}

function renderCalDetail() {
  const box = document.getElementById("calDetail");
  const focus = calendarFocusDate();
  const dateStr = calYmd(focus.getFullYear(), focus.getMonth() + 1, selectedCalDay);
  const featured = eventsOnDay(selectedCalDay).filter((e) => e.products.length > 0);
  const show = featured.length ? featured : eventsOnDay(selectedCalDay);
  let body = `<h4 class="cal-detail-head">${dateStr} 행사 (${show.length}건)</h4>`;
  if (!show.length) {
    const meta = calendarEvents._meta || {};
    const sheetRows = Number(meta.sheetRows) || 0;
    body += sheetRows
      ? `<p class="cal-empty">해당일 행사가 없습니다. (프로모션 ${sheetRows}행 중 캘린더 유효 ${Number(meta.valid) || 0}건 · 날짜/채널/행사명 형식 확인)</p>`
      : `<p class="cal-empty">해당일 등록된 행사가 없습니다. 프로모션 시트를 확인해 주세요.</p>`;
  } else {
    body += show
      .map((ev) => {
        const products =
          ev.products.length === 0
            ? `<p class="cal-empty">등록된 특가 상품 없음</p>`
            : ev.products
                .map(
                  (p) => `
              <div class="cal-product">
                <div class="cal-product-name">제품: ${p.name}</div>
                <div class="cal-product-line">
                  <span class="was">${p.was.toLocaleString("ko-KR")}</span>
                  → <span class="now">${p.now.toLocaleString("ko-KR")}</span>
                  (${discountPct(p.was, p.now)}%)
                </div>
                <div class="cal-product-line">행사기간: ${p.period}</div>
                <div class="cal-product-line">사은품: ${p.gifts}</div>
              </div>`
                )
                .join("");
        return `
          <article class="cal-event-block">
            <h5 class="cal-event-title">${ev.channel} · ${ev.name}</h5>
            ${products}
          </article>`;
      })
      .join("");
  }
  box.innerHTML = body;
}

async function openCalendar() {
  const focus = calendarFocusDate();
  selectedCalDay = focus.getDate();
  await buildCalendarFromPromo();
  const meta = calendarEvents._meta || {};
  const valid = Number(meta.valid) || calendarEvents.length;
  document.getElementById("calendarTitle").textContent =
    `행사 캘린더 · ${focus.getFullYear()}년 ${focus.getMonth() + 1}월` +
    (valid ? ` · ${valid}건` : "");
  renderCalLegend();
  renderCalGrid();
  renderCalDetail();
  document.getElementById("calendarModal").hidden = false;
  document.body.style.overflow = "hidden";
  if (typeof DashSource !== "undefined") {
    DashSource.applyEl(document.querySelector("#calendarModal .modal-calendar"), "calendar");
    DashSource.applyEl(document.getElementById("calGrid"), "calendar");
    DashSource.applyEl(document.getElementById("calDetail"), "calendar");
  }
}

function closeCalendar() {
  document.getElementById("calendarModal").hidden = true;
  if (document.getElementById("detailModal").hidden) {
    document.body.style.overflow = "";
  }
}

window.addEventListener("admin-sheets-updated", (event) => {
  const action = event?.detail?.action;
  
  if (action === "authReady" || action === "ensureBrand" || action === "createBrand") {
    refreshBrandNav();
    if (!dash) scheduleRefreshDashboard(120);
    return;
  }
  if (action === "exitAdmin") {
    scheduleRefreshDashboard(50);
    return;
  }
  refreshBrandNav();
  scheduleRefreshDashboard(50);
  if (!document.getElementById("calendarModal").hidden) {
    void buildCalendarFromPromo().then(() => {
      renderCalGrid();
      renderCalDetail();
    });
  }
});

document.addEventListener("DOMContentLoaded", bootDashboard);
if (document.readyState !== "loading") {
  bootDashboard();
}

async function bootDashboard() {
  if (window.__eibeSalesDashboardBooted) return;
  window.__eibeSalesDashboardBooted = true;
  try {
    if (window.AuthGate?.ready) {
      await Promise.race([
        window.AuthGate.ready,
        new Promise((resolve) => setTimeout(resolve, 2500)),
      ]);
    }
  } catch {
    
  }
  document.getElementById("categoryFilter")?.addEventListener("change", (event) => {
    dashboardOptions.category = event.target.value;
    void refreshDashboard();
  });
  document.getElementById("anchorSelect")?.addEventListener("change", (event) => {
    dashboardOptions.anchor = event.target.value || "";
    void refreshDashboard();
  });
  document.getElementById("trendValue")?.addEventListener("change", (event) => {
    dashboardOptions.trendValue = event.target.value;
    void refreshDashboard();
  });
  document.getElementById("trendUnit")?.addEventListener("change", (event) => {
    dashboardOptions.trendUnit = event.target.value === "month" ? "month" : "week";
    void refreshDashboard();
  });
  document.getElementById("trendRange")?.addEventListener("change", (event) => {
    const v = event.target.value;
    dashboardOptions.trendRange = v === "all" ? "all" : Number(v);
    void refreshDashboard();
  });
  document.getElementById("trendBasis")?.addEventListener("change", (event) => {
    dashboardOptions.trendBasis = event.target.value || "simplifiedChannel";
    trendSelectedLabels = null;
    lastTrendBasis = null;
    void refreshDashboard();
  });
  bindTrendSeriesUi();
  initShellChrome();
  document.getElementById("portfolioMinQty")?.addEventListener("change", (event) => {
    const n = Number(event.target.value);
    dashboardOptions.minQtyPortfolio = Number.isFinite(n) && n >= 0 ? n : 5;
    void refreshDashboard();
  });
  const minQtyEl = document.getElementById("portfolioMinQty");
  if (minQtyEl) {
    const n = Number(minQtyEl.value);
    if (Number.isFinite(n) && n >= 0) dashboardOptions.minQtyPortfolio = n;
  }
  initMonitorNav();
  if (typeof Repository !== "undefined" && Repository.getBackendName?.() !== "api") {
    console.warn(
      "[SalesHub] DATA_BACKEND가 api가 아닙니다:",
      Repository.getBackendName?.(),
      "— 운영은 API/SQL 서버 백엔드만 사용하세요."
    );
  }
  if (typeof DashSource !== "undefined") DashSource.applyStatic();
  refreshBrandNav().then(() => refreshDashboard());
}
