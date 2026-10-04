
(function (global) {
  function attrs(_key, className) {
    return className ? ` class="${String(className).replace(/"/g, "")}"` : "";
  }

  function applyEl() {}
  function applyStatic() {}
  function tip() {
    return "";
  }

  global.DashSource = { tip, attrs, applyEl, applyStatic, tips: {} };
})(typeof window !== "undefined" ? window : globalThis);
