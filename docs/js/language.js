(function () {
  "use strict";

  const STORAGE_KEY = "tsiino-language";
  const DEFAULT_LANGUAGE = "pt";
  const SYSTEM_LANGUAGES = ["pt"];

  const BLOCK_SELECTOR = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "figcaption", "blockquote", "li",
    "button", "a", "span", "strong", "em",
    ".hero-kicker", ".hero-subtitle", ".hero-description",
    ".about-eyebrow", ".method-eyebrow", ".feature-eyebrow",
    ".about-display-title", ".about-pullquote",
    ".objective-kicker", ".expedition-date", ".media-date",
    ".media-panel-label", ".researchers-kicker", ".researchers-label",
    ".project-map-header h3", ".project-map-header p",
    ".about-stat span", ".feature-title", ".feature-panel h3", ".feature-panel p",
    ".method-step h3", ".method-step p", ".impact-card h3", ".impact-card p",
    ".empty-media", ".btn-main", ".btn-ghost", ".media-link",
    ".metric-label", ".metric-sub", ".panel-title", ".chart-title", ".dashboard-title"
  ].join(",");

  const ATTRIBUTE_MAP = [
    ["alt", "alt"],
    ["title", "title"],
    ["placeholder", "placeholder"],
    ["aria-label", "aria-label"],
    ["data-label", "data-label"],
    ["data-tip", "data-tip"]
  ];

  const EXCLUDE_SELECTOR = [
    "script", "style", "noscript", "template", "canvas", "iframe",
    "pre", "code", "kbd", "samp",
    ".leaflet-container", ".leaflet-control", ".leaflet-pane",
    ".quarto-code-tools-source", ".sourceCode"
  ].join(",");

  let isApplying = false;
  let observer = null;
  let observerTimer = null;
  const mapsCache = new Map();

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

  function getSupportedLanguages() {
    const c = cfg();
    return Array.isArray(c.supportedLanguages) && c.supportedLanguages.length
      ? c.supportedLanguages
      : ["pt", "en"];
  }

  function getCurrentLanguage() {
    const saved = localStorage.getItem(STORAGE_KEY);
    const supported = getSupportedLanguages();
    if (saved && supported.includes(saved)) return saved;
    return cfg().defaultLanguage || DEFAULT_LANGUAGE;
  }

  function setCurrentLanguage(language) {
    localStorage.setItem(STORAGE_KEY, language);
  }

  function nextLanguage(language) {
    const supported = getSupportedLanguages();
    if (supported.length <= 1) return language;
    const index = Math.max(0, supported.indexOf(language));
    return supported[(index + 1) % supported.length];
  }

  function isSystemLanguage(language) {
    return language === DEFAULT_LANGUAGE || SYSTEM_LANGUAGES.includes(language);
  }

  function isExcluded(nodeOrElement) {
    const element = nodeOrElement.nodeType === Node.ELEMENT_NODE
      ? nodeOrElement
      : nodeOrElement.parentElement;
    if (!element) return true;
    return Boolean(element.closest(EXCLUDE_SELECTOR));
  }

  function getAllDictionarySections() {
    const dict = cfg().dictionary || {};
    const sections = [];
    Object.keys(dict).forEach(function (sectionName) {
      const section = dict[sectionName];
      if (section && typeof section === "object") sections.push(section);
    });
    return sections;
  }

  function buildMaps(targetLanguage) {
    if (mapsCache.has(targetLanguage)) return mapsCache.get(targetLanguage);

    const exact = new Map();
    const reverse = new Map();
    const phrases = [];
    const reversePhrases = [];

    getAllDictionarySections().forEach(function (section) {
      Object.keys(section).forEach(function (ptText) {
        const entry = section[ptText];
        if (!entry || typeof entry !== "object") return;
        const translated = entry[targetLanguage];
        if (!translated || typeof translated !== "string") return;

        const ptKey = normalize(ptText);
        const targetValue = normalize(translated);
        if (!ptKey || !targetValue) return;

        exact.set(ptKey, translated);
        reverse.set(targetValue, ptText);

        if (ptKey.length >= 12) {
          phrases.push({ from: ptText, fromNorm: ptKey, to: translated });
          reversePhrases.push({ from: translated, fromNorm: targetValue, to: ptText });
        }
      });
    });

    phrases.sort((a, b) => b.fromNorm.length - a.fromNorm.length);
    reversePhrases.sort((a, b) => b.fromNorm.length - a.fromNorm.length);

    const maps = { exact, reverse, phrases, reversePhrases };
    mapsCache.set(targetLanguage, maps);
    return maps;
  }

  function replaceNormalizedWholeText(originalText, maps, targetLanguage) {
    const normalized = normalize(originalText);
    if (!normalized) return null;
    if (isSystemLanguage(targetLanguage)) {
      return maps.reverse.get(normalized) || null;
    }
    return maps.exact.get(normalized) || null;
  }

  function replacePhrasesInText(originalText, maps, targetLanguage) {
    if (!originalText || !normalize(originalText)) return originalText;

    let output = String(originalText);
    const phraseList = isSystemLanguage(targetLanguage) ? maps.reversePhrases : maps.phrases;

    phraseList.forEach(function (item) {
      if (output.includes(item.from)) {
        output = output.split(item.from).join(item.to);
        return;
      }

      const escaped = item.from
        .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
        .replace(/\s+/g, "\\s+");
      try {
        output = output.replace(new RegExp(escaped, "g"), item.to);
      } catch (error) {
        // Keep the original if a browser rejects the regex.
      }
    });

    return output;
  }

  function getStructuredTranslation(path, targetLanguage) {
    const langObject = cfg()[targetLanguage];
    if (!langObject) return undefined;
    return String(path || "").split(".").reduce(function (obj, part) {
      return obj && obj[part];
    }, langObject);
  }

  function setTextIfChanged(element, value) {
    const next = String(value).trim();
    if (element.textContent !== next) element.textContent = next;
  }

  function setHtmlIfChanged(element, value) {
    const next = String(value).trim();
    if (element.innerHTML !== next) element.innerHTML = next;
  }

  function setAttributeIfChanged(element, attr, value) {
    const next = String(value).trim();
    if (element.getAttribute(attr) !== next) element.setAttribute(attr, next);
  }

  function translateDataI18n(targetLanguage) {
    document.querySelectorAll("[data-i18n]").forEach(function (element) {
      if (isExcluded(element)) return;
      const value = getStructuredTranslation(element.getAttribute("data-i18n"), targetLanguage);
      if (value !== undefined) setTextIfChanged(element, value);
    });

    document.querySelectorAll("[data-i18n-html]").forEach(function (element) {
      if (isExcluded(element)) return;
      const value = getStructuredTranslation(element.getAttribute("data-i18n-html"), targetLanguage);
      if (value !== undefined) setHtmlIfChanged(element, value);
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
        const value = getStructuredTranslation(element.getAttribute(pair[0]), targetLanguage);
        if (value !== undefined) setAttributeIfChanged(element, pair[1], value);
      });
    });
  }

  function translateBlocks(targetLanguage, maps, root) {
    (root || document).querySelectorAll(BLOCK_SELECTOR).forEach(function (element) {
      if (isExcluded(element)) return;
      if (element.id === "language-toggle" || element.closest("#language-toggle")) return;
      if (element.closest(".navbar") && !element.matches(".navbar a, .navbar span, .navbar button")) return;
      if (element.querySelector("img, video, iframe, canvas, svg, input, select, textarea")) return;

      const whole = replaceNormalizedWholeText(element.textContent, maps, targetLanguage);
      if (whole !== null) setTextIfChanged(element, whole);
    });
  }

  function translateTextNodes(targetLanguage, maps, root) {
    const walker = document.createTreeWalker(
      root || document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          if (!node.nodeValue || !normalize(node.nodeValue)) return NodeFilter.FILTER_REJECT;
          if (isExcluded(node)) return NodeFilter.FILTER_REJECT;
          if (node.parentElement && node.parentElement.closest("#language-toggle")) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    nodes.forEach(function (node) {
      const exact = replaceNormalizedWholeText(node.nodeValue, maps, targetLanguage);
      if (exact !== null) {
        if (node.nodeValue !== exact) node.nodeValue = exact;
        return;
      }
      const replaced = replacePhrasesInText(node.nodeValue, maps, targetLanguage);
      if (replaced !== node.nodeValue) node.nodeValue = replaced;
    });
  }

  function translateSvgAndChartText(targetLanguage, maps, root) {
    const chartTextSelector = [
      "svg text",
      ".plotly text",
      ".svg-container text",
      ".legend text",
      ".gtitle",
      ".xtitle",
      ".ytitle",
      ".annotation-text",
      ".hovertext text",
      "svg title",
      "svg desc"
    ].join(",");

    (root || document).querySelectorAll(chartTextSelector).forEach(function (element) {
      if (!element || element.closest("#language-toggle")) return;
      const current = element.textContent;
      if (!current || !normalize(current)) return;

      const exact = replaceNormalizedWholeText(current, maps, targetLanguage);
      if (exact !== null) {
        setTextIfChanged(element, exact);
        return;
      }

      const replaced = replacePhrasesInText(current, maps, targetLanguage);
      if (replaced !== current) element.textContent = replaced;
    });
  }

  function translateAttributes(targetLanguage, maps, root) {
    ATTRIBUTE_MAP.forEach(function (pair) {
      const attr = pair[0];
      (root || document).querySelectorAll("[" + attr + "]").forEach(function (element) {
        if (isExcluded(element)) return;
        if (element.id === "language-toggle") return;
        const current = element.getAttribute(attr);
        if (!current) return;

        const exact = replaceNormalizedWholeText(current, maps, targetLanguage);
        if (exact !== null) {
          setAttributeIfChanged(element, attr, exact);
          return;
        }

        const replaced = replacePhrasesInText(current, maps, targetLanguage);
        if (replaced !== current) element.setAttribute(attr, replaced);
      });
    });
  }

  function ensureLanguageButton() {
    let button = document.getElementById("language-toggle");
    if (button) return button;

    button = document.createElement("button");
    button.id = "language-toggle";
    button.className = "language-toggle";
    button.type = "button";
    button.innerHTML = '<span class="language-toggle-label"></span>';

    const tools = document.querySelector("#quarto-header .quarto-navbar-tools") ||
      document.querySelector(".quarto-navbar-tools");

    if (tools) {
      tools.insertBefore(button, tools.firstChild);
      return button;
    }

    let rightNavbar = document.querySelector("#quarto-header .navbar-nav.ms-auto") ||
      document.querySelector(".navbar .navbar-nav.ms-auto");

    if (!rightNavbar) {
      const collapse = document.querySelector("#quarto-header .navbar-collapse") ||
        document.querySelector(".navbar .navbar-collapse");
      rightNavbar = document.createElement("ul");
      rightNavbar.className = "navbar-nav ms-auto";
      if (collapse) collapse.appendChild(rightNavbar);
    }

    if (rightNavbar) {
      const item = document.createElement("li");
      item.className = "nav-item language-toggle-item";
      item.appendChild(button);
      rightNavbar.appendChild(item);
    }

    return button;
  }

  function updateButton(targetLanguage) {
    const langInfo = (cfg().languages || {})[targetLanguage] || {};
    const button = ensureLanguageButton();
    const label = button.querySelector(".language-toggle-label") || button;
    label.textContent = langInfo.buttonLabel || (targetLanguage === "pt" ? "EN" : "PT");
    button.setAttribute("aria-label", langInfo.buttonAria || "Switch language");
    button.setAttribute("title", langInfo.buttonAria || "Switch language");
  }

  function updateHtmlLang(targetLanguage) {
    const langInfo = (cfg().languages || {})[targetLanguage] || {};
    document.documentElement.lang = langInfo.htmlLang || targetLanguage;
  }

  function idle(callback, timeout) {
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(callback, { timeout: timeout || 800 });
    } else {
      window.setTimeout(callback, Math.min(timeout || 250, 250));
    }
  }

  function applyTranslations(options) {
    options = options || {};
    if (isApplying || !window.TRANSLATIONS || !document.body) return;

    const targetLanguage = getCurrentLanguage();
    const root = options.root || document;
    const maps = buildMaps(targetLanguage);

    // In initial Portuguese view, avoid scanning the whole page. This preserves
    // reveal/scroll animations and prevents unnecessary layout work.
    if (!options.force && isSystemLanguage(targetLanguage) && options.reason === "init") {
      updateButton(targetLanguage);
      updateHtmlLang(targetLanguage);
      return;
    }

    isApplying = true;
    if (observer) observer.disconnect();

    try {
      translateDataI18n(targetLanguage);
      translateBlocks(targetLanguage, maps, root);
      translateTextNodes(targetLanguage, maps, root === document ? document.body : root);
      translateAttributes(targetLanguage, maps, root);
      updateButton(targetLanguage);
      updateHtmlLang(targetLanguage);
    } finally {
      isApplying = false;
      if (observer) startObserver(true);
    }

    if (options.includeCharts !== false) {
      idle(function () {
        if (isApplying || !window.TRANSLATIONS) return;
        const current = getCurrentLanguage();
        const chartMaps = buildMaps(current);
        isApplying = true;
        if (observer) observer.disconnect();
        try {
          translateSvgAndChartText(current, chartMaps, root);
          updateButton(current);
        } finally {
          isApplying = false;
          if (observer) startObserver(true);
        }
      }, 900);
    }

    // Let existing scroll/IntersectionObserver animation code re-evaluate after
    // text height changes, without forcing repeated translations.
    window.requestAnimationFrame(function () {
      window.dispatchEvent(new Event("scroll"));
      window.dispatchEvent(new Event("resize"));
    });
  }

  function scheduleTranslate(reason, root) {
    window.clearTimeout(observerTimer);
    observerTimer = window.setTimeout(function () {
      applyTranslations({ reason: reason || "mutation", root: root || document, includeCharts: true });
    }, 450);
  }

  function startObserver(restart) {
    if (restart && observer) observer.disconnect();
    if (!document.body) return;

    if (!observer) {
      observer = new MutationObserver(function (mutations) {
        if (isApplying) return;

        // Ignore class/style changes from scroll reveal animations. The previous
        // runtime watched attributes/characterData and kept re-translating during
        // animations, which delayed the reveal effects in English.
        let root = null;
        for (const mutation of mutations) {
          if (mutation.type === "childList" && mutation.addedNodes.length) {
            for (const node of mutation.addedNodes) {
              if (node.nodeType === Node.ELEMENT_NODE && !isExcluded(node)) {
                root = node;
                break;
              }
            }
          }
          if (root) break;
        }

        if (!root) return;
        scheduleTranslate("mutation", root);
      });
    }

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
  }

  function bindButton() {
    const button = ensureLanguageButton();
    if (button.dataset.i18nBound) return;

    button.addEventListener("click", function () {
      const current = getCurrentLanguage();
      setCurrentLanguage(nextLanguage(current));
      applyTranslations({ reason: "toggle", force: true, includeCharts: true });

      // Plotly/htmlwidgets can redraw after the button click; translate chart
      // labels once more later, but do not keep hammering the page.
      window.setTimeout(function () {
        const currentLanguage = getCurrentLanguage();
        const maps = buildMaps(currentLanguage);
        translateSvgAndChartText(currentLanguage, maps, document);
      }, 1200);
    });

    button.dataset.i18nBound = "true";
  }

  function init() {
    bindButton();
    applyTranslations({ reason: "init", includeCharts: getCurrentLanguage() !== DEFAULT_LANGUAGE });
    startObserver(false);

    // One delayed pass for widgets loaded after Quarto, only when already in a
    // non-default language.
    if (getCurrentLanguage() !== DEFAULT_LANGUAGE) {
      idle(function () {
        applyTranslations({ reason: "idle", force: true, includeCharts: true });
      }, 1200);
    }
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
