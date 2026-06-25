/* Tsiino Hiiwiida language switcher — full-site runtime v2
 * Source language: Portuguese (pt-BR). Target: English.
 * Designed for Quarto static pages, R-generated HTML widgets, Leaflet popups,
 * Plotly/SVG labels, and dynamically inserted content.
 */
(function () {
  "use strict";

  window.TSIINO_TRANSLATION_RUNTIME_VERSION = "full-site-v2-2026-06-25";
  if (window.TSIINO_TRANSLATION_RUNTIME_ACTIVE) return;
  window.TSIINO_TRANSLATION_RUNTIME_ACTIVE = true;

  const config = window.TsiinoTranslations || {};
  const strings = config.strings || {};
  const phrases = config.phrases || {};
  const prefixes = config.prefixes || {};
  const regexRules = config.regex || {};
  const labels = config.labels || { pt: "Português", en: "English" };
  const available = config.availableLanguages || ["pt", "en"];
  const defaultLanguage = config.defaultLanguage || "pt";
  const storageKey = config.storageKey || "tsiino-language";

  const excludedSelector = [
    "script", "style", "code", "pre", "kbd", "samp", "textarea", "noscript",
    "template", ".tsiino-language-control", ".MathJax", ".sourceCode"
  ].join(",");

  const attrsToTranslate = ["placeholder", "title", "aria-label", "alt", "data-label", "value"];
  const dataAttrMap = {
    "data-i18n-alt": "alt",
    "data-i18n-title": "title",
    "data-i18n-label": "aria-label",
    "data-i18n-placeholder": "placeholder"
  };

  const textOriginals = new WeakMap();
  const elementOriginals = new WeakMap();
  const attrOriginals = new WeakMap();

  let currentLanguage = defaultLanguage;
  let observer = null;
  let refreshTimer = null;
  let translating = false;
  const originalTitle = document.title;

  function normalize(value) {
    return String(value || "")
      .replace(/\u00a0/g, " ")
      .replace(/[“”]/g, '"')
      .replace(/[‘’]/g, "'")
      .replace(/\s+/g, " ")
      .trim();
  }

  function hasLetters(value) {
    return /[A-Za-zÀ-ÿ]/.test(String(value || ""));
  }

  function preserveSpacing(original, translated) {
    const raw = String(original || "");
    const leading = (raw.match(/^\s*/) || [""])[0];
    const trailing = (raw.match(/\s*$/) || [""])[0];
    return leading + translated + trailing;
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function dictionaryFor(language) {
    return strings[language] || {};
  }

  function lookupExact(value, language) {
    const dictionary = dictionaryFor(language);
    const key = normalize(value);
    if (!key) return null;

    if (Object.prototype.hasOwnProperty.call(dictionary, key)) return dictionary[key];

    const noPeriod = key.replace(/\.$/, "");
    if (noPeriod !== key && Object.prototype.hasOwnProperty.call(dictionary, noPeriod)) {
      const translated = dictionary[noPeriod];
      return /[.!?…]$/.test(translated) ? translated : translated + ".";
    }

    const withPeriod = key + ".";
    if (Object.prototype.hasOwnProperty.call(dictionary, withPeriod)) return dictionary[withPeriod];

    const colonTrimmed = key.replace(/:\s*$/, "");
    if (colonTrimmed !== key && Object.prototype.hasOwnProperty.call(dictionary, colonTrimmed)) {
      return dictionary[colonTrimmed] + ":";
    }

    return null;
  }

  function applyPrefix(value, language) {
    if (language === defaultLanguage) return null;
    const languagePrefixes = prefixes[language] || {};
    const key = normalize(value);
    const ordered = Object.keys(languagePrefixes).sort((a, b) => b.length - a.length);
    for (const sourcePrefix of ordered) {
      const normalizedPrefix = normalize(sourcePrefix);
      if (key.startsWith(normalizedPrefix)) {
        return languagePrefixes[sourcePrefix] + key.slice(normalizedPrefix.length);
      }
    }
    return null;
  }

  function applyPhraseReplacements(value, language) {
    const languagePhrases = phrases[language] || {};
    let out = String(value || "");
    const ordered = Object.keys(languagePhrases).sort((a, b) => b.length - a.length);

    for (const source of ordered) {
      const target = languagePhrases[source];
      if (!source || target === undefined || target === null) continue;
      out = out.split(source).join(target);
    }

    return out;
  }

  function applyRegexRules(value, language) {
    const rules = regexRules[language] || [];
    let out = String(value || "");

    for (const rule of rules) {
      try {
        const pattern = rule.pattern || rule[0];
        const replacement = rule.replacement || rule[1] || "";
        const flags = rule.flags || rule[2] || "g";
        out = out.replace(new RegExp(pattern, flags), replacement);
      } catch (error) {
        // Ignore malformed optional rules.
      }
    }

    return out;
  }

  function translateValue(value, language) {
    const raw = String(value || "");
    if (language === defaultLanguage) return raw;
    if (!hasLetters(raw)) return raw;

    const exact = lookupExact(raw, language);
    if (exact !== null) return preserveSpacing(raw, exact);

    const prefixed = applyPrefix(raw, language);
    if (prefixed !== null) return preserveSpacing(raw, prefixed);

    let out = applyPhraseReplacements(raw, language);
    out = applyRegexRules(out, language);

    return out === raw ? raw : out;
  }

  function isExcluded(nodeOrElement) {
    if (!nodeOrElement) return true;
    const element = nodeOrElement.nodeType === Node.ELEMENT_NODE
      ? nodeOrElement
      : nodeOrElement.parentElement;
    return !!(element && element.closest && element.closest(excludedSelector));
  }

  function getOriginalText(node) {
    if (!textOriginals.has(node)) textOriginals.set(node, node.nodeValue || "");
    return textOriginals.get(node);
  }

  function getOriginalElementText(element) {
    if (!elementOriginals.has(element)) elementOriginals.set(element, element.textContent || "");
    return elementOriginals.get(element);
  }

  function getOriginalAttr(element, attr) {
    let map = attrOriginals.get(element);
    if (!map) {
      map = {};
      attrOriginals.set(element, map);
    }
    if (!Object.prototype.hasOwnProperty.call(map, attr)) {
      map[attr] = element.getAttribute(attr) || "";
    }
    return map[attr];
  }

  function translateDataI18nElement(element, language) {
    if (!element || isExcluded(element)) return;
    const key = element.getAttribute("data-i18n");
    if (!key) return;

    const original = getOriginalElementText(element);
    if (language === defaultLanguage) {
      element.textContent = original;
      return;
    }

    const translated = lookupExact(key, language) || lookupExact(original, language);
    if (translated !== null) element.textContent = translated;
  }

  function translateDataI18nAttributes(element, language) {
    if (!element || isExcluded(element)) return;

    Object.keys(dataAttrMap).forEach(function (dataAttr) {
      const key = element.getAttribute(dataAttr);
      const attr = dataAttrMap[dataAttr];
      if (!key) return;
      const original = getOriginalAttr(element, attr) || element.getAttribute(attr) || "";
      if (language === defaultLanguage) {
        if (original) element.setAttribute(attr, original);
        return;
      }
      const translated = lookupExact(key, language) || lookupExact(original, language);
      if (translated !== null) element.setAttribute(attr, translated);
    });
  }

  function translateAttributes(element, language) {
    if (!element || isExcluded(element)) return;

    attrsToTranslate.forEach(function (attr) {
      if (!element.hasAttribute(attr)) return;
      if (attr === "value" && !/^(button|submit|reset)$/i.test(element.getAttribute("type") || "")) return;
      const original = getOriginalAttr(element, attr);
      const translated = translateValue(original, language);
      if (translated !== element.getAttribute(attr)) element.setAttribute(attr, translated);
    });
  }

  function translateTextNode(node, language) {
    if (!node || node.nodeType !== Node.TEXT_NODE || isExcluded(node)) return;
    const original = getOriginalText(node);
    if (!hasLetters(original)) {
      node.nodeValue = original;
      return;
    }

    const normalized = normalize(original);
    if (!normalized || normalized.length > 7000) {
      node.nodeValue = original;
      return;
    }

    const translated = translateValue(original, language);
    if (node.nodeValue !== translated) node.nodeValue = translated;
  }

  function walkTextNodes(root, language) {
    if (!root || isExcluded(root)) return;
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          if (!node.parentElement || isExcluded(node)) return NodeFilter.FILTER_REJECT;
          if (!hasLetters(node.nodeValue)) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => translateTextNode(node, language));
  }

  function translateElementTree(root, language) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) {
      translateTextNode(root, language);
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;

    const elementRoot = root.nodeType === Node.ELEMENT_NODE ? root : null;
    if (elementRoot) {
      translateDataI18nElement(elementRoot, language);
      translateDataI18nAttributes(elementRoot, language);
      translateAttributes(elementRoot, language);
    }

    const elements = root.querySelectorAll ? root.querySelectorAll("[data-i18n], [data-i18n-alt], [data-i18n-title], [data-i18n-label], [data-i18n-placeholder], [placeholder], [title], [aria-label], [alt], input[type='button'], input[type='submit'], input[type='reset']") : [];
    elements.forEach(function (element) {
      translateDataI18nElement(element, language);
      translateDataI18nAttributes(element, language);
      translateAttributes(element, language);
    });

    walkTextNodes(root, language);
  }

  function updateDocumentLanguage(language) {
    document.documentElement.setAttribute("lang", language === "en" ? "en" : "pt-BR");
    document.title = translateValue(originalTitle, language);
  }

  function applyLanguage(language) {
    if (!available.includes(language)) language = defaultLanguage;
    if (translating) return;
    translating = true;

    currentLanguage = language;
    try {
      localStorage.setItem(storageKey, language);
    } catch (error) {}

    document.documentElement.setAttribute("data-tsiino-language", language);
    updateDocumentLanguage(language);
    translateElementTree(document.body || document.documentElement, language);
    updateSwitcher(language);

    translating = false;
  }

  function scheduleApply() {
    if (translating) return;
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function () {
      applyLanguage(currentLanguage);
    }, 80);
  }

  function startObserver() {
    if (observer || !document.body) return;
    observer = new MutationObserver(function (mutations) {
      if (translating) return;
      const relevant = mutations.some(function (m) {
        return m.type === "childList" || m.type === "characterData" || m.type === "attributes";
      });
      if (relevant) scheduleApply();
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["placeholder", "title", "aria-label", "alt", "data-label", "data-i18n", "data-i18n-alt", "data-i18n-title", "data-i18n-label", "data-i18n-placeholder"]
    });
  }

  function getInitialLanguage() {
    const params = new URLSearchParams(window.location.search);
    const queryLanguage = params.get("lang");
    if (available.includes(queryLanguage)) return queryLanguage;

    try {
      const stored = localStorage.getItem(storageKey);
      if (available.includes(stored)) return stored;
    } catch (error) {}

    return defaultLanguage;
  }

  function makeButton(language) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tsiino-language-button";
    button.dataset.language = language;
    button.textContent = labels[language] || language.toUpperCase();
    button.addEventListener("click", function () { applyLanguage(language); });
    return button;
  }

  function installSwitcherStyles() {
    if (document.getElementById("tsiino-language-style")) return;
    const style = document.createElement("style");
    style.id = "tsiino-language-style";
    style.textContent = `
      .tsiino-language-control{
        position: fixed;
        right: clamp(0.75rem, 1.6vw, 1.25rem);
        bottom: clamp(0.75rem, 1.6vw, 1.25rem);
        z-index: 2147483000;
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        padding: 0.25rem;
        border-radius: 999px;
        background: rgba(255,253,247,0.94);
        border: 1px solid rgba(98,106,56,0.28);
        box-shadow: 0 12px 26px rgba(0,0,0,0.16);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        font-family: Montserrat, Arial, sans-serif;
      }
      .tsiino-language-button{
        border: 0;
        border-radius: 999px;
        background: transparent;
        color: #2E3B24;
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.02em;
        line-height: 1;
        padding: 0.52rem 0.72rem;
        cursor: pointer;
      }
      .tsiino-language-button:hover{ background: rgba(215,221,197,0.65); }
      .tsiino-language-button.is-active{ background: #626A38; color: #FFFDF7; }
      @media (max-width: 640px){
        .tsiino-language-control{ right: 0.55rem; bottom: 0.55rem; }
        .tsiino-language-button{ font-size: 0.7rem; padding: 0.48rem 0.58rem; }
      }
    `;
    document.head.appendChild(style);
  }

  function createSwitcher() {
    if (document.querySelector(".tsiino-language-control")) return;
    installSwitcherStyles();
    const control = document.createElement("div");
    control.className = "tsiino-language-control";
    control.setAttribute("aria-label", "Idioma");
    available.forEach(function (language) { control.appendChild(makeButton(language)); });
    document.body.appendChild(control);
  }

  function updateSwitcher(language) {
    document.querySelectorAll(".tsiino-language-button").forEach(function (button) {
      const active = button.dataset.language === language;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function boot() {
    if (!document.body) return;
    createSwitcher();
    applyLanguage(getInitialLanguage());
    startObserver();
    window.addEventListener("load", function () {
      scheduleApply();
      setTimeout(scheduleApply, 250);
      setTimeout(scheduleApply, 1000);
      setTimeout(scheduleApply, 2500);
    });
    window.TsiinoSetLanguage = applyLanguage;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
