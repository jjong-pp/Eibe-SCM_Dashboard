
(function (global) {
  const STORE_VERSION = 4;

  function schema() {
    return global.SheetSchema;
  }

  function storageKey() {
    return global.DataConfig.LOCAL_STORAGE_KEY;
  }

  function blankSheets(count = 1) {
    return Object.fromEntries(
      schema().SHEET_IDS.map((id) => [id, schema().emptySheetRows(id, count)])
    );
  }

  function shouldSeedSample() {
    return !!(global.DataConfig && global.DataConfig.SEED_SAMPLE_DATA && global.SampleData?.buildSampleSheets);
  }

  function defaultStore() {
    const brand = { ...schema().DEFAULT_BRAND };
    const sheets = shouldSeedSample()
      ? structuredClone(global.SampleData.buildSampleSheets())
      : blankSheets(1);
    return {
      version: STORE_VERSION,
      seeded: shouldSeedSample(),
      brands: [brand],
      sheets: {
        [brand.id]: sheets,
      },
      auditLogs: [],
    };
  }

  function normalizeBrand(value) {
    if (value && typeof value === "object") {
      const name = String(value.name || value.slug || value.id || "").trim();
      const slug = String(value.slug || value.id || schema().slugifyBrand(name));
      return { id: slug, name, slug };
    }
    const name = String(value || "").trim();
    const slug = schema().slugifyBrand(name);
    return { id: slug, name, slug };
  }

  function migrate(parsed) {
    const brands = (parsed.brands || []).map(normalizeBrand);
    if (!brands.length) return defaultStore();
    const oldSheets = parsed.sheets || {};
    const sheets = {};
    brands.forEach((brand) => {
      sheets[brand.id] =
        oldSheets[brand.id] ||
        oldSheets[brand.slug] ||
        oldSheets[brand.name] ||
        blankSheets();
    });
    return {
      version: STORE_VERSION,
      seeded: parsed.seeded !== false,
      brands,
      sheets,
      auditLogs: Array.isArray(parsed.auditLogs) ? parsed.auditLogs : [],
    };
  }

  function read() {
    try {
      const raw = localStorage.getItem(storageKey());
      if (!raw) {
        const initial = defaultStore();
        write(initial);
        return initial;
      }
      const parsed = JSON.parse(raw);
      const migrated = migrate(parsed);
      if (parsed.version !== STORE_VERSION || typeof parsed.brands?.[0] === "string") {
        write(migrated);
      }
      return migrated;
    } catch (error) {
      console.warn("[LocalStore] 저장 데이터를 읽지 못해 초기화합니다.", error);
      return defaultStore();
    }
  }

  function write(store) {
    localStorage.setItem(storageKey(), JSON.stringify(store));
  }

  function requireBrand(store, brandId) {
    const brand = store.brands.find((item) => item.id === brandId);
    if (!brand) throw new Error(`unknown brand: ${brandId}`);
    return brand;
  }

  const LocalStore = {
    async init() {
      read();
      return this;
    },

    async getBrands() {
      return structuredClone(read().brands);
    },

    async createBrand(name) {
      return this.ensureBrand(name);
    },

    async ensureBrand(name) {
      const store = read();
      const slug = schema().slugifyBrand(name);
      const displayName = String(name || schema().DEFAULT_BRAND_NAME).trim();
      let brand = store.brands.find((item) => item.id === slug || item.name === displayName);
      if (!brand) {
        brand = { id: slug, name: displayName, slug };
        store.brands.push(brand);
      }
      if (!store.sheets[slug]) store.sheets[slug] = blankSheets(1);
      schema().SHEET_IDS.forEach((sheetId) => {
        if (!store.sheets[slug][sheetId]) {
          store.sheets[slug][sheetId] = schema().emptySheetRows(sheetId, 1);
        }
      });
      write(store);
      return structuredClone(brand);
    },

    async getSheet(brandId, sheetId) {
      const store = read();
      requireBrand(store, brandId);
      const def = schema().getSheetDef(sheetId);
      if (!def) throw new Error("unknown sheet: " + sheetId);
      const rows = store.sheets[brandId]?.[sheetId] || schema().emptySheetRows(sheetId, 1);
      return { columns: def.cols.slice(), rows: structuredClone(rows) };
    },

    async getSheetPage(brandId, sheetId, { offset = 0, limit = 50 } = {}) {
      const full = await LocalStore.getSheet(brandId, sheetId);
      const off = Math.max(0, Math.floor(Number(offset) || 0));
      const lim = Math.max(1, Math.min(500, Math.floor(Number(limit) || 50)));
      const all = Array.isArray(full.rows) ? full.rows : [];
      const rows = all.slice(off, off + lim);
      return {
        columns: full.columns,
        rows,
        offset: off,
        total: all.length,
        hasMore: off + rows.length < all.length,
      };
    },

    async replaceSheet(brandId, sheetId, rows, _options) {
      const store = read();
      requireBrand(store, brandId);
      const def = schema().getSheetDef(sheetId);
      if (!def) throw new Error("unknown sheet: " + sheetId);
      if (!store.sheets[brandId]) store.sheets[brandId] = {};
      store.sheets[brandId][sheetId] = structuredClone(rows);
      write(store);
      return { columns: def.cols.slice(), rows: structuredClone(rows) };
    },

    async upsertRows(brandId, sheetId, patches) {
      const { rows } = await LocalStore.getSheet(brandId, sheetId);
      patches.forEach(({ index, cells }) => {
        while (rows.length <= index) {
          rows.push(schema().emptyRow(schema().getSheetDef(sheetId).cols));
        }
        rows[index] = cells;
      });
      return LocalStore.replaceSheet(brandId, sheetId, rows);
    },

    async getBrandBundle(brandId) {
      const store = read();
      requireBrand(store, brandId);
      const sheets = store.sheets[brandId] || {};
      return {
        brand: brandId,
        promo: structuredClone(sheets.promo || []),
        raw: structuredClone(sheets.raw || []),
        channelGroup: structuredClone(sheets.channelGroup || []),
        lineup: structuredClone(sheets.lineup || []),
        channelSetting: structuredClone(sheets.channelSetting || []),
      };
    },

    async appendAudit(entry) {
      const store = read();
      const max = 10;
      store.auditLogs.unshift({
        id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        at: new Date().toISOString(),
        ...entry,
      });

      const brandId = entry?.brandId;
      const kept = [];
      const perBrand = Object.create(null);
      for (const log of store.auditLogs) {
        const key = log.brandId || "_";
        perBrand[key] = (perBrand[key] || 0) + 1;
        if (perBrand[key] <= max) kept.push(log);
      }
      store.auditLogs = kept;
      write(store);
    },

    async getAuditLogs(brandId, limit = 10) {
      return read()
        .auditLogs.filter((entry) => !brandId || entry.brandId === brandId)
        .slice(0, Math.min(limit, 10));
    },

    subscribeBrand(brandId, onChange) {
      LocalStore.getBrandBundle(brandId).then(onChange);
      return () => {};
    },

    _readAll() {
      return read();
    },
  };

  global.LocalStore = LocalStore;
})(typeof window !== "undefined" ? window : globalThis);
