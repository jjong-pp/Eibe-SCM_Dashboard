
(function (global) {
  const SHEET_DEFS = [
    {
      id: "promo",
      label: "1 시트 프로모션",
      cols: [
        "시작일", "종료일", "채널", "구좌명", "드리미 행사명", "제품명",
        "정상가", "가격", "할인율", "적립금", "사은품", "비고",
        "채널 구분", "마케팅 여부", "확정여부",
      ],
    },
    {
      id: "raw",
      label: "2 시트 raw 통합",
      cols: [
        "Category", "채널", "제품명", "수량", "출고일", "주문일자",
        "년", "월", "주차", "주문번호", "고객명", "판매가", "판매가합", "채널구분",
      ],
    },
    {
      id: "channelGroup",
      label: "3 채널그룹맵핑",
      cols: ["채널", "채널 그룹"],
    },
    {
      id: "lineup",
      label: "4 라인업매핑",
      cols: ["원본 제품명", "라인업명"],
    },
    {
      id: "channelSetting",
      label: "5 채널설정",
      cols: ["주요채널"],
    },
  ];

  const SHEET_IDS = SHEET_DEFS.map((s) => s.id);
  const DEFAULT_BRAND_NAME = "드리미";
  const DEFAULT_BRAND_SLUG = "dreame";
  const DEFAULT_BRAND = {
    id: DEFAULT_BRAND_SLUG,
    name: DEFAULT_BRAND_NAME,
    slug: DEFAULT_BRAND_SLUG,
  };

  function slugifyBrand(name) {
    const value = String(name || "").trim();
    if (value === DEFAULT_BRAND_NAME) return DEFAULT_BRAND_SLUG;
    const ascii = value
      .normalize("NFKD")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    if (ascii) return ascii;
    let hash = 2166136261;
    for (const ch of value) {
      hash ^= ch.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return `brand-${(hash >>> 0).toString(36)}`;
  }

  
  const ANALYTICS_THRESHOLDS = {
    MIN_QTY_PORTFOLIO: 1,
    ALERT_PRODUCT_UP: 50,
    ALERT_PRODUCT_DOWN: -25,
    ALERT_CHANNEL_DOWN: -20,
    ALERT_MAX: 5,
  };

  function getSheetDef(sheetId) {
    return SHEET_DEFS.find((s) => s.id === sheetId) || null;
  }

  function emptyRow(cols) {
    return (cols || []).map(() => "");
  }

  function emptySheetRows(sheetId, count = 1) {
    const def = getSheetDef(sheetId);
    if (!def) return [];
    return Array.from({ length: count }, () => emptyRow(def.cols));
  }

  global.SheetSchema = {
    SHEET_DEFS,
    SHEET_IDS,
    DEFAULT_BRAND_NAME,
    DEFAULT_BRAND_SLUG,
    DEFAULT_BRAND,
    slugifyBrand,
    ANALYTICS_THRESHOLDS,
    getSheetDef,
    emptyRow,
    emptySheetRows,
  };
})(typeof window !== "undefined" ? window : globalThis);
