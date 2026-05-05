/* ==========================================================================
   Tsiino Hiiwiida — language.js v14
   Runtime global de tradução PT/EN.

   Diferença da v14:
   - Traduz também elementos inteiros por textContent exato.
   - Isso resolve parágrafos com <strong>, spans ou quebras internas, onde
     a tradução por nó de texto não encontra a frase completa.
   - PT restaura o HTML original renderizado pelo Quarto.
   ========================================================================== */

(function () {
  "use strict";

  const CONFIG = Object.assign({
    defaultLanguage: "pt",
    targetLanguage: "en",
    persistLanguage: false,
    storageKey: "tsiino_i18n_lang",
    projectBase: "cabeca_cachorro"
  }, window.TSIINO_I18N_CONFIG || {});

  const DEFAULT_LANG = CONFIG.defaultLanguage || "pt";
  const TARGET_LANG = CONFIG.targetLanguage || "en";
  const STORAGE_KEY = CONFIG.storageKey || "tsiino_i18n_lang";

  const LEGACY_STORAGE_KEYS = [
    "site-language",
    "tsiino-language",
    "language",
    "tsiino_lang"
  ];

  const BLOCKED_TAGS = new Set([
    "SCRIPT", "STYLE", "CODE", "PRE", "KBD", "SAMP", "TEXTAREA", "NOSCRIPT", "SVG", "CANVAS"
  ]);

  const ATTRS_TO_TRANSLATE = [
    "alt",
    "title",
    "aria-label",
    "placeholder",
    "data-label"
  ];

  const ELEMENT_SELECTOR = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "figcaption",
    ".hero-kicker",
    ".hero-subtitle",
    ".hero-description",
    ".about-eyebrow",
    ".method-eyebrow",
    ".feature-eyebrow",
    ".objective-kicker",
    ".about-pullquote",
    ".project-map-header p",
    ".project-map-header h3",
    ".about-stat span",
    ".feature-panel h3",
    ".feature-panel p",
    ".method-step h3",
    ".method-step p",
    ".impact-card h3",
    ".impact-card p",
    ".media-date",
    ".media-link",
    ".media-panel-label",
    ".researchers-label",
    ".empty-media",
    ".tag",
    ".agency-pill"
  ].join(",");

  let currentLang = DEFAULT_LANG;

  let textNodes = [];
  let attrNodes = [];
  let elementNodes = [];
  let chartTextNodes = [];

  const capturedTextNodes = new WeakSet();
  const capturedAttrKeys = new Set();
  const capturedElements = new WeakSet();
  const capturedChartTextElements = new WeakSet();

  function normalizeText(value) {
    return String(value || "")
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function preserveSpacing(original, translated) {
    const originalString = String(original || "");
    const start = (originalString.match(/^\s*/) || [""])[0];
    const end = (originalString.match(/\s*$/) || [""])[0];
    return start + translated + end;
  }

  function isPlainObject(value) {
    return value && typeof value === "object" && !Array.isArray(value);
  }

  function walkParallel(ptNode, langNode, exact) {
    if (typeof ptNode === "string" && typeof langNode === "string") {
      const pt = normalizeText(ptNode);
      const translated = normalizeText(langNode);

      if (pt && translated && pt !== translated) {
        exact[pt] = translated;
      }

      return;
    }

    if (!isPlainObject(ptNode) || !isPlainObject(langNode)) {
      return;
    }

    Object.keys(ptNode).forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(langNode, key)) {
        walkParallel(ptNode[key], langNode[key], exact);
      }
    });
  }

  function getDictionary(lang) {
    const exact = {};

    if (
      window.TRANSLATIONS &&
      window.TRANSLATIONS.pt &&
      window.TRANSLATIONS[lang]
    ) {
      walkParallel(window.TRANSLATIONS.pt, window.TRANSLATIONS[lang], exact);
    }

    if (
      window.TSIINO_I18N_DICTIONARY &&
      window.TSIINO_I18N_DICTIONARY[lang] &&
      window.TSIINO_I18N_DICTIONARY[lang].exact
    ) {
      Object.assign(exact, window.TSIINO_I18N_DICTIONARY[lang].exact);
    }

    if (
      lang === TARGET_LANG &&
      window.TSIINO_I18N_FALLBACKS &&
      window.TSIINO_I18N_FALLBACKS.exact
    ) {
      Object.assign(exact, window.TSIINO_I18N_FALLBACKS.exact);
    }

    return exact;
  }

  function getPatterns(lang) {
    if (
      window.TSIINO_I18N_PATTERNS &&
      window.TSIINO_I18N_PATTERNS[lang] &&
      Array.isArray(window.TSIINO_I18N_PATTERNS[lang])
    ) {
      return window.TSIINO_I18N_PATTERNS[lang];
    }

    return [];
  }

  function applyPatternTranslation(key, patterns) {
    for (let i = 0; i < patterns.length; i += 1) {
      const rule = patterns[i];
      if (!rule || !rule.pattern || typeof rule.replacement !== "string") continue;

      let regex;

      try {
        regex = rule.pattern instanceof RegExp
          ? rule.pattern
          : new RegExp(rule.pattern, rule.flags || "");
      } catch (error) {
        continue;
      }

      if (regex.test(key)) {
        return key.replace(regex, rule.replacement);
      }
    }

    return null;
  }

  function isBlockedElement(el) {
    if (!el) return true;

    let node = el;

    while (node) {
      if (BLOCKED_TAGS.has(node.tagName)) return true;

      if (node.classList) {
        if (
          node.classList.contains("MathJax") ||
          node.classList.contains("aa-DetachedSearchButton") ||
          node.classList.contains("sourceCode") ||
          node.classList.contains("plotly") ||
          node.classList.contains("leaflet-container")
        ) {
          return true;
        }
      }

      node = node.parentElement;
    }

    return false;
  }

  function shouldSkipTextNode(node) {
    if (!node || !node.parentElement) return true;
    if (isBlockedElement(node.parentElement)) return true;
    if (!normalizeText(node.nodeValue)) return true;
    return false;
  }

  function hasTranslatedElementAncestor(node) {
    let el = node && node.parentElement;

    while (el) {
      if (el.dataset && el.dataset.tsiinoI18nElementTranslated === "1") {
        return true;
      }
      el = el.parentElement;
    }

    return false;
  }

  function shouldCaptureElement(el) {
    if (!el || capturedElements.has(el)) return false;
    if (isBlockedElement(el)) return false;

    // Nunca trocar textContent de elementos de navegação/interativos.
    // Isso evita destruir <a>, <button> e a estrutura da navbar do Quarto.
    if (
      el.closest("#quarto-header") ||
      el.closest(".navbar") ||
      el.closest(".tsiino-site-footer") ||
      el.closest(".quarto-navbar-tools") ||
      el.matches("a, button, li, ul, ol, nav")
    ) {
      return false;
    }

    const text = normalizeText(el.textContent);
    if (!text) return false;

    // Não capture containers muito grandes. Eles misturam seções inteiras.
    if (text.length > 900) return false;

    // Evita capturar elementos que só servem de wrapper para muitos blocos.
    const blockChildren = el.querySelectorAll("section, article, div, p, h1, h2, h3, h4, h5, h6, ul, ol, table");
    if (blockChildren.length > 8) return false;

    return true;
  }

  function captureChartTextOriginals() {
    if (!document.body) return;

    const selectors = [
      ".js-plotly-plot svg text",
      ".plotly svg text",
      ".plot-container svg text",
      ".html-widget svg text",
      "svg text"
    ].join(",");

    document.querySelectorAll(selectors).forEach(function (el) {
      if (!el || capturedChartTextElements.has(el)) return;

      // Evita capturar ícones pequenos ou botões SVG do Quarto/navbar.
      if (
        el.closest("#quarto-header") ||
        el.closest(".navbar") ||
        el.closest(".quarto-navbar-tools") ||
        el.closest(".tsiino-site-footer")
      ) {
        return;
      }

      const text = normalizeText(el.textContent);
      if (!text) return;

      capturedChartTextElements.add(el);
      chartTextNodes.push({
        el: el,
        original: el.textContent
      });
    });
  }

  function restoreChartTextOriginals() {
    captureChartTextOriginals();

    chartTextNodes.forEach(function (item) {
      if (item.el) {
        item.el.textContent = item.original;
      }
    });
  }

  function translateChartText(lang) {
    captureChartTextOriginals();

    if (lang === DEFAULT_LANG) {
      restoreChartTextOriginals();
      return;
    }

    const dict = getDictionary(lang);
    const patterns = getPatterns(lang);

    chartTextNodes.forEach(function (item) {
      if (!item.el) return;
      item.el.textContent = translateExact(item.original, dict, patterns);
    });
  }

  function captureOriginals() {
    if (!document.body) return;

    document.querySelectorAll(ELEMENT_SELECTOR).forEach(function (el) {
      if (!shouldCaptureElement(el)) return;

      capturedElements.add(el);
      elementNodes.push({
        el: el,
        originalHTML: el.innerHTML,
        originalText: el.textContent
      });
    });

    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          if (capturedTextNodes.has(node)) return NodeFilter.FILTER_REJECT;
          if (shouldSkipTextNode(node)) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    let node;
    while ((node = walker.nextNode())) {
      capturedTextNodes.add(node);
      textNodes.push({
        node: node,
        original: node.nodeValue
      });
    }

    captureChartTextOriginals();

    document.querySelectorAll("*").forEach(function (el) {
      if (isBlockedElement(el)) return;

      ATTRS_TO_TRANSLATE.forEach(function (attr) {
        if (!el.hasAttribute(attr)) return;

        const value = el.getAttribute(attr);
        if (!normalizeText(value)) return;

        if (!el.dataset.tsiinoI18nId) {
          el.dataset.tsiinoI18nId = String(Math.random()).slice(2);
        }

        const key = el.dataset.tsiinoI18nId + "::" + attr;
        if (capturedAttrKeys.has(key)) return;

        capturedAttrKeys.add(key);
        attrNodes.push({
          el: el,
          attr: attr,
          original: value
        });
      });
    });
  }

  function translateExact(original, dict, patterns) {
    const raw = String(original || "");
    const key = normalizeText(raw);

    if (!key) return raw;

    if (Object.prototype.hasOwnProperty.call(dict, key)) {
      return preserveSpacing(raw, dict[key]);
    }

    const patternTranslation = applyPatternTranslation(key, patterns || []);
    if (patternTranslation !== null) {
      return preserveSpacing(raw, patternTranslation);
    }

    return raw;
  }

  function restoreOriginals() {
    captureOriginals();

    elementNodes.forEach(function (item) {
      if (!item.el) return;
      item.el.innerHTML = item.originalHTML;
      delete item.el.dataset.tsiinoI18nElementTranslated;
    });

    textNodes.forEach(function (item) {
      if (item.node && item.node.parentElement && !hasTranslatedElementAncestor(item.node)) {
        item.node.nodeValue = item.original;
      }
    });

    attrNodes.forEach(function (item) {
      if (item.el) {
        item.el.setAttribute(item.attr, item.original);
      }
    });

    restoreChartTextOriginals();

    document.documentElement.lang = "pt-BR";
    setDocumentTitle(DEFAULT_LANG);
    setButtonState(DEFAULT_LANG);
  }

  function applyLanguage(lang) {
    captureOriginals();

    const dict = getDictionary(lang);
    const patterns = getPatterns(lang);

    // Primeiro traduz elementos inteiros. Isso resolve frases quebradas por <strong>, spans etc.
    elementNodes.forEach(function (item) {
      if (!item.el) return;

      const key = normalizeText(item.originalText);

      if (Object.prototype.hasOwnProperty.call(dict, key)) {
        item.el.textContent = dict[key];
        item.el.dataset.tsiinoI18nElementTranslated = "1";
      } else {
        const patternTranslation = applyPatternTranslation(key, patterns);
        if (patternTranslation !== null) {
          item.el.textContent = patternTranslation;
          item.el.dataset.tsiinoI18nElementTranslated = "1";
        } else {
          delete item.el.dataset.tsiinoI18nElementTranslated;
        }
      }
    });

    // Depois traduz nós de texto isolados que não foram cobertos por elementos inteiros.
    textNodes.forEach(function (item) {
      if (!item.node || !item.node.parentElement) return;
      if (hasTranslatedElementAncestor(item.node)) return;

      item.node.nodeValue = translateExact(item.original, dict, patterns);
    });

    attrNodes.forEach(function (item) {
      if (!item.el) return;
      item.el.setAttribute(item.attr, translateExact(item.original, dict, patterns));
    });

    translateChartText(lang);

    document.documentElement.lang = lang === "en" ? "en" : lang;
    setDocumentTitle(lang);
    setButtonState(lang);
  }

  function setDocumentTitle(lang) {
    if (
      window.TRANSLATIONS &&
      window.TRANSLATIONS[lang] &&
      window.TRANSLATIONS[lang].meta &&
      window.TRANSLATIONS[lang].meta.siteTitle
    ) {
      document.title = window.TRANSLATIONS[lang].meta.siteTitle;
    }
  }

  function setLanguage(lang) {
    const normalized = lang === TARGET_LANG ? TARGET_LANG : DEFAULT_LANG;
    currentLang = normalized;

    try {
      LEGACY_STORAGE_KEYS.forEach(function (key) {
        localStorage.removeItem(key);
      });

      if (CONFIG.persistLanguage) {
        localStorage.setItem(STORAGE_KEY, currentLang);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch (error) {}

    if (currentLang === DEFAULT_LANG) {
      restoreOriginals();
    } else {
      applyLanguage(currentLang);
    }
  }

  function getSavedLanguage() {
    if (!CONFIG.persistLanguage) {
      return DEFAULT_LANG;
    }

    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved === TARGET_LANG ? TARGET_LANG : DEFAULT_LANG;
    } catch (error) {
      return DEFAULT_LANG;
    }
  }

  function findNavContainer() {
    return (
      document.querySelector("#quarto-header .quarto-navbar-tools") ||
      document.querySelector("#quarto-header .navbar .container-fluid") ||
      document.querySelector("#quarto-header .navbar") ||
      document.body
    );
  }

  function ensureButton() {
    let button = document.querySelector("#tsiino-language-toggle");

    if (!button) {
      button = document.querySelector(".tsiino-language-toggle");
    }

    if (!button) {
      button = document.createElement("button");
      button.id = "tsiino-language-toggle";
      button.className = "tsiino-language-toggle";
      button.type = "button";

      const container = findNavContainer();
      container.appendChild(button);
    }

    if (!button.dataset.tsiinoI18nBound) {
      button.dataset.tsiinoI18nBound = "1";

      button.addEventListener("click", function (event) {
        event.preventDefault();
        const nextLang = currentLang === TARGET_LANG ? DEFAULT_LANG : TARGET_LANG;
        setLanguage(nextLang);
      });
    }

    return button;
  }

  function setButtonState(lang) {
    const button = ensureButton();

    if (lang === TARGET_LANG) {
      button.textContent = "PT";
      button.setAttribute("aria-label", "Mudar idioma para português");
    } else {
      button.textContent = "EN";
      button.setAttribute("aria-label", "Switch language to English");
    }
  }

  function getRelativePrefix() {
    const projectBase = CONFIG.projectBase || "cabeca_cachorro";
    let path = window.location.pathname || "/";

    if (path.startsWith("/" + projectBase + "/")) {
      path = path.slice(projectBase.length + 1);
    }

    if (path === "" || path === "/") {
      path = "/index.html";
    }

    if (path.endsWith("/")) {
      path += "index.html";
    }

    const parts = path.split("/").filter(Boolean);
    if (parts.length <= 1) return "";

    return "../".repeat(parts.length - 1);
  }

  function fixFooterPaths() {
    const footer = document.querySelector(".tsiino-site-footer");

    if (footer && footer.parentElement !== document.body) {
      document.body.appendChild(footer);
    }

    const prefix = getRelativePrefix();

    document.querySelectorAll(".tsiino-site-footer img[data-src]").forEach(function (img) {
      const src = img.getAttribute("data-src");
      if (!src) return;

      img.setAttribute("src", prefix + src.replace(/^\/+/, ""));

      if (!img.dataset.tsiinoFooterErrorBound) {
        img.dataset.tsiinoFooterErrorBound = "1";
        img.addEventListener("error", function () {
          img.classList.add("tsiino-footer-logo-missing");
        });
      }
    });

    document.querySelectorAll(".tsiino-footer-home").forEach(function (link) {
      link.setAttribute("href", prefix + "index.html");
    });
  }

  function refreshDynamicContent() {
    captureOriginals();

    if (currentLang !== DEFAULT_LANG) {
      applyLanguage(currentLang);
    }
  }

  function dictionariesReady() {
    return !!(
      window.TRANSLATIONS &&
      window.TSIINO_I18N_DICTIONARY &&
      window.TSIINO_I18N_DICTIONARY[TARGET_LANG] &&
      window.TSIINO_I18N_DICTIONARY[TARGET_LANG].exact
    );
  }

  function initWhenReady(attempt) {
    attempt = attempt || 0;

    ensureButton();
    fixFooterPaths();

    if (!dictionariesReady() && attempt < 40) {
      window.setTimeout(function () {
        initWhenReady(attempt + 1);
      }, 75);
      return;
    }

    captureOriginals();
    setLanguage(getSavedLanguage());

    window.setTimeout(refreshDynamicContent, 500);
    window.setTimeout(refreshDynamicContent, 1500);
    window.setTimeout(refreshDynamicContent, 3000);
  }

  function init() {
    initWhenReady(0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  window.addEventListener("load", function () {
    fixFooterPaths();
    refreshDynamicContent();
  });

  window.TSIINO_SET_LANGUAGE = setLanguage;
  window.TSIINO_REFRESH_I18N = refreshDynamicContent;
})();
