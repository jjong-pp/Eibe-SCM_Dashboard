(function (global) {
  function apiCfg() {
    return global.DataConfig?.API || {};
  }

  function authCfg() {
    return global.DataConfig?.AUTH || {};
  }

  function tokenKey() {
    return authCfg().tokenKey || "sales_hub_access_token";
  }

  function getToken() {
    try {
      return String(global.localStorage.getItem(tokenKey()) || "").trim();
    } catch {
      return "";
    }
  }

  function setToken(token) {
    try {
      if (token) global.localStorage.setItem(tokenKey(), String(token));
      else global.localStorage.removeItem(tokenKey());
    } catch {
      
    }
  }

  function joinUrl(base, prefix, path) {
    const b = String(base || "").replace(/\/+$/, "");
    const p = String(prefix || "").replace(/^\/+|\/+$/g, "");
    const rest = String(path || "").replace(/^\/+/, "");
    if (!b) return "";
    return [b, p, rest].filter(Boolean).join("/");
  }

  async function request(method, path, body) {
    const cfg = apiCfg();
    const url = joinUrl(cfg.baseUrl, cfg.prefix, path);
    if (!url) {
      throw new Error("API base URL is not configured");
    }
    const headers = {
      Accept: "application/json",
      "Content-Type": "application/json",
    };
    if (cfg.apiKey) headers["X-Api-Key"] = cfg.apiKey;
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    const controller = new AbortController();
    const timeout = Number(cfg.timeoutMs) > 0 ? Number(cfg.timeoutMs) : 15000;
    const timer = setTimeout(() => controller.abort(), timeout);
    let res;
    try {
      res = await fetch(url, {
        method,
        headers,
        body: body == null ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { raw: text };
    }
    if (!res.ok) {
      const err = new Error(data?.message || data?.error || `HTTP ${res.status}`);
      err.status = res.status;
      err.payload = data;
      throw err;
    }
    return data;
  }

  const ApiStore = {
    _ready: false,

    async init() {
      const cfg = apiCfg();
      if (!cfg.baseUrl) {
        throw new Error("SALES_HUB_API_BASE_URL is required");
      }
      if (cfg.healthPath) {
        try {
          await request("GET", cfg.healthPath);
        } catch {
          
        }
      }
      this._ready = true;
      return this;
    },

    async login(email, password) {
      const path = authCfg().loginPath || "/auth/login";
      const data = await request("POST", path, { email, password });
      const token = data?.accessToken || data?.token || "";
      if (!token) throw new Error("login response missing token");
      setToken(token);
      return data;
    },

    async me() {
      const path = authCfg().mePath || "/auth/me";
      return request("GET", path);
    },

    logout() {
      setToken("");
    },

    getToken,

    async getBrands() {
      const data = await request("GET", "/brands");
      return Array.isArray(data) ? data : data?.items || [];
    },

    async createBrand(name) {
      return request("POST", "/brands", { name: String(name || "").trim() });
    },

    async ensureBrand(name) {
      const brands = await this.getBrands();
      const hit = brands.find((b) => String(b.name || "") === String(name || ""));
      if (hit) return hit;
      return this.createBrand(name);
    },

    async getSheet(brandId, sheetId) {
      return request("GET", `/brands/${encodeURIComponent(brandId)}/sheets/${encodeURIComponent(sheetId)}`);
    },

    async getSheetPage(brandId, sheetId, options) {
      const off = Math.max(0, Math.floor(Number(options?.offset) || 0));
      const lim = Math.max(1, Math.min(500, Math.floor(Number(options?.limit) || 50)));
      return request(
        "GET",
        `/brands/${encodeURIComponent(brandId)}/sheets/${encodeURIComponent(sheetId)}?offset=${off}&limit=${lim}`
      );
    },

    async replaceSheet(brandId, sheetId, rows) {
      return request("PUT", `/brands/${encodeURIComponent(brandId)}/sheets/${encodeURIComponent(sheetId)}`, {
        rows,
      });
    },

    async upsertRows(brandId, sheetId, patches) {
      return request("PATCH", `/brands/${encodeURIComponent(brandId)}/sheets/${encodeURIComponent(sheetId)}/rows`, {
        patches,
      });
    },

    async getBrandBundle(brandId) {
      return request("GET", `/brands/${encodeURIComponent(brandId)}/bundle`);
    },

    async appendAudit(entry) {
      try {
        await request("POST", "/audit", entry || {});
      } catch {
        
      }
    },

    async getAuditLogs(brandId, limit = 10) {
      const data = await request(
        "GET",
        `/audit?brandId=${encodeURIComponent(brandId || "")}&limit=${encodeURIComponent(limit)}`
      );
      return Array.isArray(data) ? data : data?.items || [];
    },

    subscribeBrand(_brandId, _onChange) {
      return function unsubscribe() {};
    },
  };

  global.ApiStore = ApiStore;
  global.FirestoreStore = ApiStore;
})(typeof window !== "undefined" ? window : globalThis);
