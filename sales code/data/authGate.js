(function (global) {
  let resolveReady;
  let readySettled = false;
  const ready = new Promise((resolve) => {
    resolveReady = resolve;
  });

  function settleReady() {
    if (readySettled) return;
    readySettled = true;
    resolveReady(AuthGate);
  }

  function hideAuthGate() {
    const gate = document.getElementById("authGate");
    if (gate) gate.hidden = true;
  }

  function enterDemo() {
    this.role = "admin";
    this.user = { uid: "demo", email: "demo@local" };
    hideAuthGate();
    document.documentElement.classList.add("eibe-sso-ok");
    document.documentElement.classList.remove("eibe-sso-pending");
    settleReady();
  }

  const AuthGate = {
    role: null,
    user: null,
    ready,
    isAdmin() {
      return this.role === "admin";
    },
    async init() {
      const apiBase = String(global.DataConfig?.API?.baseUrl || "").trim();
      const mode = String(global.DataConfig?.DATA_BACKEND || "").trim().toLowerCase();
      const useLocal = !mode || mode === "local" || !apiBase;

      if (useLocal) {
        if (!global.DataConfig.DATA_BACKEND) global.DataConfig.DATA_BACKEND = "local";
        if (!global.DataConfig.LOCAL_STORAGE_KEY) {
          global.DataConfig.LOCAL_STORAGE_KEY = "sales_hub_demo_v1";
        }
        if (global.DataConfig.SEED_SAMPLE_DATA == null) {
          global.DataConfig.SEED_SAMPLE_DATA = true;
        }
        enterDemo.call(this);
        return;
      }

      try {
        await global.ApiStore.init();
        const token = global.ApiStore.getToken?.();
        if (token) {
          const me = await global.ApiStore.me();
          const email = String(me?.email || "").trim().toLowerCase();
          this.user = { uid: me.id || me.uid || email, email, ...me };
          this.role = me.role === "viewer" ? "viewer" : "admin";
          hideAuthGate();
          document.documentElement.classList.add("eibe-sso-ok");
          settleReady();
          return;
        }
      } catch {
        
      }

      enterDemo.call(this);
    },
  };

  global.AuthGate = AuthGate;
  AuthGate.init().catch(() => {
    AuthGate.role = "admin";
    AuthGate.user = { uid: "demo", email: "demo@local" };
    document.getElementById("authGate")?.setAttribute("hidden", "");
    document.documentElement.classList.add("eibe-sso-ok");
    if (!readySettled) {
      readySettled = true;
      resolveReady(AuthGate);
    }
  });
})(typeof window !== "undefined" ? window : globalThis);
