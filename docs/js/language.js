/* Tsiino Hiiwiida language switcher — no-fragment v1
 * Runtime de tradução PT/EN para site Quarto estático.
 * Traduz apenas textos completos encontrados no dicionário.
 * Não faz substituição por fragmentos soltos dentro de palavras/frases.
 */
(function () {
  "use strict";

  window.TSIINO_TRANSLATION_RUNTIME_VERSION = "nofragment-v1-2026-06-24";

  if (window.TSIINO_TRANSLATION_RUNTIME_ACTIVE) {
    return;
  }
  window.TSIINO_TRANSLATION_RUNTIME_ACTIVE = true;

  const config = window.TsiinoTranslations || {};
  const strings = config.strings || {};
  const prefixes = config.prefixes || {};
  const labels = config.labels || { pt: "Português", en: "English" };
  const available = config.availableLanguages || ["pt", "en"];
  const defaultLanguage = config.defaultLanguage || "pt";
  const storageKey = config.storageKey || "tsiino-language";

  const excludedSelectors = [
    "script", "style", "code", "pre", "kbd", "samp", "textarea", "noscript",
    "svg", "canvas", ".tsiino-language-control", ".MathJax", ".sourceCode",
    ".leaflet-container", ".leaflet-control", ".plotly", ".js-plotly-plot"
  ].join(",");

  const wholeElementSelector = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "label", "button", "figcaption", "dt", "dd", "summary",
    "a.nav-link", "a.dropdown-item", ".navbar-title", ".navbar-brand",
    ".hero-kicker", ".hero-subtitle", ".hero-description", ".hero-video-toggle",
    ".section-title h2", ".about-eyebrow", ".about-display-title span",
    ".about-copy p", ".about-copy-columns p", ".about-pullquote",
    ".about-stat span", ".project-map-caption", ".photo-chip",
    ".feature-title", ".feature-eyebrow", ".feature-panel h3", ".axis-title", ".axis-detail",
    ".method-eyebrow", ".method-step h3", ".method-step p",
    ".method-card h3", ".method-card p", ".method-number",
    ".core-objectives-title span", ".core-objective-number", ".core-objective-kicker",
    ".core-objective-card h3", ".core-objective-card p",
    ".safeguards-editorial-eyebrow", ".safeguards-editorial-copy h3",
    ".safeguards-editorial-lead", ".safeguards-editorial-copy p",
    ".safeguards-editorial-textgrid p", ".safeguards-editorial-tags span",
    ".safeguards-status-label", ".safeguards-status-card strong", ".safeguards-status-card p",
    ".safeguards-process-card h3", ".safeguards-process-card p",
    ".safeguards-step-card h3", ".safeguards-step-card p",
    ".safeguards-impact-card h3", ".safeguards-impact-card p",
    ".exp-collage-overlay h2", ".exp-collage-overlay p",
    ".media-panel h3", ".media-panel-label", ".media-date",
    ".media-body h4", ".media-body p", ".media-link",
    ".carousel-type-pill", ".carousel-date", ".carousel-title", ".carousel-description", ".carousel-link",
    ".empty-media", ".divulg-empty-media",
    ".researchers-kicker", ".researchers-lead", ".researchers-copy p",
    ".researchers-number", ".researchers-label", ".researcher-card h3", ".researcher-card p",
    ".team-name", ".team-affiliation", ".inst-name",
    ".tsiino-footer-title", ".tsiino-footer-name span", ".tsiino-footer-contact", ".tsiino-footer-links"
  ].join(",");

  const attrsToTranslate = ["placeholder", "title", "aria-label", "alt", "data-label"];

  const textOriginals = new WeakMap();
  const attrOriginals = new WeakMap();
  const elementOriginals = new WeakMap();

  let originalTitle = document.title;
  let currentLanguage = defaultLanguage;
  let observerStarted = false;
  let refreshTimer = null;
  let translating = false;

  function normalize(value) {
    return String(value || "")
      .replace(/\u00a0/g, " ")
      .replace(/[“”]/g, '"')
      .replace(/[‘’]/g, "'")
      .replace(/[—]/g, "–")
      .replace(/\s+/g, " ")
      .trim();
  }

  function preserveSpacing(original, translated) {
    const raw = String(original || "");
    const leading = (raw.match(/^\s*/) || [""])[0];
    const trailing = (raw.match(/\s*$/) || [""])[0];
    return leading + translated + trailing;
  }

  function getDictionary(language) {
    return (strings && strings[language]) || {};
  }

  function getPrefixes(language) {
    return (prefixes && prefixes[language]) || {};
  }

  function dictionaryLookup(value, dictionary) {
    const key = normalize(value);
    if (!key) return null;

    if (Object.prototype.hasOwnProperty.call(dictionary, key)) {
      return dictionary[key];
    }

    const noFinalPeriod = key.replace(/\.$/, "");
    if (noFinalPeriod !== key && Object.prototype.hasOwnProperty.call(dictionary, noFinalPeriod)) {
      const translated = dictionary[noFinalPeriod];
      return /\.$/.test(translated) ? translated : translated + ".";
    }

    const withFinalPeriod = key + ".";
    if (Object.prototype.hasOwnProperty.call(dictionary, withFinalPeriod)) {
      return dictionary[withFinalPeriod];
    }

    const altApostrophe = key.replace(/’/g, "'");
    if (altApostrophe !== key && Object.prototype.hasOwnProperty.call(dictionary, altApostrophe)) {
      return dictionary[altApostrophe];
    }

    const altApostrophe2 = key.replace(/'/g, "’");
    if (altApostrophe2 !== key && Object.prototype.hasOwnProperty.call(dictionary, altApostrophe2)) {
      return dictionary[altApostrophe2];
    }

    return null;
  }

  function prefixLookup(value, language) {
    if (language === defaultLanguage) return null;

    const key = normalize(value);
    if (!key) return null;

    const languagePrefixes = getPrefixes(language);
    const sourcePrefixes = Object.keys(languagePrefixes).sort(function (a, b) {
      return b.length - a.length;
    });

    for (const sourcePrefix of sourcePrefixes) {
      const normalizedPrefix = normalize(sourcePrefix);
      if (key.startsWith(normalizedPrefix)) {
        const suffix = key.slice(normalizedPrefix.length);
        return languagePrefixes[sourcePrefix] + suffix;
      }
    }

    return null;
  }

  function translateValue(value, language) {
    const raw = String(value || "");
    const key = normalize(raw);

    if (!key || language === defaultLanguage) {
      return raw;
    }

    const dictionary = getDictionary(language);
    const translated = dictionaryLookup(key, dictionary);

    if (translated !== null) {
      return preserveSpacing(raw, translated);
    }

    const prefixed = prefixLookup(key, language);
    if (prefixed !== null) {
      return preserveSpacing(raw, prefixed);
    }

    return raw;
  }

  function getInitialLanguage() {
    const params = new URLSearchParams(window.location.search);
    const queryLanguage = params.get("lang");

    if (available.includes(queryLanguage)) {
      return queryLanguage;
    }

    // O site sempre abre em português. Não usa idioma do navegador nem localStorage.
    try {
      localStorage.removeItem(storageKey);
      localStorage.removeItem("tsiino-language");
      localStorage.removeItem("tsiino_i18n_lang");
      localStorage.removeItem("site-language");
      localStorage.removeItem("language");
      localStorage.removeItem("rede-c2-language");
    } catch (error) {}

    return defaultLanguage;
  }

  function isExcludedElement(element) {
    return !!(element && element.closest && element.closest(excludedSelectors));
  }

  function isSafeWholeElement(element) {
    if (!element || isExcludedElement(element)) return false;

    // Não traduz containers da navbar; traduz só links individuais.
    if (
      element.matches("nav, ul, ol, .navbar, .navbar-nav, .navbar-collapse, .navbar-container, .container-fluid") ||
      element.classList.contains("quarto-navbar-tools")
    ) {
      return false;
    }

    const text = normalize(element.textContent);
    if (!text) return false;

    // Evita trocar seções enormes.
    if (text.length > 1600) return false;

    const blockChildren = element.querySelectorAll("section, article, div, table, ul, ol, p, h1, h2, h3, h4, h5, h6");
    if (blockChildren.length > 10) return false;

    if (
      element.matches(".lead, .hero-subtitle, .hero-description, .axis-title, .axis-detail") ||
      element.matches(".section-title h2, .about-display-title span, .core-objectives-title span") ||
      element.matches(".core-objective-card h3, .core-objective-card p, .core-objective-kicker") ||
      element.matches(".safeguards-editorial-copy p, .safeguards-editorial-textgrid p") ||
      element.matches(".researchers-copy p, .media-body p, .carousel-description")
    ) {
      return true;
    }

    // Evita trocar elementos que possuem filhos estruturais/interativos,
    // exceto classes pontuais em que só há elementos decorativos ou texto curto.
    if (
      element.children &&
      element.children.length > 0 &&
      !element.matches("a.nav-link, a.dropdown-item") &&
      !element.classList.contains("feature-title")
    ) {
      return false;
    }

    return true;
  }

  function rememberElement(element) {
    if (!elementOriginals.has(element)) {
      elementOriginals.set(element, {
        html: element.innerHTML,
        text: element.textContent
      });
    }
  }

  function restoreElement(element) {
    const original = elementOriginals.get(element);
    if (!original) return;
    if (element.dataset) delete element.dataset.tsiinoTranslatedWhole;
    element.innerHTML = original.html;
  }

  function translateWholeElements(language) {
    const dictionary = getDictionary(language);

    document.querySelectorAll(wholeElementSelector).forEach(function (element) {
      if (!isSafeWholeElement(element)) return;

      rememberElement(element);
      restoreElement(element);

      if (language === defaultLanguage) return;

      const original = elementOriginals.get(element);
      const translated = dictionaryLookup(original.text, dictionary);

      if (translated !== null) {
        element.textContent = translated;
        element.dataset.tsiinoTranslatedWhole = "1";
      }
    });
  }

  function shouldTranslateTextNode(node) {
    if (!node || !node.parentElement) return false;
    if (isExcludedElement(node.parentElement)) return false;
    if (node.parentElement.closest("[data-tsiino-translated-whole='1']")) return false;
    return !!normalize(node.nodeValue);
  }

  function translateTextNodes(language) {
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          return shouldTranslateTextNode(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
        }
      }
    );

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    nodes.forEach(function (node) {
      if (!textOriginals.has(node)) {
        textOriginals.set(node, node.nodeValue);
      }

      const original = textOriginals.get(node);
      node.nodeValue = translateValue(original, language);
    });
  }

  function translateAttributes(language) {
    document.querySelectorAll("[placeholder], [title], [aria-label], img[alt], [data-label]").forEach(function (element) {
      if (isExcludedElement(element)) return;

      if (!attrOriginals.has(element)) {
        attrOriginals.set(element, {});
      }

      const stored = attrOriginals.get(element);

      attrsToTranslate.forEach(function (attr) {
        if (!element.hasAttribute(attr)) return;

        if (!Object.prototype.hasOwnProperty.call(stored, attr)) {
          stored[attr] = element.getAttribute(attr);
        }

        element.setAttribute(attr, translateValue(stored[attr], language));
      });
    });
  }

  function translateDocumentTitle(language) {
    document.title = translateValue(originalTitle, language);
  }

  function walkAndTranslate(language) {
    if (!document.body || translating) return;

    translating = true;

    translateWholeElements(language);
    translateTextNodes(language);
    translateAttributes(language);
    translateDocumentTitle(language);

    document.documentElement.lang = language === "pt" ? "pt-BR" : "en";
    document.body.dataset.language = language;

    translating = false;
  }

  function findNavContainer() {
    return (
      document.querySelector(".quarto-navbar-tools") ||
      document.querySelector("#quarto-header .quarto-navbar-tools") ||
      document.querySelector("#quarto-header .navbar .container-fluid") ||
      document.querySelector(".navbar .container-fluid") ||
      document.querySelector("#quarto-header .navbar") ||
      document.querySelector("nav.navbar") ||
      document.body
    );
  }

  function injectStyles() {
    if (document.getElementById("tsiino-language-style")) return;

    const style = document.createElement("style");
    style.id = "tsiino-language-style";
    style.textContent = `
      .tsiino-language-control {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        margin-left: .5rem;
        margin-right: .35rem;
        z-index: 10001;
      }

      .tsiino-language-select {
        border: 1px solid rgba(169, 54, 50, .36);
        border-radius: 999px;
        background: rgba(255, 253, 247, .96);
        color: #2E3B24;
        font: 800 .74rem/1.2 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        letter-spacing: .01em;
        padding: .28rem .62rem;
        cursor: pointer;
        box-shadow: 0 2px 10px rgba(0,0,0,.08);
      }

      .tsiino-language-select:focus {
        outline: 2px solid rgba(217, 154, 39, .36);
        outline-offset: 2px;
      }

      #quarto-header .tsiino-language-select {
        background: rgba(255, 253, 247, .92);
        color: #2E3B24;
        text-shadow: none;
      }

      @media (max-width: 768px) {
        .tsiino-language-control { margin: .45rem 0; }
      }
    `;

    document.head.appendChild(style);
  }

  function updateControlLanguageLabel(language) {
    const label = document.querySelector("label[for='tsiino-language-select']");
    const select = document.querySelector("#tsiino-language-select");

    if (label) {
      label.textContent = language === "pt" ? "Idioma" : "Language";
    }

    if (select) {
      select.setAttribute("aria-label", language === "pt" ? "Idioma" : "Language");
    }
  }

  function createControl(language) {
    let control = document.querySelector(".tsiino-language-control");
    let select = document.querySelector("#tsiino-language-select");

    if (!control) {
      control = document.createElement("div");
      control.className = "tsiino-language-control quarto-navigation-tool px-1";
    }

    if (!select) {
      const label = document.createElement("label");
      label.className = "visually-hidden";
      label.setAttribute("for", "tsiino-language-select");
      label.textContent = "Idioma";

      select = document.createElement("select");
      select.id = "tsiino-language-select";
      select.className = "tsiino-language-select";
      select.setAttribute("aria-label", "Idioma");

      available.forEach(function (lang) {
        const option = document.createElement("option");
        option.value = lang;
        option.textContent = labels[lang] || lang.toUpperCase();
        select.appendChild(option);
      });

      select.addEventListener("change", function () {
        currentLanguage = this.value;
        walkAndTranslate(currentLanguage);
      });

      control.appendChild(label);
      control.appendChild(select);
    }

    select.value = language;
    updateControlLanguageLabel(language);

    const target = findNavContainer();
    if (target && !target.contains(control)) {
      target.prepend(control);
    }
  }

  function scheduleRefresh() {
    if (refreshTimer) window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(function () {
      walkAndTranslate(currentLanguage);
    }, 150);
  }

  function startObserver() {
    if (observerStarted || !document.body || !window.MutationObserver) return;

    observerStarted = true;

    const observer = new MutationObserver(function (mutations) {
      if (translating) return;

      const relevant = mutations.some(function (mutation) {
        if (mutation.type === "childList" && mutation.addedNodes.length) return true;
        if (mutation.type === "attributes") return true;
        return false;
      });

      if (relevant && currentLanguage !== defaultLanguage) {
        scheduleRefresh();
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: attrsToTranslate
    });
  }

  function init() {
    currentLanguage = getInitialLanguage();
    injectStyles();
    createControl(currentLanguage);
    walkAndTranslate(currentLanguage);
    startObserver();

    window.setTimeout(function () { walkAndTranslate(currentLanguage); }, 500);
    window.setTimeout(function () { walkAndTranslate(currentLanguage); }, 1500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  window.addEventListener("load", function () {
    walkAndTranslate(currentLanguage);
  });

  window.TsiinoSetLanguage = function (language) {
    currentLanguage = available.includes(language) ? language : defaultLanguage;
    const select = document.querySelector("#tsiino-language-select");
    if (select) select.value = currentLanguage;
    updateControlLanguageLabel(currentLanguage);
    walkAndTranslate(currentLanguage);
  };

  window.TsiinoRefreshI18n = function () {
    walkAndTranslate(currentLanguage);
  };
})();
