(function (global) {
  function str(v, fallback) {
    const s = String(v == null ? "" : v).trim();
    return s || fallback;
  }
  function bool(v, fallback) {
    const s = String(v == null ? "" : v).trim().toLowerCase();
    if (!s) return fallback;
    return s === "1" || s === "true" || s === "yes" || s === "on";
  }
  function num(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  const staffDomains = [
    str(global.SALES_HUB_STAFF_DOMAIN_1, ""),
    str(global.SALES_HUB_STAFF_DOMAIN_2, ""),
    str(global.SALES_HUB_STAFF_DOMAIN_3, ""),
    str(global.SALES_HUB_STAFF_DOMAIN_4, ""),
  ].filter(Boolean);

  const DataConfig = {
    DATA_BACKEND: str(global.SALES_HUB_DATA_BACKEND, "local"),
    LOCAL_STORAGE_KEY: str(global.SALES_HUB_LOCAL_STORAGE_KEY, "sales_hub_demo_v1"),
    SEED_SAMPLE_DATA: bool(global.SALES_HUB_SEED_SAMPLE_DATA, true),
    REF_DATE_OVERRIDE: str(global.SALES_HUB_REF_DATE_OVERRIDE, "") || null,
    WRITE_BATCH_SIZE: num(global.SALES_HUB_WRITE_BATCH_SIZE, 200),
    DEV_BYPASS_AUTH: bool(global.SALES_HUB_DEV_BYPASS_AUTH, true),
    API: {
      baseUrl: str(global.SALES_HUB_API_BASE_URL, ""),
      prefix: str(global.SALES_HUB_API_PREFIX, ""),
      timeoutMs: num(global.SALES_HUB_API_TIMEOUT_MS, 0),
      retryCount: num(global.SALES_HUB_API_RETRY_COUNT, 0),
      apiKey: str(global.SALES_HUB_API_KEY, ""),
      clientId: str(global.SALES_HUB_API_CLIENT_ID, ""),
      clientSecret: str(global.SALES_HUB_API_CLIENT_SECRET, ""),
      healthPath: str(global.SALES_HUB_SERVER_HEALTH_PATH, ""),
      corsOrigin: str(global.SALES_HUB_CORS_ORIGIN, ""),
      uploadMaxMb: num(global.SALES_HUB_UPLOAD_MAX_MB, 0),
      region: str(global.SALES_HUB_SERVER_REGION, ""),
    },
    AUTH: {
      mode: str(global.SALES_HUB_AUTH_MODE, ""),
      tokenKey: str(global.SALES_HUB_AUTH_TOKEN_KEY, ""),
      loginPath: str(global.SALES_HUB_AUTH_LOGIN_PATH, ""),
      refreshPath: str(global.SALES_HUB_AUTH_REFRESH_PATH, ""),
      mePath: str(global.SALES_HUB_AUTH_ME_PATH, ""),
      jwtAudience: str(global.SALES_HUB_JWT_AUDIENCE, ""),
      jwtIssuer: str(global.SALES_HUB_JWT_ISSUER, ""),
    },
    SQL: {
      dialect: str(global.SALES_HUB_SQL_DIALECT, ""),
      host: str(global.SALES_HUB_SQL_HOST, ""),
      port: str(global.SALES_HUB_SQL_PORT, ""),
      database: str(global.SALES_HUB_SQL_DATABASE, ""),
      user: str(global.SALES_HUB_SQL_USER, ""),
      password: str(global.SALES_HUB_SQL_PASSWORD, ""),
      ssl: bool(global.SALES_HUB_SQL_SSL, false),
      poolMin: num(global.SALES_HUB_SQL_POOL_MIN, 0),
      poolMax: num(global.SALES_HUB_SQL_POOL_MAX, 0),
      schema: str(global.SALES_HUB_SQL_SCHEMA, ""),
      migrationsPath: str(global.SALES_HUB_SQL_MIGRATIONS_PATH, ""),
    },
    SSO: {
      enabled: bool(global.SALES_HUB_SSO_ENABLED, false),
      mallLoginPath: str(global.SALES_HUB_SSO_MALL_LOGIN_PATH, ""),
      sessionKey: str(global.SALES_HUB_SSO_SESSION_KEY, ""),
      authStartedKey: str(global.SALES_HUB_SSO_AUTH_STARTED_KEY, ""),
      maxAgeMs: num(global.SALES_HUB_SSO_MAX_AGE_MS, 0),
      staffDomains,
    },
    APP: {
      name: str(global.SALES_HUB_PUBLIC_APP_NAME, ""),
      tagline: str(global.SALES_HUB_PUBLIC_APP_TAGLINE, ""),
      locale: str(global.SALES_HUB_DEFAULT_LOCALE, ""),
      timezone: str(global.SALES_HUB_DEFAULT_TIMEZONE, ""),
      currency: str(global.SALES_HUB_DEFAULT_CURRENCY, ""),
      defaultBrandId: str(global.SALES_HUB_DEFAULT_BRAND_ID, ""),
      supportEmail: str(global.SALES_HUB_SUPPORT_EMAIL, ""),
      supportSlackChannel: str(global.SALES_HUB_SUPPORT_SLACK_CHANNEL, ""),
      netlifySiteUrl: str(global.SALES_HUB_NETLIFY_SITE_URL, ""),
    },
    RUNTIME: {
      chartDefaultRangeDays: num(global.SALES_HUB_CHART_DEFAULT_RANGE_DAYS, 0),
      trendCacheTtlMs: num(global.SALES_HUB_TREND_CACHE_TTL_MS, 0),
      exportMaxRows: num(global.SALES_HUB_EXPORT_MAX_ROWS, 0),
      logLevel: str(global.SALES_HUB_LOG_LEVEL, ""),
      chartJsUrl: str(global.SALES_HUB_CDN_CHARTJS_URL, ""),
      sheetJsUrl: str(global.SALES_HUB_CDN_SHEETJS_URL, ""),
    },
    FEATURES: {
      calendar: bool(global.SALES_HUB_FEATURE_CALENDAR, false),
      multiBrand: bool(global.SALES_HUB_FEATURE_MULTI_BRAND, false),
      roi: bool(global.SALES_HUB_FEATURE_ROI, false),
      portfolio: bool(global.SALES_HUB_FEATURE_PORTFOLIO, false),
      events: bool(global.SALES_HUB_FEATURE_EVENTS, false),
      mix: bool(global.SALES_HUB_FEATURE_MIX, false),
      why: bool(global.SALES_HUB_FEATURE_WHY, false),
      adminImport: bool(global.SALES_HUB_FEATURE_ADMIN_IMPORT, false),
      adminExport: bool(global.SALES_HUB_FEATURE_ADMIN_EXPORT, false),
    },
  };

  global.DataConfig = DataConfig;
})(typeof window !== "undefined" ? window : globalThis);
