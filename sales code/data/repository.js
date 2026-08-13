(function (global) {
  function backendMode() {
    const mode = String(global.DataConfig?.DATA_BACKEND || "api").trim().toLowerCase();
    if (mode === "local") return "local";
    if (mode === "sql" || mode === "postgres" || mode === "mysql" || mode === "api") return "api";
    return mode || "api";
  }

  function backend() {
    if (backendMode() === "local") {
      if (!global.LocalStore) throw new Error("[Repository] LocalStore 없음");
      return global.LocalStore;
    }
    if (!global.ApiStore) throw new Error("[Repository] ApiStore 없음");
    return global.ApiStore;
  }

  function notifyChanged(detail) {
    if (detail?.brandId) {
      delete Repository._bundleCache[detail.brandId];
      delete Repository._bundleCacheAt[detail.brandId];
      delete Repository._bundleInflight[detail.brandId];
      Repository._bundleGen[detail.brandId] =
        (Repository._bundleGen[detail.brandId] || 0) + 1;
    } else {
      Repository._bundleCache = Object.create(null);
      Repository._bundleCacheAt = Object.create(null);
      Repository._bundleInflight = Object.create(null);
      Repository._bundleGen = Object.create(null);
    }
    global.dispatchEvent(
      new CustomEvent("admin-sheets-updated", { detail: detail || null })
    );
  }

  function actorEmail() {
    const fromAuth = global.AuthGate?.user?.email;
    return String(fromAuth || "")
      .trim()
      .toLowerCase() || null;
  }

  const Repository = {
    _bundleCache: Object.create(null),
    _bundleCacheAt: Object.create(null),
    _bundleInflight: Object.create(null),
    _bundleGen: Object.create(null),
    BUNDLE_CACHE_TTL_MS: 120000,

    getBackendName() {
      return backendMode();
    },

    isApi() {
      return backendMode() === "api";
    },

    isFirestore() {
      return this.isApi();
    },

    async getBrands() {
      return backend().getBrands();
    },

    async createBrand(name) {
      const result = await backend().createBrand(name);
      notifyChanged({ action: "createBrand", name });
      return result;
    },

    async ensureDefaultBrand() {
      const name =
        global.SheetSchema?.DEFAULT_BRAND_NAME ||
        global.SheetSchema?.DEFAULT_BRAND?.name ||
        "드리미";
      if (typeof backend().ensureBrand === "function") {
        const result = await backend().ensureBrand(name);
        notifyChanged({ action: "ensureBrand", name });
        return result;
      }
      return this.createBrand(name);
    },

    async getSheet(brandId, sheetId) {
      return backend().getSheet(brandId, sheetId);
    },

    async getSheetPage(brandId, sheetId, options) {
      const store = backend();
      if (typeof store.getSheetPage === "function") {
        return store.getSheetPage(brandId, sheetId, options);
      }
      const full = await store.getSheet(brandId, sheetId);
      const off = Math.max(0, Math.floor(Number(options?.offset) || 0));
      const lim = Math.max(1, Math.min(500, Math.floor(Number(options?.limit) || 50)));
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

    async replaceSheet(brandId, sheetId, rows, options) {
      const result = await backend().replaceSheet(brandId, sheetId, rows, options);
      await backend().appendAudit?.({
        action: "replaceSheet",
        brandId,
        sheetId,
        rowCount: rows.length,
        email: actorEmail(),
      });
      notifyChanged({ action: "replaceSheet", brandId, sheetId, rowCount: rows.length });
      return result;
    },

    async upsertRows(brandId, sheetId, patches) {
      const result = await backend().upsertRows(brandId, sheetId, patches);
      notifyChanged({ action: "upsertRows", brandId, sheetId });
      return result;
    },

    async getBrandBundle(brandId, options = {}) {
      const id = String(brandId || "");
      const fresh = options?.fresh === true;
      const ttl = Repository.BUNDLE_CACHE_TTL_MS;
      if (
        !fresh &&
        id &&
        Repository._bundleCache[id] &&
        Date.now() - (Repository._bundleCacheAt[id] || 0) < ttl
      ) {
        return Repository._bundleCache[id];
      }
      if (!fresh && id && Repository._bundleInflight[id]) {
        return Repository._bundleInflight[id];
      }

      const run = (async () => {
        const gen = id ? Repository._bundleGen[id] || 0 : 0;
        const started = typeof performance !== "undefined" ? performance.now() : Date.now();
        const bundle = await backend().getBrandBundle(brandId);
        const ms = Math.round(
          (typeof performance !== "undefined" ? performance.now() : Date.now()) - started
        );
        console.info(`[Repository] getBrandBundle(${id}) ${ms}ms`, {
          raw: bundle?.raw?.length || 0,
          promo: bundle?.promo?.length || 0,
        });
        if (id && (Repository._bundleGen[id] || 0) === gen) {
          Repository._bundleCache[id] = bundle;
          Repository._bundleCacheAt[id] = Date.now();
        }
        return bundle;
      })();

      if (id) Repository._bundleInflight[id] = run;
      try {
        return await run;
      } finally {
        if (id && Repository._bundleInflight[id] === run) {
          delete Repository._bundleInflight[id];
        }
      }
    },

    async getBrandBundleFresh(brandId) {
      const id = String(brandId || "");
      if (id) {
        delete Repository._bundleCache[id];
        delete Repository._bundleCacheAt[id];
        delete Repository._bundleInflight[id];
        Repository._bundleGen[id] = (Repository._bundleGen[id] || 0) + 1;
      }
      return this.getBrandBundle(brandId, { fresh: true });
    },

    async getAuditLogs(brandId, limit = 10) {
      return backend().getAuditLogs?.(brandId, limit) || [];
    },

    subscribeBrand(brandId, onChange) {
      return backend().subscribeBrand(brandId, onChange);
    },

    notifyChanged,

    getAdminStoreSnapshot() {
      if (backendMode() !== "local") {
        return { brands: [], sheets: {} };
      }
      return global.LocalStore._readAll();
    },

    getBrandPromoRowsSync(brandId) {
      const id = brandId || global.SheetSchema?.DEFAULT_BRAND_SLUG || "dreame";
      const cached = Repository._bundleCache[id];
      if (cached && Array.isArray(cached.promo)) return cached.promo;
      if (backendMode() === "local") {
        return Repository.getAdminStoreSnapshot().sheets?.[id]?.promo || [];
      }
      return [];
    },

    getBrandSheetRowsSync(brandId, sheetId) {
      const id = brandId || global.SheetSchema?.DEFAULT_BRAND_SLUG || "dreame";
      const cached = Repository._bundleCache[id];
      if (cached && Array.isArray(cached[sheetId])) return cached[sheetId];
      if (backendMode() === "local") {
        return Repository.getAdminStoreSnapshot().sheets?.[id]?.[sheetId] || [];
      }
      return [];
    },
  };

  global.Repository = Repository;
  global.getAdminStore = () => Repository.getAdminStoreSnapshot();
  global.getBrandPromoRows = (brand) =>
    Repository.getBrandPromoRowsSync(brand || global.SheetSchema?.DEFAULT_BRAND_SLUG);
  global.getBrandSheetRows = (brand, sheetId) =>
    Repository.getBrandSheetRowsSync(brand, sheetId);
})(typeof window !== "undefined" ? window : globalThis);
