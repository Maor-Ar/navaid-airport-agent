(function () {
  const fallback = { api: "", root: "" };
  let cfg = fallback;
  const el = document.getElementById("navaid-config");
  if (el) {
    try {
      cfg = Object.assign({}, fallback, JSON.parse(el.textContent || "{}"));
    } catch {
      cfg = fallback;
    }
  }
  window.NAVAID = cfg;

  window.navaidSite = function navaidSite(path) {
    const p = path.startsWith("/") ? path : `/${path}`;
    const root = String(window.NAVAID.root || "").replace(/\/$/, "");
    return `${root}${p}`;
  };

  window.navaidApi = function navaidApi(path) {
    const p = path.startsWith("/") ? path : `/${path}`;
    const api = String(window.NAVAID.api || "").replace(/\/$/, "");
    return `${api}${p}`;
  };
})();
