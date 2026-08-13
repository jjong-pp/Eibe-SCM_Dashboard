
(function (global) {
  const ALLOWED_DOMAINS = Object.freeze(["@eibe.co.kr", "@btmall.kr"]);
  const MALL_SESSION_KEY = "eibe_staff_session_v1";
  const AUTH_STARTED_KEY = "eibe_auth_session_started_v1";
  const AUTH_SESSION_MAX_AGE_MS = 24 * 60 * 60 * 1000;
  const WORKSPACE_NEXT_KEY = "eibe_workspace_next_v1";

  function isAllowedWorkspaceEmail(email) {
    const e = String(email || "")
      .trim()
      .toLowerCase();
    const at = e.indexOf("@");
    if (at <= 0) return false;
    return ALLOWED_DOMAINS.some((domain) => e.endsWith(domain));
  }

  function readAuthStartedAt(email) {
    const em = String(email || "")
      .trim()
      .toLowerCase();
    if (!em) return 0;
    try {
      const raw = global.localStorage.getItem(AUTH_STARTED_KEY);
      if (raw) {
        const map = JSON.parse(raw);
        const fromMap = Number(map?.[em]);
        if (Number.isFinite(fromMap) && fromMap > 0) return fromMap;
      }
    } catch {
      
    }
    return 0;
  }

  function isAuthSessionExpired(email, sessionStartedAt) {
    const em = String(email || "")
      .trim()
      .toLowerCase();
    if (!em) return true;
    let started = readAuthStartedAt(em);
    if (!started) {
      const fromSession = Number(sessionStartedAt);
      if (Number.isFinite(fromSession) && fromSession > 0) started = fromSession;
    }
    
    if (!started) return true;
    return Date.now() - started >= AUTH_SESSION_MAX_AGE_MS;
  }

  function clearMallStaffSession() {
    try {
      global.localStorage.removeItem(MALL_SESSION_KEY);
    } catch {
      
    }
  }

  function readMallStaffSession() {
    try {
      const raw = global.localStorage.getItem(MALL_SESSION_KEY);
      if (!raw) return null;
      const u = JSON.parse(raw);
      const email = String(u?.email || "")
        .trim()
        .toLowerCase();
      if (!isAllowedWorkspaceEmail(email)) {
        clearMallStaffSession();
        return null;
      }
      if (u && Object.prototype.hasOwnProperty.call(u, "emailVerified") && u.emailVerified !== true) {
        clearMallStaffSession();
        return null;
      }
      if (isAuthSessionExpired(email, u?.authStartedAt)) {
        clearMallStaffSession();
        return null;
      }
      const name = String(u?.name || u?.displayName || "").trim() || email.split("@")[0];
      return { name, email };
    } catch {
      clearMallStaffSession();
      return null;
    }
  }

  
  function mallLoginUrl(nextPath) {
    const next =
      typeof nextPath === "string" && nextPath
        ? nextPath
        : global.location.pathname + global.location.search;
    try {
      const url = new URL("../index.html", global.location.href);
      url.searchParams.set("from", "workspace");
      url.searchParams.set("next", next);
      return url.href;
    } catch {
      try {
        const url = new URL("/index.html", global.location.origin);
        url.searchParams.set("from", "workspace");
        url.searchParams.set("next", next);
        return url.href;
      } catch {
        return "../index.html?from=workspace";
      }
    }
  }

  function markPending() {
    try {
      global.document.documentElement.classList.add("eibe-sso-pending");
      global.document.documentElement.classList.remove("eibe-sso-ok");
    } catch {
      
    }
  }

  function markOk() {
    try {
      global.document.documentElement.classList.add("eibe-sso-ok");
      global.document.documentElement.classList.remove("eibe-sso-pending");
    } catch {
      
    }
  }

  function redirectToMallLogin(nextPath) {
    markPending();
    global.__EIBE_WORKSPACE_SSO_OK__ = false;
    global.EibeMallSso = null;
    try {
      const next =
        typeof nextPath === "string" && nextPath
          ? nextPath
          : global.location.pathname + global.location.search;
      global.sessionStorage.setItem(WORKSPACE_NEXT_KEY, next);
    } catch {
      
    }
    global.location.replace(mallLoginUrl(nextPath));
  }

  const session = readMallStaffSession();
  if (!session) {
    redirectToMallLogin();
    return;
  }

  global.__EIBE_WORKSPACE_SSO_OK__ = true;
  global.EibeMallSso = {
    session,
    allowedDomains: ALLOWED_DOMAINS,
    redirectToMallLogin,
    isAllowedWorkspaceEmail,
    readMallStaffSession,
  };
  markOk();
})(typeof window !== "undefined" ? window : globalThis);
