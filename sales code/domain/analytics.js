


function getRefDate() {
  const override =
    (typeof DataConfig !== "undefined" && DataConfig.REF_DATE_OVERRIDE) || null;
  if (override) {
    const d = parseDate(override) || new Date(String(override));
    if (d && !Number.isNaN(d.getTime())) {
      return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12, 0, 0);
    }
  }
  const n = new Date();
  return new Date(n.getFullYear(), n.getMonth(), n.getDate(), 12, 0, 0);
}


function dateFromWeekKey(wk) {
  const m = String(wk || "").match(/^(\d{4})-W(\d{1,2})$/);
  if (!m) return null;
  const y = Number(m[1]);
  const w = Number(m[2]);
  if (!y || w < 1 || w > 53) return null;
  const jan4 = new Date(y, 0, 4, 12, 0, 0);
  const week1Mon = startOfIsoWeek(jan4);
  return addDays(week1Mon, (w - 1) * 7 + 6);
}


function dateFromMonthKey(mk) {
  const m = String(mk || "").match(/^(\d{4})-M(\d{1,2})$/);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  if (!y || mo < 1 || mo > 12) return null;
  return new Date(y, mo, 0, 12, 0, 0);
}


function resolveAnchor(options = {}) {
  const raw = String(options.anchor || "").trim();
  if (!raw) {
    return { refDate: getRefDate(), fullMonth: false, anchor: "" };
  }
  if (raw.indexOf("week:") === 0) {
    const d = dateFromWeekKey(raw.slice(5));
    if (d) return { refDate: d, fullMonth: true, anchor: raw };
  }
  if (raw.indexOf("month:") === 0) {
    const d = dateFromMonthKey(raw.slice(6));
    if (d) return { refDate: d, fullMonth: true, anchor: raw };
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const d = parseDate(raw);
    if (d) return { refDate: d, fullMonth: Boolean(options.fullMonth), anchor: raw };
  }
  return { refDate: getRefDate(), fullMonth: false, anchor: "" };
}

let REF_DATE = getRefDate();
let ANCHOR_FULL_MONTH = false;

function thresholds() {
  return (typeof SheetSchema !== "undefined" && SheetSchema.ANALYTICS_THRESHOLDS) || {
    MIN_QTY_PORTFOLIO: 1,
    ALERT_PRODUCT_UP: 50,
    ALERT_PRODUCT_DOWN: -25,
    ALERT_CHANNEL_DOWN: -20,
    ALERT_MAX: 5,
  };
}

function toNum(v) {
  if (v == null || v === "") return 0;
  if (typeof v === "number") return v;
  const n = Number(
    String(v)
      .replace(/,/g, "")
      .replace(/%/g, "")
      .replace(/원/g, "")
      .replace(/\s/g, "")
      .trim()
  );
  return Number.isFinite(n) ? n : 0;
}

function parseDate(v) {
  if (!v) return null;
  if (v instanceof Date && !Number.isNaN(v.getTime())) {
    return new Date(v.getFullYear(), v.getMonth(), v.getDate(), 12, 0, 0);
  }
  const s = String(v).trim();

  if (/^\d+(\.\d+)?$/.test(s) && Number(s) > 20000) {
    const serial = Math.floor(Number(s));
    const excelEpoch = Date.UTC(1899, 11, 30);
    const utc = new Date(excelEpoch + serial * 86400000);
    return new Date(utc.getUTCFullYear(), utc.getUTCMonth(), utc.getUTCDate(), 12, 0, 0);
  }

  let m = s.match(/^(\d{4})\s*[-\/.년]\s*(\d{1,2})\s*[-\/.월]\s*(\d{1,2})/);
  if (m) {
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12, 0, 0);
  }

  m = s.match(/^(\d{2})[-\/.](\d{1,2})[-\/.](\d{1,2})/);
  if (m) {
    return new Date(2000 + Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12, 0, 0);
  }
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return null;
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12, 0, 0);
}

function ymd(d) {
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function isoWeek(date) {
  const t = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - yearStart) / 86400000 + 1) / 7);
}

function isoWeekYear(date) {
  const t = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  return t.getUTCFullYear();
}

function weekKey(d) {
  return `${isoWeekYear(d)}-W${String(isoWeek(d)).padStart(2, "0")}`;
}

function monthKey(d) {
  return `${d.getFullYear()}-M${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function addMonths(d, n) {
  return new Date(d.getFullYear(), d.getMonth() + n, 1, 12, 0, 0);
}

function startOfIsoWeek(d) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const day = x.getDay() || 7;
  x.setDate(x.getDate() - day + 1);
  return x;
}

function addDays(d, n) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() + n);
  return x;
}


function sameDayPrevMonth(ref) {
  const y = ref.getFullYear();
  const m = ref.getMonth();
  const d = ref.getDate();
  const lastPrev = new Date(y, m, 0).getDate();
  return new Date(y, m - 1, Math.min(d, lastPrev), 12, 0, 0);
}


function weekEndClamped(weekStart, ref) {
  const sun = addDays(weekStart, 6);
  return sun.getTime() <= ref.getTime() ? sun : new Date(ref.getFullYear(), ref.getMonth(), ref.getDate(), 12, 0, 0);
}

function pctChange(cur, prev) {
  if (!prev) return cur ? 100 : 0;
  return ((cur - prev) / prev) * 100;
}

function sharePp(curShare, prevShare) {
  return curShare - prevShare;
}

function getBrandBundle(brand) {
  const brandId =
    brand ||
    (typeof SheetSchema !== "undefined" ? SheetSchema.DEFAULT_BRAND_SLUG : "dreame");

  if (typeof Repository !== "undefined" && Repository._bundleCache?.[brandId]) {
    const cached = Repository._bundleCache[brandId];
    return {
      brand: brandId,
      promo: cached.promo || [],
      raw: cached.raw || [],
      channelGroup: cached.channelGroup || [],
      lineup: cached.lineup || [],
      channelSetting: cached.channelSetting || [],
    };
  }

  if (
    typeof Repository !== "undefined" &&
    Repository.getBackendName?.() === "local" &&
    Repository.getAdminStoreSnapshot
  ) {
    const store = Repository.getAdminStoreSnapshot();
    const sheets = store?.sheets?.[brandId] || {};
    return {
      brand: brandId,
      promo: sheets.promo || [],
      raw: sheets.raw || [],
      channelGroup: sheets.channelGroup || [],
      lineup: sheets.lineup || [],
      channelSetting: sheets.channelSetting || [],
    };
  }
  return {
    brand: brandId,
    promo: [],
    raw: [],
    channelGroup: [],
    lineup: [],
    channelSetting: [],
  };
}

function buildMaps(bundle) {
  const groupMap = new Map();
  bundle.channelGroup.forEach((r) => {
    const ch = String(r[0] || "").trim();
    const g = String(r[1] || "").trim();
    if (ch && g) groupMap.set(ch, g);
  });
  const lineupMap = new Map();
  bundle.lineup.forEach((r) => {
    const a = String(r[0] || "").trim();
    const b = String(r[1] || "").trim();
    if (a && b) lineupMap.set(a, b);
  });
  const major = new Set(
    bundle.channelSetting.map((r) => String(r[0] || "").trim()).filter(Boolean)
  );
  return { groupMap, lineupMap, major };
}


function resolveGroup(channel, maps, channelType) {
  const ch = String(channel || "").trim();
  if (!ch) return "기타";
  if (maps.groupMap.has(ch)) return maps.groupMap.get(ch);
  if (maps.major.has(ch)) return ch;

  for (const [k, v] of maps.groupMap) {
    if (ch.startsWith(k) || k.startsWith(ch)) return v;
  }
  for (const m of maps.major) {
    if (ch.startsWith(m)) return m;
  }
  const t = String(channelType || "").trim();
  return t ? `기타 ${t}` : "기타";
}


const TREND_BASIS_PROPS = {
  simplifiedChannel: "channelGroup",
  channel: "channelRaw",
  channelType: "channelType",
  lineup: "lineup",
  product: "productRaw",
  category: "category",
};

const TREND_SERIES_HARD_CAP = 120;

function resolveLineup(product, maps) {
  const p = String(product || "").trim();
  return maps.lineupMap.get(p) || p;
}

function normalizeRawRows(bundle) {
  const maps = buildMaps(bundle);
  return bundle.raw
    .map((r) => {
      const ship = parseDate(r[4]);
      if (!ship) return null;
      const qty = toNum(r[3]);
      let sales = toNum(r[12]);
      if (!sales) sales = qty * toNum(r[11]);
      const channelRaw = String(r[1] || "").trim();
      const productRaw = String(r[2] || "").trim();
      const channelType = String(r[13] || "").trim();
      if (!channelRaw && !productRaw) return null;
      return {
        category: String(r[0] || "").trim() || "기타",
        channelRaw,
        channelType: channelType || "기타",
        channelGroup: resolveGroup(channelRaw, maps, channelType),
        productRaw,
        lineup: resolveLineup(productRaw, maps),
        qty,
        sales,
        ship,
        week: weekKey(ship),
        mKey: monthKey(ship),
        year: ship.getFullYear(),
        month: ship.getMonth() + 1,
        day: ship.getDate(),
      };
    })
    .filter(Boolean);
}

function sumRows(rows) {
  return rows.reduce(
    (a, r) => {
      a.qty += r.qty;
      a.sales += r.sales;
      return a;
    },
    { qty: 0, sales: 0 }
  );
}

function inRange(d, start, end) {
  const t = d.getTime();
  return t >= start.getTime() && t <= end.getTime();
}

function computeDashboard(brand = "dreame", bundleInject, options = {}) {
  const anchored = resolveAnchor(options);
  REF_DATE = anchored.refDate;
  ANCHOR_FULL_MONTH = anchored.fullMonth;
  if (typeof window !== "undefined") window.REF_DATE = REF_DATE;
  const bundle = bundleInject || getBrandBundle(brand);
  const maps = buildMaps(bundle);
  const allRows = normalizeRawRows(bundle);
  const rawSkipped =
    (Array.isArray(bundle.raw) ? bundle.raw.length : 0) -
    allRows.length;
  const category = String(options.category || "").trim();
  const rows = category ? allRows.filter((row) => row.category === category) : allRows;

  const thisWeekStart = startOfIsoWeek(REF_DATE);
  const thisWeekEnd = weekEndClamped(thisWeekStart, REF_DATE);
  const prevWeekStart = addDays(thisWeekStart, -7);
  const prevWeekEnd = addDays(thisWeekStart, -1);

  const monthStart = new Date(REF_DATE.getFullYear(), REF_DATE.getMonth(), 1, 12, 0, 0);
  let monthEnd = new Date(REF_DATE.getFullYear(), REF_DATE.getMonth(), REF_DATE.getDate(), 12, 0, 0);
  const prevMonthStart = new Date(REF_DATE.getFullYear(), REF_DATE.getMonth() - 1, 1, 12, 0, 0);
  let prevMonthEnd = sameDayPrevMonth(REF_DATE);
  if (ANCHOR_FULL_MONTH) {
    monthEnd = new Date(REF_DATE.getFullYear(), REF_DATE.getMonth() + 1, 0, 12, 0, 0);
    prevMonthEnd = new Date(REF_DATE.getFullYear(), REF_DATE.getMonth(), 0, 12, 0, 0);
  }

  const weekRows = rows.filter((r) => inRange(r.ship, thisWeekStart, thisWeekEnd));
  const prevWeekRows = rows.filter((r) => inRange(r.ship, prevWeekStart, prevWeekEnd));
  const monthRows = rows.filter((r) => inRange(r.ship, monthStart, monthEnd));
  const prevMonthRows = rows.filter((r) => inRange(r.ship, prevMonthStart, prevMonthEnd));

  const week = sumRows(weekRows);
  const prevWeek = sumRows(prevWeekRows);
  const month = sumRows(monthRows);
  const prevMonth = sumRows(prevMonthRows);


  const four = [];
  for (let i = 1; i <= 4; i++) {
    const s = addDays(thisWeekStart, -7 * i);
    const e = addDays(s, 6);
    four.push(sumRows(rows.filter((r) => inRange(r.ship, s, e))));
  }
  const avg4 = {
    sales: four.reduce((a, x) => a + x.sales, 0) / 4,
    qty: four.reduce((a, x) => a + x.qty, 0) / 4,
  };

  const kpi = {
    week,
    prevWeek,
    weekSalesPct: pctChange(week.sales, prevWeek.sales),
    weekQtyPct: pctChange(week.qty, prevWeek.qty),
    month,
    prevMonth,
    monthSalesPct: pctChange(month.sales, prevMonth.sales),
    monthQtyPct: pctChange(month.qty, prevMonth.qty),
    momentumSales: week.sales - avg4.sales,
    momentumQty: week.qty - avg4.qty,
    momentumSalesPct: pctChange(week.sales, avg4.sales),
    momentumQtyPct: pctChange(week.qty, avg4.qty),
    avg4,
    weekLabel: weekKey(REF_DATE),
    monthLabel: ANCHOR_FULL_MONTH
      ? `${REF_DATE.getFullYear()}년 ${REF_DATE.getMonth() + 1}월`
      : `${REF_DATE.getMonth() + 1}/1~${REF_DATE.getDate()}일`,
    fullMonth: ANCHOR_FULL_MONTH,
  };


  const byGroup = (list) => {
    const m = new Map();
    list.forEach((r) => {
      const g = r.channelGroup;
      if (!m.has(g)) m.set(g, { sales: 0, qty: 0 });
      m.get(g).sales += r.sales;
      m.get(g).qty += r.qty;
    });
    return m;
  };
  const curG = byGroup(weekRows);
  const prevG = byGroup(prevWeekRows);
  const monthG = byGroup(monthRows);
  const prevMonthG = byGroup(prevMonthRows);
  const totalCur = week.sales || 1;
  const totalPrev = prevWeek.sales || 1;
  const totalMonth = month.sales || 1;
  const totalPrevMonth = prevMonth.sales || 1;

  const order = [...maps.major];
  curG.forEach((_, k) => {
    if (!order.includes(k)) order.push(k);
  });

  const mixRows = order
    .map((ch) => {
      const sales = curG.get(ch)?.sales || 0;
      const share = (sales / totalCur) * 100;
      const prevShare = ((prevG.get(ch)?.sales || 0) / totalPrev) * 100;
      const momShare = ((monthG.get(ch)?.sales || 0) / totalMonth) * 100;
      const prevMomShare = ((prevMonthG.get(ch)?.sales || 0) / totalPrevMonth) * 100;
      return {
        ch,
        sales,
        share,
        wow: sharePp(share, prevShare),
        mom: sharePp(momShare, prevMomShare),
      };
    })
    .filter((r) => r.sales > 0 || maps.major.has(r.ch))
    .sort((a, b) => b.sales - a.sales);


  const byLineup = (list) => {
    const m = new Map();
    list.forEach((r) => {
      const k = r.lineup || "(미지정)";
      if (!m.has(k)) m.set(k, { qty: 0, sales: 0 });
      m.get(k).qty += r.qty;
      m.get(k).sales += r.sales;
    });
    return m;
  };
  const curL = byLineup(monthRows);
  const prevL = byLineup(prevMonthRows);
  const minOrder = Math.max(
    0,
    Number(options.minQtyPortfolio ?? thresholds().MIN_QTY_PORTFOLIO) || 0
  );
  const ranked = [...curL.entries()]
    .filter(([, v]) => v.qty >= minOrder)
    .map(([name, v]) => {
      const prev = prevL.get(name);
      if (!prev || prev.qty === 0) {
        return { name, qty: v.qty, sales: v.sales, delta: null, neu: true };
      }
      return {
        name,
        qty: v.qty,
        sales: v.sales,
        delta: pctChange(v.qty, prev.qty),
        neu: false,
      };
    });

  prevL.forEach((v, name) => {
    if (!curL.has(name) && v.qty >= minOrder) {
      ranked.push({ name, qty: 0, sales: 0, delta: -100, neu: false });
    }
  });
  const growth = ranked
    .filter((r) => r.neu || (r.delta != null && r.delta > 0))
    .sort((a, b) => (b.delta ?? 9999) - (a.delta ?? 9999))
    .slice(0, 3);
  const decline = ranked
    .filter((r) => r.delta != null && r.delta < 0)
    .sort((a, b) => a.delta - b.delta)
    .slice(0, 3);


  const promoEvents = [];
  bundle.promo.forEach((p) => {
    const start = parseDate(p[0]);
    const end = parseDate(p[1]);
    const channel = String(p[2] || "").trim();
    const slot = String(p[3] || "").trim();
    const eventName = String(p[4] || "").trim();
    const productRaw = String(p[5] || "").trim();
    const product = resolveLineup(productRaw, maps);
    if (!start || !end || !channel || !eventName) return;
    const group = resolveGroup(channel, maps);
    const days = Math.round((end - start) / 86400000) + 1;
    const overlapWeek = !(end < thisWeekStart || start > thisWeekEnd);
    const during = rows.filter(
      (r) =>
        (!product || r.lineup === product) &&
        (r.channelGroup === group || r.channelRaw === channel || r.channelRaw.startsWith(channel)) &&
        inRange(r.ship, start, end)
    );
    const dSum = sumRows(during);
    promoEvents.push({
      start,
      end,
      channel,
      group,
      slot,
      eventName,
      product,
      days,
      overlapWeek,
      periodLabel: `${ymd(start)} ~ ${ymd(end)} (${days}일)`,
      qty: dSum.qty,
      sales: dSum.sales,
      priceWas: toNum(p[6]),
      priceNow: toNum(p[7]),
      gifts: String(p[10] || "").trim(),
    });
  });

  function eventsForProduct(lineupName) {
    return promoEvents.filter((e) => e.product === lineupName || !e.product);
  }
  function eventsForChannel(groupName) {
    return promoEvents.filter((e) => e.group === groupName || e.channel === groupName || e.channel.startsWith(groupName));
  }
  function weekEventsFor(list) {
    return list.filter((e) => e.overlapWeek);
  }

  function buildWhy({ type, name, wowPct, curQty, prevQty, curSales, relatedEvents, driverRows }) {
    const reasons = [];
    const weekEv = weekEventsFor(relatedEvents);
    if (weekEv.length) {
      weekEv.slice(0, 3).forEach((e) => {
        const liftHint =
          e.qty > 0
            ? `행사 기간 실판매 ${e.qty}개 (${Math.round(e.sales).toLocaleString("ko-KR")}원)`
            : "행사 기간 raw 판매 0 — 일정만 등록됨";
        reasons.push({
          kind: "event",
          title: `${e.channel} · ${e.eventName}`,
          detail: `${e.product || "전체"} · ${e.periodLabel} · ${liftHint}`,
        });
      });
      if (wowPct >= 0) {
        reasons.push({
          kind: "hypothesis",
          title: "가설: 행사 리프트 가능",
          detail: `금주와 겹치는 프로모션 ${weekEv.length}건이 있어 상승 요인으로 우선 검토`,
        });
      } else {
        reasons.push({
          kind: "hypothesis",
          title: "가설: 행사 종료/약화 또는 채널 이슈",
          detail: "금주 겹침 행사가 있어도 하락이면 재고·가격·노출·경쟁 요인을 함께 확인",
        });
      }
    } else if (relatedEvents.length) {
      const nearest = relatedEvents
        .slice()
        .sort((a, b) => Math.abs(a.start - REF_DATE) - Math.abs(b.start - REF_DATE))[0];
      reasons.push({
        kind: "event",
        title: `근접 행사: ${nearest.channel} · ${nearest.eventName}`,
        detail: `${nearest.periodLabel} (금주와 비겹침) — 전후 효과/반동 가능`,
      });
    } else {
      reasons.push({
        kind: "gap",
        title: "연계 행사 없음",
        detail: "프로모션 시트에 매칭 행사가 없습니다. 오가닉/채널 이슈·시즌 요인을 의심",
      });
    }

    const drivers = (driverRows || [])
      .filter((r) => r.wowQty != null || r.neu != null)
      .slice()
      .sort((a, b) => Math.abs(b.wowQty || b.neu || 0) - Math.abs(a.wowQty || a.neu || 0))
      .slice(0, 3);
    drivers.forEach((d) => {
      const dir = (d.wowQty || 0) >= 0 || d.neu != null ? "기여(상승)" : "기여(하락)";
      reasons.push({
        kind: "driver",
        title: `${dir}: ${d.name}`,
        detail:
          d.neu != null
            ? `신규 ${d.neu}개 · ${Math.round(d.sales).toLocaleString("ko-KR")}원`
            : `WoW ${d.wowQty}개 (${Number(d.wowPct).toFixed(1)}%) · ${Math.round(d.sales).toLocaleString("ko-KR")}원`,
      });
    });

    const verdict =
      wowPct == null
        ? `${name} · 신규/특이 패턴`
        : wowPct >= 0
          ? `${name} · 전주 대비 ▲${Math.abs(wowPct).toFixed(1)}%`
          : `${name} · 전주 대비 ▼${Math.abs(wowPct).toFixed(1)}%`;

    return {
      type,
      name,
      verdict,
      summary: {
        curQty,
        prevQty,
        curSales,
        wowPct,
      },
      reasons,
      relatedEvents: relatedEvents.map((e) => ({
        label: `${e.channel} · ${e.eventName}`,
        product: e.product,
        period: e.periodLabel,
        overlapWeek: e.overlapWeek,
        qty: e.qty,
        sales: e.sales,
        price:
          e.priceWas && e.priceNow
            ? `${e.priceWas.toLocaleString("ko-KR")} → ${e.priceNow.toLocaleString("ko-KR")}`
            : "",
        gifts: e.gifts,
      })),
    };
  }


  const alerts = [];
  ranked.forEach((r) => {
    if (r.neu && r.qty > 0) return;
    const wCur = weekRows.filter((x) => x.lineup === r.name);
    const wPrev = prevWeekRows.filter((x) => x.lineup === r.name);
    const c = sumRows(wCur);
    const p = sumRows(wPrev);
    if (p.qty > 0) {
      const d = pctChange(c.qty, p.qty);
      const th = thresholds();
      const rel = eventsForProduct(r.name);
      const weekEv = weekEventsFor(rel);
      const eventHint = weekEv.length
        ? ` · 연계 행사 ${weekEv.length}건 (${weekEv[0].eventName})`
        : rel.length
          ? " · 금주 겹침 행사 없음"
          : " · 등록 행사 없음";
      if (d >= th.ALERT_PRODUCT_UP) {
        alerts.push({
          type: "up",
          text: `<strong>${r.name}</strong> 판매가 전주 대비 <strong>${Math.round(d)}%</strong> 증가했습니다.${eventHint}`,
          key: `product:${r.name}`,
          why: weekEv.length ? `금주 겹침 행사: ${weekEv.map((e) => e.eventName).join(", ")}` : "행사 외 요인 가능",
        });
      }
      if (d <= th.ALERT_PRODUCT_DOWN) {
        alerts.push({
          type: "down",
          text: `<strong>${r.name}</strong> 판매가 전주 대비 <strong>${Math.round(Math.abs(d))}%</strong> 감소했습니다.${eventHint}`,
          key: `product:${r.name}`,
          why: weekEv.length ? "행사 중인데도 하락 — 채널/가격 점검" : "금주 행사 공백 또는 수요 둔화",
        });
      }
    }
  });
  mixRows.forEach((r) => {
    const c = curG.get(r.ch)?.qty || 0;
    const p = prevG.get(r.ch)?.qty || 0;
    if (p > 0) {
      const d = pctChange(c, p);
      if (d <= thresholds().ALERT_CHANNEL_DOWN) {
        const rel = eventsForChannel(r.ch);
        const weekEv = weekEventsFor(rel);
        const eventHint = weekEv.length
          ? ` · 금주 행사 ${weekEv.length}건`
          : " · 금주 채널 행사 약함";
        alerts.push({
          type: "down",
          text: `<strong>${r.ch}</strong> 판매가 이번 주 <strong>${Math.round(Math.abs(d))}%</strong> 감소했습니다.${eventHint}`,
          key: `channel:${r.ch}`,
          why: weekEv.length
            ? `겹침 행사 있음에도 하락: ${weekEv[0].eventName}`
            : "금주 프로모션 공백 가능",
        });
      } else if (d >= 30) {
        const rel = eventsForChannel(r.ch);
        const weekEv = weekEventsFor(rel);
        if (weekEv.length || d >= 50) {
          alerts.push({
            type: "up",
            text: `<strong>${r.ch}</strong> 판매가 이번 주 <strong>${Math.round(d)}%</strong> 증가했습니다.${
              weekEv.length ? ` · ${weekEv[0].eventName}` : ""
            }`,
            key: `channel:${r.ch}`,
            why: weekEv.length ? `행사 연계 상승 가능: ${weekEv.map((e) => e.eventName).join(", ")}` : "채널 오가닉/시즌 상승",
          });
        }
      }
    }
  });
  const alertList = alerts.slice(0, thresholds().ALERT_MAX);


  const trendUnit = options.trendUnit === "month" ? "month" : "week";
  const trendValue = options.trendValue === "qty" ? "qty" : "sales";
  const rangeRaw = options.trendRange;
  const trendAll = rangeRaw === "all" || String(rangeRaw) === "all";
  const trendRangeN = [4, 6, 8, 12].includes(Number(rangeRaw)) ? Number(rangeRaw) : 12;
  const trendBasisRaw = String(options.trendBasis || "simplifiedChannel");
  const trendBasis = TREND_BASIS_PROPS[trendBasisRaw] ? trendBasisRaw : "simplifiedChannel";
  const groupProp = TREND_BASIS_PROPS[trendBasis];

  let periodKeys = [];
  if (trendUnit === "week") {
    if (trendAll) {
      periodKeys = [...new Set(rows.map((r) => r.week))].sort();
      const curWk = weekKey(REF_DATE);
      periodKeys = periodKeys.filter((k) => k <= curWk);
      if (!periodKeys.length) periodKeys = [curWk];
    } else {
      for (let i = trendRangeN - 1; i >= 0; i--) {
        periodKeys.push(weekKey(addDays(thisWeekStart, -7 * i)));
      }
    }
  } else {
    const thisMonth = monthKey(REF_DATE);
    if (trendAll) {
      periodKeys = [...new Set(rows.map((r) => r.mKey))].sort();
      periodKeys = periodKeys.filter((k) => k <= thisMonth);
      if (!periodKeys.length) periodKeys = [thisMonth];
    } else {
      for (let i = trendRangeN - 1; i >= 0; i--) {
        periodKeys.push(monthKey(addMonths(REF_DATE, -i)));
      }
    }
  }

  const periodProp = trendUnit === "month" ? "mKey" : "week";
  const periodSet = new Set(periodKeys);
  const formatPeriodLabel = (key) => {
    if (trendUnit === "month") {
      const parts = String(key).split("-M");
      return `${parts[0]}.${Number(parts[1] || 0)}`;
    }
    return String(key).replace(/^(\d+)-W/, (_, y) => (trendAll ? `${y}-W` : "W"));
  };

  const totals = new Map();
  const byLabelPeriod = new Map();
  rows.forEach((r) => {
    const pk = r[periodProp];
    if (!periodSet.has(pk)) return;
    const label = String(r[groupProp] || "").trim() || "기타";
    const v = r[trendValue] || 0;
    totals.set(label, (totals.get(label) || 0) + v);
    if (!byLabelPeriod.has(label)) byLabelPeriod.set(label, new Map());
    const bucket = byLabelPeriod.get(label);
    bucket.set(pk, (bucket.get(pk) || 0) + v);
  });

  let orderedLabels = [...totals.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko"))
    .map(([label]) => label);
  let truncated = false;
  if (orderedLabels.length > TREND_SERIES_HARD_CAP) {
    truncated = true;
    const head = orderedLabels.slice(0, TREND_SERIES_HARD_CAP - 1);
    const rest = orderedLabels.slice(TREND_SERIES_HARD_CAP - 1);
    const restKey = "기타(나머지)";
    const restMap = new Map();
    let restTotal = 0;
    rest.forEach((lab) => {
      restTotal += totals.get(lab) || 0;
      const m = byLabelPeriod.get(lab);
      if (!m) return;
      m.forEach((v, pk) => restMap.set(pk, (restMap.get(pk) || 0) + v));
    });
    totals.set(restKey, restTotal);
    byLabelPeriod.set(restKey, restMap);
    orderedLabels = [...head, restKey];
  }

  const trend = {
    labels: periodKeys.map(formatPeriodLabel),
    series: orderedLabels.map((label) => ({
      label,
      total: totals.get(label) || 0,
      data: periodKeys.map((pk) => byLabelPeriod.get(label)?.get(pk) || 0),
    })),
    value: trendValue,
    unit: trendUnit,
    range: trendAll ? "all" : trendRangeN,
    basis: trendBasis,
    truncated,
  };


  const detailCatalog = {};
  order.forEach((group) => {
    const kids = new Map();
    weekRows
      .filter((r) => r.channelGroup === group)
      .forEach((r) => {
        if (!kids.has(r.channelRaw)) kids.set(r.channelRaw, { qty: 0, sales: 0 });
        kids.get(r.channelRaw).qty += r.qty;
        kids.get(r.channelRaw).sales += r.sales;
      });
    const prevKids = new Map();
    prevWeekRows
      .filter((r) => r.channelGroup === group)
      .forEach((r) => {
        if (!prevKids.has(r.channelRaw)) prevKids.set(r.channelRaw, { qty: 0, sales: 0 });
        prevKids.get(r.channelRaw).qty += r.qty;
        prevKids.get(r.channelRaw).sales += r.sales;
      });
    const names = new Set([...kids.keys(), ...prevKids.keys()]);
    if (!names.size) return;
    const detailRows = [...names].map((name) => {
      const q = kids.get(name)?.qty || 0;
      const s = kids.get(name)?.sales || 0;
      const pq = prevKids.get(name)?.qty || 0;
      if (pq === 0 && q > 0) return { name, qty: q, neu: q, wowQty: null, wowPct: null, sales: s };
      const wowQty = q - pq;
      const wowPct = pctChange(q, pq);
      return { name, qty: q, wowQty, wowPct, sales: s };
    });
    const cur = sumRows(weekRows.filter((r) => r.channelGroup === group));
    const prev = sumRows(prevWeekRows.filter((r) => r.channelGroup === group));
    const wowPct = pctChange(cur.qty, prev.qty);
    detailCatalog[`channel:${group}`] = {
      title: `[${group}] 세부 분석 · 채널 (${weekKey(REF_DATE)})`,
      col1: "세부 채널명",
      rows: detailRows,
      insight: buildWhy({
        type: "channel",
        name: group,
        wowPct,
        curQty: cur.qty,
        prevQty: prev.qty,
        curSales: cur.sales,
        relatedEvents: eventsForChannel(group),
        driverRows: detailRows,
      }),
    };
  });

  [...new Set([...weekRows, ...prevWeekRows].map((r) => r.lineup))].forEach((name) => {
    if (!name) return;
    const kids = new Map();
    weekRows
      .filter((r) => r.lineup === name)
      .forEach((r) => {
        if (!kids.has(r.channelGroup)) kids.set(r.channelGroup, { qty: 0, sales: 0 });
        kids.get(r.channelGroup).qty += r.qty;
        kids.get(r.channelGroup).sales += r.sales;
      });
    const prevKids = new Map();
    prevWeekRows
      .filter((r) => r.lineup === name)
      .forEach((r) => {
        if (!prevKids.has(r.channelGroup)) prevKids.set(r.channelGroup, { qty: 0, sales: 0 });
        prevKids.get(r.channelGroup).qty += r.qty;
        prevKids.get(r.channelGroup).sales += r.sales;
      });
    const detailRows = [...new Set([...kids.keys(), ...prevKids.keys()])].map((ch) => {
      const q = kids.get(ch)?.qty || 0;
      const s = kids.get(ch)?.sales || 0;
      const pq = prevKids.get(ch)?.qty || 0;
      if (pq === 0 && q > 0) return { name: ch, qty: q, neu: q, wowQty: null, wowPct: null, sales: s };
      return { name: ch, qty: q, wowQty: q - pq, wowPct: pctChange(q, pq), sales: s };
    });
    const cur = sumRows(weekRows.filter((r) => r.lineup === name));
    const prev = sumRows(prevWeekRows.filter((r) => r.lineup === name));
    const wowPct = prev.qty || cur.qty ? pctChange(cur.qty, prev.qty) : null;
    detailCatalog[`product:${name}`] = {
      title: `[${name}] 세부 분석 · 채널별 (${weekKey(REF_DATE)})`,
      col1: "채널",
      rows: detailRows,
      insight: buildWhy({
        type: "product",
        name,
        wowPct,
        curQty: cur.qty,
        prevQty: prev.qty,
        curSales: cur.sales,
        relatedEvents: eventsForProduct(name),
        driverRows: detailRows,
      }),
    };
  });


  const correlations = promoEvents
    .filter((e) => e.overlapWeek)
    .map((e) => {
      const cur = sumRows(weekRows.filter((r) => (!e.product || r.lineup === e.product) && (r.channelGroup === e.group || r.channelRaw.startsWith(e.channel))));
      const prev = sumRows(prevWeekRows.filter((r) => (!e.product || r.lineup === e.product) && (r.channelGroup === e.group || r.channelRaw.startsWith(e.channel))));
      const wow = pctChange(cur.qty, prev.qty);
      return {
        event: `${e.channel} · ${e.eventName}`,
        product: e.product || "-",
        period: e.periodLabel,
        eventQty: e.qty,
        eventSales: e.sales,
        wowQtyPct: wow,
        story:
          e.qty > 0 && wow > 0
            ? "행사 실판매 + 주간 상승 — 리프트 정합"
            : e.qty > 0 && wow < 0
              ? "행사 실판매는 있으나 주간 하락 — 전주 대비 반동/잠식 점검"
              : e.qty === 0
                ? "일정만 있고 raw 판매 0 — 진행/집계 누락 의심"
                : "행사·주간 변동 약함",
        detailKey: e.product ? `product:${e.product}` : `channel:${e.group}`,
      };
    })
    .sort((a, b) => Math.abs(b.wowQtyPct) - Math.abs(a.wowQtyPct))
    .slice(0, 8);


  const events = [];
  bundle.promo.forEach((p) => {
    const start = parseDate(p[0]);
    const end = parseDate(p[1]);
    const channel = String(p[2] || "").trim();
    const slot = String(p[3] || "").trim();
    const eventName = String(p[4] || "").trim();
    const product = resolveLineup(String(p[5] || "").trim(), maps);
    if (!start || !end || !channel || !eventName) return;
    const days = Math.round((end - start) / 86400000) + 1;
    const preEnd = addDays(start, -1);
    const preStart = addDays(start, -14);
    const group = resolveGroup(channel, maps);

    const matchProduct = (r) => !product || r.lineup === product || r.productRaw === product;
    const matchChannel = (r) =>
      r.channelGroup === group || r.channelRaw === channel || r.channelRaw.startsWith(channel);

    const during = rows.filter(
      (r) => matchProduct(r) && matchChannel(r) && inRange(r.ship, start, end)
    );
    const before = rows.filter(
      (r) => matchProduct(r) && matchChannel(r) && inRange(r.ship, preStart, preEnd)
    );
    const dSum = sumRows(during);
    const bSum = sumRows(before);
    const eventDaily = days > 0 ? dSum.qty / days : 0;
    const baseDaily = bSum.qty / 14;
    let lift = -100;
    if (baseDaily > 0) lift = (eventDaily / baseDaily - 1) * 100;
    else if (eventDaily > 0) lift = 99999;

    events.push([
      channel,
      `${slot || "-"} / ${eventName || "-"}`,
      product || "(전체)",
      `${ymd(start)} ~ ${ymd(end)} (${days}일간)`,
      `${dSum.qty}개 (${Math.round(dSum.sales).toLocaleString("ko-KR")}원)`,
      baseDaily.toFixed(2),
      eventDaily.toFixed(2),
      lift,
    ]);
  });


  const checks = [
    {
      id: "raw",
      ok: rows.length > 0,
      label: "2 raw 통합 → KPI·채널믹스·포트폴리오·추이",
      detail: `유효 출고 행 ${rows.length}건`,
    },
    {
      id: "group",
      ok: maps.groupMap.size > 0,
      label: "3 채널그룹맵핑 → 채널 집계/기타온라인",
      detail: `맵핑 ${maps.groupMap.size}건`,
    },
    {
      id: "lineup",
      ok: maps.lineupMap.size > 0,
      label: "4 라인업매핑 → 제품 TOP·알림",
      detail: `맵핑 ${maps.lineupMap.size}건`,
    },
    {
      id: "major",
      ok: maps.major.size > 0,
      label: "5 채널설정 → 주요채널 정렬",
      detail: `주요채널 ${maps.major.size}개`,
    },
    {
      id: "promo",
      ok: bundle.promo.some((r) => String(r[0] || "").trim()),
      label: "1 프로모션 → 행사캘린더·ROI",
      detail: `프로모션 ${bundle.promo.filter((r) => r[0]).length}행`,
    },
    {
      id: "kpi",
      ok: week.sales > 0 || month.sales > 0,
      label: "매출 현황 요약 수치 산출",
      detail: `금주 ${Math.round(week.sales).toLocaleString("ko-KR")}원`,
    },
  ];

  return {
    brand,
    rows,
    kpi,
    mixRows,
    growth,
    decline,
    alerts: alertList,
    trend,
    detailCatalog,
    correlations,
    promoEvents: promoEvents.map((e) => ({
      channel: e.channel,
      group: e.group,
      eventName: e.eventName,
      product: e.product,
      start: ymd(e.start),
      end: ymd(e.end),
      periodLabel: e.periodLabel,
      overlapWeek: e.overlapWeek,
      qty: e.qty,
      sales: e.sales,
    })),
    events,
    checks,
    meta: {
      refDate: ymd(REF_DATE),
      weekKey: weekKey(REF_DATE),
      monthKey: monthKey(REF_DATE),
      anchor: anchored.anchor,
      fullMonth: ANCHOR_FULL_MONTH,
      weekRange: `${ymd(thisWeekStart)}~${ymd(thisWeekEnd)}`,
      monthRange: `${ymd(monthStart)}~${ymd(monthEnd)}`,
      prevMonthRange: `${ymd(prevMonthStart)}~${ymd(prevMonthEnd)}`,
      weekKeys: [...new Set(allRows.map((r) => r.week))].sort().reverse(),
      monthKeys: [...new Set(allRows.map((r) => r.mKey))].sort().reverse(),
      rawCount: rows.length,
      rawAllCount: allRows.length,
      rawSheetCount: Array.isArray(bundle.raw) ? bundle.raw.length : 0,
      rawSkipped: Math.max(0, rawSkipped),
      promoCount: bundle.promo.filter((r) => r[0]).length,
      weekEventCount: promoEvents.filter((e) => e.overlapWeek).length,
      categories: [...new Set(allRows.map((row) => row.category).filter(Boolean))].sort((a, b) =>
        a.localeCompare(b, "ko")
      ),
      category,
    },
  };
}

async function computeDashboardAsync(brand, options = {}) {
  const brandId =
    brand ||
    (typeof SheetSchema !== "undefined" ? SheetSchema.DEFAULT_BRAND_SLUG : "dreame");
  if (typeof Repository === "undefined") return computeDashboard(brandId, undefined, options);
  const bundle = await Repository.getBrandBundle(brandId);
  return computeDashboard(brandId, bundle, options);
}

window.computeDashboard = computeDashboard;
window.computeDashboardAsync = computeDashboardAsync;
window.REF_DATE = REF_DATE;
window.parseDate = parseDate;
window.ymd = ymd;
