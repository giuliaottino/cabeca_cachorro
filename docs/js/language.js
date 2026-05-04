(function () {
  "use strict";

  const DEFAULT_LANGUAGE = "pt";
  const STORAGE_KEYS = ["tsiino-language", "site-language"];
  const SYSTEM_LANGUAGES = ["pt", "pt-BR"];

  const EXCLUDE_SELECTOR = [
    "script", "style", "noscript", "template", "canvas", "iframe",
    "pre", "code", "kbd", "samp",
    ".leaflet-container", ".leaflet-control", ".leaflet-pane",
    ".quarto-code-tools-source", ".sourceCode"
  ].join(",");

  const BLOCK_SELECTOR = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "figcaption", "blockquote", "li", "button", "a",
    ".hero-kicker", ".hero-subtitle", ".hero-description",
    ".about-eyebrow", ".method-eyebrow", ".feature-eyebrow",
    ".about-display-title", ".about-pullquote",
    ".objective-kicker", ".expedition-date", ".media-date",
    ".media-panel-label", ".researchers-kicker", ".researchers-label",
    ".project-map-header h3", ".project-map-header p",
    ".about-stat span", ".feature-title", ".feature-panel h3", ".feature-panel p",
    ".method-step h3", ".method-step p", ".impact-card h3", ".impact-card p",
    ".empty-media", ".btn-main", ".btn-ghost", ".media-link",
    ".metric-label", ".metric-sub", ".panel-title", ".chart-title", ".dashboard-title",
    ".card-title", ".card-subtitle", ".card-text", ".section-title h2"
  ].join(",");

  const ATTRIBUTE_NAMES = [
    "alt", "title", "placeholder", "aria-label", "data-label", "data-tip"
  ];

  let isApplying = false;
  let observer = null;
  let mutationTimer = null;
  const mapCache = new Map();
  const originalTextNodes = new WeakMap();

  function cfg() {
    return window.TRANSLATIONS || {};
  }

  function normalize(text) {
    return String(text || "")
      .replace(/\u00a0/g, " ")
      .replace(/[\r\n\t]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function escapeRegExp(text) {
    return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function getSupportedLanguages() {
    const c = cfg();
    if (Array.isArray(c.supportedLanguages) && c.supportedLanguages.length) {
      return c.supportedLanguages;
    }
    if (c.languages && typeof c.languages === "object") {
      const keys = Object.keys(c.languages);
      if (keys.length) return keys;
    }
    return ["pt", "en"];
  }

  function getSavedLanguage() {
    for (const key of STORAGE_KEYS) {
      const value = localStorage.getItem(key);
      if (value) return value;
    }
    return null;
  }

  function getCurrentLanguage() {
    const supported = getSupportedLanguages();
    const saved = getSavedLanguage();
    if (saved && supported.includes(saved)) return saved;
    return cfg().defaultLanguage || DEFAULT_LANGUAGE;
  }

  function setCurrentLanguage(language) {
    STORAGE_KEYS.forEach(function (key) {
      localStorage.setItem(key, language);
    });
  }

  function nextLanguage(language) {
    const supported = getSupportedLanguages();
    if (supported.length <= 1) return language;
    const index = supported.indexOf(language);
    const safeIndex = index >= 0 ? index : 0;
    return supported[(safeIndex + 1) % supported.length];
  }

  function isDefaultLanguage(language) {
    return language === (cfg().defaultLanguage || DEFAULT_LANGUAGE) || SYSTEM_LANGUAGES.includes(language);
  }

  function isExcluded(nodeOrElement) {
    const element = nodeOrElement && nodeOrElement.nodeType === Node.ELEMENT_NODE
      ? nodeOrElement
      : nodeOrElement && nodeOrElement.parentElement;
    if (!element) return true;
    return Boolean(element.closest(EXCLUDE_SELECTOR));
  }

  function getDictionarySections() {
    const dictionary = cfg().dictionary || {};
    return Object.keys(dictionary)
      .map(function (key) { return dictionary[key]; })
      .filter(function (section) { return section && typeof section === "object"; });
  }

  function buildMaps(targetLanguage) {
    if (mapCache.has(targetLanguage)) return mapCache.get(targetLanguage);

    const exact = new Map();
    const phrases = [];

    getDictionarySections().forEach(function (section) {
      Object.keys(section).forEach(function (sourceText) {
        const entry = section[sourceText];
        if (!entry || typeof entry !== "object") return;
        const translated = entry[targetLanguage];
        if (!translated || typeof translated !== "string") return;

        const key = normalize(sourceText);
        const value = String(translated);
        if (!key || !normalize(value)) return;

        exact.set(key, value);
        if (key.length >= 8) {
          phrases.push({ from: String(sourceText), fromNorm: key, to: value });
        }
      });
    });

    phrases.sort(function (a, b) {
      return b.fromNorm.length - a.fromNorm.length;
    });

    const maps = { exact: exact, phrases: phrases };
    mapCache.set(targetLanguage, maps);
    return maps;
  }

  function structuredLookup(path, language) {
    const root = cfg()[language];
    if (!root) return undefined;
    return String(path || "").split(".").reduce(function (obj, part) {
      return obj && obj[part];
    }, root);
  }

  function saveOriginalHtml(element) {
    if (!element.dataset.tsiinoOriginalHtml) {
      element.dataset.tsiinoOriginalHtml = element.innerHTML;
    }
  }

  function saveOriginalAttribute(element, attr) {
    const key = "tsiinoOriginal" + attr.replace(/[^a-z0-9]/gi, "_");
    if (!element.dataset[key] && element.hasAttribute(attr)) {
      element.dataset[key] = element.getAttribute(attr) || "";
    }
    return key;
  }

  function restoreOriginals() {
    document.querySelectorAll("[data-tsiino-original-html]").forEach(function (element) {
      element.innerHTML = element.dataset.tsiinoOriginalHtml;
      delete element.dataset.tsiinoOriginalHtml;
    });

    ATTRIBUTE_NAMES.forEach(function (attr) {
      const key = "tsiinoOriginal" + attr.replace(/[^a-z0-9]/gi, "_");
      document.querySelectorAll("[data-" + key.replace(/[A-Z]/g, function (m) { return "-" + m.toLowerCase(); }) + "]").forEach(function (element) {
        if (element.dataset[key] !== undefined) {
          element.setAttribute(attr, element.dataset[key]);
          delete element.dataset[key];
        }
      });
    });

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (isExcluded(node)) return NodeFilter.FILTER_REJECT;
        return originalTextNodes.has(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      }
    });

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      const original = originalTextNodes.get(node);
      if (original !== undefined) node.nodeValue = original;
      originalTextNodes.delete(node);
    });
  }

  function translateWholeBlock(element, maps) {
    if (!element || isExcluded(element)) return;
    if (element.id === "language-toggle" || element.closest("#language-toggle")) return;
    if (element.closest(".navbar") && !element.matches(".navbar a, .navbar span, .navbar button")) return;
    if (element.querySelector("img, video, iframe, canvas, input, select, textarea")) return;

    const sourceText = element.dataset.tsiinoOriginalHtml
      ? normalize(element.dataset.tsiinoOriginalHtml.replace(/<[^>]+>/g, " "))
      : normalize(element.textContent);

    if (!sourceText) return;
    const translated = maps.exact.get(sourceText);
    if (!translated) return;

    saveOriginalHtml(element);
    if (element.textContent !== translated) {
      element.textContent = translated;
    }
  }

  function translateTextNode(node, maps) {
    if (!node || isExcluded(node)) return;
    const parent = node.parentElement;
    if (!parent) return;
    if (parent.closest("#language-toggle")) return;

    const original = originalTextNodes.get(node) || node.nodeValue;
    const normalized = normalize(original);
    if (!normalized) return;

    let translated = maps.exact.get(normalized);

    if (!translated) {
      translated = String(original);
      maps.phrases.forEach(function (item) {
        if (translated.includes(item.from)) {
          translated = translated.split(item.from).join(item.to);
          return;
        }
        try {
          const pattern = new RegExp(escapeRegExp(item.from).replace(/\s+/g, "\\s+"), "g");
          translated = translated.replace(pattern, item.to);
        } catch (error) {
          // Keep original fragment if regex fails.
        }
      });
      if (translated === original) return;
    }

    if (!originalTextNodes.has(node)) originalTextNodes.set(node, original);
    node.nodeValue = translated;
  }

  function translateTextNodes(root, maps) {
    const walker = document.createTreeWalker(root || document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (isExcluded(node)) return NodeFilter.FILTER_REJECT;
        if (!normalize(node.nodeValue)) return NodeFilter.FILTER_SKIP;
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) { translateTextNode(node, maps); });
  }

  function translateAttributes(root, maps) {
    ATTRIBUTE_NAMES.forEach(function (attr) {
      (root || document).querySelectorAll("[" + attr + "]").forEach(function (element) {
        if (isExcluded(element)) return;
        const originalKey = saveOriginalAttribute(element, attr);
        const original = element.dataset[originalKey] || element.getAttribute(attr) || "";
        const normalized = normalize(original);
        if (!normalized) return;

        let translated = maps.exact.get(normalized);
        if (!translated) {
          translated = String(original);
          maps.phrases.forEach(function (item) {
            if (translated.includes(item.from)) translated = translated.split(item.from).join(item.to);
          });
          if (translated === original) return;
        }
        element.setAttribute(attr, translated);
      });
    });
  }

  function translateDataI18n(language) {
    document.querySelectorAll("[data-i18n]").forEach(function (element) {
      if (isExcluded(element)) return;
      const value = structuredLookup(element.getAttribute("data-i18n"), language);
      if (value !== undefined) {
        saveOriginalHtml(element);
        element.textContent = String(value).trim();
      }
    });

    document.querySelectorAll("[data-i18n-html]").forEach(function (element) {
      if (isExcluded(element)) return;
      const value = structuredLookup(element.getAttribute("data-i18n-html"), language);
      if (value !== undefined) {
        saveOriginalHtml(element);
        element.innerHTML = String(value).trim();
      }
    });

    [
      ["data-i18n-alt", "alt"],
      ["data-i18n-title", "title"],
      ["data-i18n-placeholder", "placeholder"],
      ["data-i18n-aria", "aria-label"],
      ["data-i18n-tip", "data-tip"]
    ].forEach(function (pair) {
      document.querySelectorAll("[" + pair[0] + "]").forEach(function (element) {
        if (isExcluded(element)) return;
        const value = structuredLookup(element.getAttribute(pair[0]), language);
        if (value !== undefined) {
          saveOriginalAttribute(element, pair[1]);
          element.setAttribute(pair[1], String(value).trim());
        }
      });
    });
  }

  function translateBlocks(root, maps) {
    (root || document).querySelectorAll(BLOCK_SELECTOR).forEach(function (element) {
      translateWholeBlock(element, maps);
    });
  }

  function translateQuartoUI(language, maps) {
    const langCfg = cfg().languages && cfg().languages[language];
    const searchText = language === "en" ? "Search" : "Buscar";

    document.querySelectorAll("input[type='search'], .aa-Input").forEach(function (input) {
      if (!input.dataset.tsiinoOriginalPlaceholder && input.hasAttribute("placeholder")) {
        input.dataset.tsiinoOriginalPlaceholder = input.getAttribute("placeholder") || "";
      }
      input.setAttribute("placeholder", searchText);
      input.setAttribute("aria-label", searchText);
    });

    if (langCfg && langCfg.htmlLang) {
      document.documentElement.lang = langCfg.htmlLang;
    } else {
      document.documentElement.lang = language === "en" ? "en" : "pt-BR";
    }
  }

  function translateSvgAndCharts(root, maps) {
    (root || document).querySelectorAll("svg text, .js-plotly-plot text, .legendtext, .gtitle, .xtitle, .ytitle").forEach(function (element) {
      if (isExcluded(element)) return;
      translateWholeBlock(element, maps);
      element.childNodes.forEach(function (node) {
        if (node.nodeType === Node.TEXT_NODE) translateTextNode(node, maps);
      });
    });
  }

  function getScriptBasePath() {
    const scripts = Array.from(document.querySelectorAll("script[src]"));
    const script = scripts.find(function (s) {
      return /(^|\/)js\/language\.js(\?|#|$)/.test(s.getAttribute("src") || "");
    });

    if (!script) return "/";

    try {
      const url = new URL(script.getAttribute("src"), window.location.href);
      return url.pathname.replace(/js\/language\.js.*$/, "");
    } catch (error) {
      return "/";
    }
  }

  function getPathInsideSite() {
    let path = window.location.pathname;
    const base = getScriptBasePath();

    if (base && base !== "/" && path.startsWith(base.replace(/\/$/, "") + "/")) {
      path = path.slice(base.replace(/\/$/, "").length);
    }

    if (!path || path === "/") path = "/index.html";
    if (path.endsWith("/")) path += "index.html";
    return path;
  }

  function getRelativePrefix() {
    const parts = getPathInsideSite().split("/").filter(Boolean);
    if (parts.length <= 1) return "";
    return "../".repeat(parts.length - 1);
  }

  function fixFooterImagePaths() {
    const footer = document.querySelector(".tsiino-site-footer");
    if (footer && footer.parentElement !== document.body) {
      document.body.appendChild(footer);
    }

    const prefix = getRelativePrefix();

    document.querySelectorAll(".tsiino-site-footer img[data-src], .tsiino-site-footer img[data-tsiino-src]").forEach(function (img) {
      const source = img.getAttribute("data-tsiino-src") || img.getAttribute("data-src");
      if (!source) return;
      img.setAttribute("src", prefix + source.replace(/^\/+/, ""));
    });

    document.querySelectorAll(".tsiino-footer-home").forEach(function (link) {
      link.setAttribute("href", prefix + "index.html");
    });
  }

  function ensureLanguageButton() {
    let button = document.getElementById("language-toggle");
    if (button) return button;

    button = document.createElement("button");
    button.id = "language-toggle";
    button.className = "language-toggle";
    button.type = "button";
    button.innerHTML = "<span class=\"language-toggle-label\"></span>";

    const item = document.createElement("li");
    item.className = "nav-item language-toggle-item";
    item.appendChild(button);

    const tools = document.querySelector(".quarto-navbar-tools");
    if (tools) {
      tools.appendChild(button);
      return button;
    }

    let rightNavbar = document.querySelector(".navbar .navbar-nav.ms-auto");
    if (!rightNavbar) {
      const navbarCollapse = document.querySelector(".navbar .navbar-collapse");
      rightNavbar = document.createElement("ul");
      rightNavbar.className = "navbar-nav ms-auto";
      if (navbarCollapse) navbarCollapse.appendChild(rightNavbar);
    }
    if (rightNavbar) rightNavbar.appendChild(item);
    return button;
  }

  function updateButton(language) {
    const button = ensureLanguageButton();
    const next = nextLanguage(language);
    const langCfg = cfg().languages && cfg().languages[language];
    const label = (langCfg && langCfg.buttonLabel) || next.toUpperCase();
    const title = language === "en" ? "Switch language to Portuguese" : "Mudar idioma para inglês";

    const span = button.querySelector(".language-toggle-label") || button;
    span.textContent = label;
    button.setAttribute("aria-label", title);
    button.setAttribute("title", title);
  }

  function applyTranslations(options) {
    const opts = options || {};
    const language = getCurrentLanguage();

    if (isApplying) return;
    isApplying = true;

    try {
      fixFooterImagePaths();

      if (isDefaultLanguage(language)) {
        restoreOriginals();
        translateQuartoUI(language, null);
        updateButton(language);
        return;
      }

      const maps = buildMaps(language);
      translateDataI18n(language);
      translateBlocks(document, maps);
      translateTextNodes(document.body, maps);
      translateAttributes(document, maps);
      translateQuartoUI(language, maps);

      if (opts.includeCharts) {
        window.setTimeout(function () {
          const current = getCurrentLanguage();
          if (!isDefaultLanguage(current)) {
            translateSvgAndCharts(document, buildMaps(current));
          }
        }, 250);
      }

      updateButton(language);
    } finally {
      isApplying = false;
      window.dispatchEvent(new Event("resize"));
      window.dispatchEvent(new Event("scroll"));
    }
  }

  function scheduleApply(root) {
    if (mutationTimer) window.clearTimeout(mutationTimer);
    mutationTimer = window.setTimeout(function () {
      if (!isDefaultLanguage(getCurrentLanguage())) {
        applyTranslations({ reason: "mutation", includeCharts: true, root: root });
      } else {
        fixFooterImagePaths();
      }
    }, 150);
  }

  function startObserver() {
    if (!document.body || observer) return;
    observer = new MutationObserver(function (mutations) {
      if (isApplying) return;
      const hasAddedNodes = mutations.some(function (mutation) {
        return mutation.type === "childList" && mutation.addedNodes && mutation.addedNodes.length;
      });
      if (hasAddedNodes) scheduleApply(document.body);
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  function bindButton() {
    const button = ensureLanguageButton();
    if (button.dataset.tsiinoBound) return;

    button.addEventListener("click", function () {
      const current = getCurrentLanguage();
      setCurrentLanguage(nextLanguage(current));
      applyTranslations({ reason: "toggle", force: true, includeCharts: true });
      window.setTimeout(function () {
        applyTranslations({ reason: "toggle-late", force: true, includeCharts: true });
      }, 800);
    });

    button.dataset.tsiinoBound = "true";
  }

  function init() {
    bindButton();
    applyTranslations({ reason: "init", includeCharts: true });
    startObserver();
    window.setTimeout(fixFooterImagePaths, 500);
    window.setTimeout(fixFooterImagePaths, 1500);
  }

  window.TSIINO_TRANSLATE_NOW = function () {
    applyTranslations({ reason: "manual", force: true, includeCharts: true });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
