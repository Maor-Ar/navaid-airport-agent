const PAGE = document.body?.dataset.page || "";

document.querySelectorAll("[data-nav]").forEach((link) => {
  if (link.dataset.nav === PAGE) {
    link.setAttribute("aria-current", "page");
  }
});

async function enhanceMermaid() {
  const nodes = document.querySelectorAll("pre.mermaid");
  if (!nodes.length) return;
  try {
    const { default: mermaid } = await import(
      "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"
    );
    mermaid.initialize({
      startOnLoad: false,
      theme: "base",
      securityLevel: "strict",
      themeVariables: {
        primaryColor: "#f3eee3",
        primaryTextColor: "#16130f",
        primaryBorderColor: "#8d6d32",
        lineColor: "#121a24",
        secondaryColor: "#efe8d8",
        tertiaryColor: "#faf7f0",
        fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
      },
    });
    await mermaid.run({ nodes: [...nodes] });
  } catch {
    /* Offline: leave the mermaid source readable in the pre. */
  }
}

enhanceMermaid();
