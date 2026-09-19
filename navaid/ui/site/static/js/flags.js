/** IATA → iso_region for inline state flags. All 14 product airports are US. */

export const IATA_ISO_REGION = {
  BOS: "US-MA",
  ORH: "US-MA",
  BDL: "US-CT",
  PVD: "US-RI",
  PWM: "US-ME",
  BGR: "US-ME",
  MHT: "US-NH",
  BTV: "US-VT",
  LAX: "US-CA",
  SNA: "US-CA",
  SFO: "US-CA",
  OAK: "US-CA",
  SJC: "US-CA",
  ANC: "US-AK",
};

export const IATA_CODES = Object.keys(IATA_ISO_REGION);

const IATA_RE = new RegExp(`\\b(${IATA_CODES.join("|")})\\b`, "g");

function flagUrl(code) {
  const region = IATA_ISO_REGION[code] || "US";
  const slug = String(region).toLowerCase();
  const path = `/static/flags/${slug}.svg`;
  return typeof window.navaidSite === "function" ? window.navaidSite(path) : path;
}

function iataSpanHtml(code) {
  const src = flagUrl(code);
  return `<span class="iata"><img class="flag" alt="" src="${src}" height="12"> ${code}</span>`;
}

function shouldSkip(node) {
  const parent = node.parentElement;
  if (!parent) return true;
  return Boolean(parent.closest("code, pre, .iata, a, script, style"));
}

export function decorateIata(root) {
  if (!root) return root;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    if (shouldSkip(walker.currentNode)) continue;
    IATA_RE.lastIndex = 0;
    if (IATA_RE.test(walker.currentNode.textContent || "")) nodes.push(walker.currentNode);
  }
  for (const node of nodes) {
    IATA_RE.lastIndex = 0;
    const html = String(node.textContent || "").replace(IATA_RE, (code) => iataSpanHtml(code));
    const wrap = document.createElement("span");
    wrap.innerHTML = html;
    node.replaceWith(...wrap.childNodes);
  }
  return root;
}
