(function () {
  "use strict";

  if (window.__TSIINO_I18N_RUNTIME_LOADED__) {
    return;
  }
  window.__TSIINO_I18N_RUNTIME_LOADED__ = true;

  const DEFAULT_LANGUAGE = "pt";
  const STORAGE_KEY = "site-language";
  const originalTextNodes = new WeakMap();
  const observerTimers = new WeakMap();
  let isUpdating = false;
  let observer = null;

  function getCurrentLanguage() {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_LANGUAGE;
  }

  function setCurrentLanguage(language) {
    localStorage.setItem(STORAGE_KEY, language);
  }

  function getTranslation(key, language) {
    const source = window.TRANSLATIONS && window.TRANSLATIONS[language];
    if (!source) return undefined;

    return key.split(".").reduce(function (obj, part) {
      return obj && obj[part];
    }, source);
  }

  function normalizeText(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function fallbackExact() {
    return (window.TSIINO_I18N_FALLBACKS && window.TSIINO_I18N_FALLBACKS.exact) || {};
  }

  function fallbackPhrases() {
    return (window.TSIINO_I18N_FALLBACKS && window.TSIINO_I18N_FALLBACKS.phrases) || {};
  }

  function translateFallbackString(original, language) {
    if (language !== "en") {
      return original;
    }

    if (!original || !String(original).trim()) {
      return original;
    }

    const originalString = String(original);
    const leading = originalString.match(/^\s*/)[0];
    const trailing = originalString.match(/\s*$/)[0];
    let core = originalString.trim();
    const normalizedCore = normalizeText(core);
    const exact = fallbackExact();

    if (Object.prototype.hasOwnProperty.call(exact, normalizedCore)) {
      return leading + exact[normalizedCore] + trailing;
    }

    const phrases = fallbackPhrases();
    Object.keys(phrases)
      .sort(function (a, b) { return b.length - a.length; })
      .forEach(function (ptPhrase) {
        if (core.indexOf(ptPhrase) !== -1) {
          core = core.split(ptPhrase).join(phrases[ptPhrase]);
        }
      });

    return leading + core + trailing;
  }

  function shouldSkipNode(node) {
    const parent = node.parentElement;
    if (!parent) return true;

    if (
      parent.closest(
        "script, style, noscript, template, code, pre, kbd, samp, textarea, .no-i18n"
      )
    ) {
      return true;
    }

    if (parent.closest("[data-i18n], [data-i18n-html]")) {
      return true;
    }

    if (parent.closest("#quarto-header, .navbar")) {
      return true;
    }

    return false;
  }

  function translateFallbackTextNodes(language) {
    if (!document.body) return;

    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          if (shouldSkipNode(node)) return NodeFilter.FILTER_REJECT;
          if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    const nodes = [];
    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }

    nodes.forEach(function (node) {
      if (!originalTextNodes.has(node)) {
        originalTextNodes.set(node, node.nodeValue);
      }
      const original = originalTextNodes.get(node);
      const translated = translateFallbackString(original, language);
      if (node.nodeValue !== translated) {
        node.nodeValue = translated;
      }
    });
  }

  function getOriginalAttr(element, attr) {
    const storeName = "tsiinoOriginal" + attr.replace(/[^a-z0-9]/gi, "_");
    if (!Object.prototype.hasOwnProperty.call(element.dataset, storeName)) {
      const value = element.getAttribute(attr);
      if (value !== null) {
        element.dataset[storeName] = value;
      }
    }
    return element.dataset[storeName];
  }

  function translateFallbackAttributes(language) {
    const attrs = ["alt", "title", "placeholder", "aria-label", "data-tip", "value"];

    attrs.forEach(function (attr) {
      document.querySelectorAll("[" + attr + "]").forEach(function (element) {
        if (element.closest("#quarto-header, .navbar") && attr !== "placeholder" && attr !== "aria-label") {
          return;
        }

        if (
          element.hasAttribute("data-i18n-alt") ||
          element.hasAttribute("data-i18n-title") ||
          element.hasAttribute("data-i18n-placeholder") ||
          element.hasAttribute("data-i18n-aria") ||
          element.hasAttribute("data-i18n-tip")
        ) {
          return;
        }

        const original = getOriginalAttr(element, attr);
        if (original === undefined || original === null) return;
        const translated = translateFallbackString(original, language);
        if (element.getAttribute(attr) !== translated) {
          element.setAttribute(attr, translated);
        }
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

    const navbarTools = document.querySelector(".quarto-navbar-tools");
    if (navbarTools) {
      const wrapper = document.createElement("span");
      wrapper.className = "language-toggle-tool";
      wrapper.appendChild(button);
      navbarTools.insertBefore(wrapper, navbarTools.firstChild);
      return button;
    }

    const existingRightNav = document.querySelector(".navbar .navbar-nav.ms-auto, .navbar .navbar-nav.me-auto");
    if (existingRightNav) {
      const item = document.createElement("li");
      item.className = "nav-item language-toggle-item";
      item.appendChild(button);
      existingRightNav.appendChild(item);
      return button;
    }

    const navbarCollapse = document.querySelector(".navbar .navbar-collapse");
    if (navbarCollapse) {
      const ul = document.createElement("ul");
      ul.className = "navbar-nav ms-auto";
      const item = document.createElement("li");
      item.className = "nav-item language-toggle-item";
      item.appendChild(button);
      ul.appendChild(item);
      navbarCollapse.appendChild(ul);
      return button;
    }

    const navbar = document.querySelector(".navbar .container-fluid, .navbar");
    if (navbar) {
      const wrapper = document.createElement("span");
      wrapper.className = "language-toggle-tool";
      wrapper.appendChild(button);
      navbar.appendChild(wrapper);
      return button;
    }

    return button;
  }

  function setElementText(element, text) {
    const target = element.querySelector("span.menu-text") || element;
    if (target.textContent !== text) {
      target.textContent = text;
    }
  }

  function normalizeHrefPath(href) {
    try {
      const url = new URL(href, window.location.href);
      let path = url.pathname.replace(/\\/g, "/");
      path = path.replace(/\/+$/, "/");
      if (path.endsWith("/")) path += "index.html";
      return path;
    } catch (err) {
      return String(href || "");
    }
  }

  function hrefMatchesTarget(href, target) {
    const path = normalizeHrefPath(href);
    const cleanTarget = String(target || "").replace(/^\/+/, "");
    const targetIndex = cleanTarget.replace(/\/+$/, "/index.html");

    if (path.endsWith("/" + targetIndex)) return true;
    if (path.endsWith("/" + targetIndex.replace(/\/index\.html$/, "/"))) return true;

    if (targetIndex === "index.html") {
      return /\/index\.html$/.test(path) && !/(expedicoes|conservacao|diversidade|team)\/index\.html$/.test(path);
    }

    return false;
  }

  function translateNavbar(language) {
    const links = getTranslation("navbar.links", language);
    if (!links) return;

    const targets = Object.keys(links).sort(function (a, b) { return b.length - a.length; });

    document.querySelectorAll(".navbar a[href]").forEach(function (link) {
      const href = link.getAttribute("href");
      if (!href) return;

      for (let i = 0; i < targets.length; i++) {
        const target = targets[i];
        if (hrefMatchesTarget(href, target)) {
          setElementText(link, links[target]);
          break;
        }
      }
    });
  }

  function translateMarkedElements(language) {
    document.querySelectorAll("[data-i18n]").forEach(function (element) {
      const key = element.getAttribute("data-i18n");
      const translation = getTranslation(key, language);
      if (translation !== undefined) element.textContent = String(translation).trim();
    });

    document.querySelectorAll("[data-i18n-html]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-html");
      const translation = getTranslation(key, language);
      if (translation !== undefined) element.innerHTML = String(translation).trim();
    });

    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-placeholder");
      const translation = getTranslation(key, language);
      if (translation !== undefined) element.setAttribute("placeholder", String(translation).trim());
    });

    document.querySelectorAll("[data-i18n-alt]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-alt");
      const translation = getTranslation(key, language);
      if (translation !== undefined) element.setAttribute("alt", String(translation).trim());
    });

    document.querySelectorAll("[data-i18n-title]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-title");
      const translation = getTranslation(key, language);
      if (translation !== undefined) element.setAttribute("title", String(translation).trim());
    });

    document.querySelectorAll("[data-i18n-aria]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-aria");
      const translation = getTranslation(key, language);
      if (translation !== undefined) element.setAttribute("aria-label", String(translation).trim());
    });

    document.querySelectorAll("[data-i18n-tip]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-tip");
      const translation = getTranslation(key, language);
      if (translation !== undefined) element.setAttribute("data-tip", String(translation).trim());
    });
  }

  function translateQuartoUI(language) {
    const q = getTranslation("quarto", language);
    if (!q) return;

    document.querySelectorAll("input[type='search'], .aa-Input").forEach(function (input) {
      input.setAttribute("placeholder", q.searchPlaceholder);
      input.setAttribute("aria-label", q.searchLabel);
    });

    document.querySelectorAll("#TOC .toc-title, .toc-title, #toc-title").forEach(function (element) {
      element.textContent = q.tocTitle;
    });

    document.querySelectorAll(".code-copy-button").forEach(function (button) {
      button.setAttribute("title", q.copyCode);
      button.setAttribute("aria-label", q.copyCode);
    });
  }

  function updateLanguage() {
    if (isUpdating) return;
    isUpdating = true;

    try {
      const language = getCurrentLanguage();
      const meta = window.TRANSLATIONS && window.TRANSLATIONS[language] && window.TRANSLATIONS[language].meta;
      if (!meta) return;

      const button = ensureLanguageButton();

      translateMarkedElements(language);
      translateFallbackTextNodes(language);
      translateFallbackAttributes(language);
      translateNavbar(language);
      translateQuartoUI(language);

      document.documentElement.lang = meta.htmlLang;

      button.textContent = meta.languageButton;
      button.setAttribute("aria-label", meta.languageButtonLabel);
      button.setAttribute("title", meta.languageButtonLabel);
    } finally {
      isUpdating = false;
    }
  }

  function scheduleUpdate() {
    if (observerTimers.has(document.body)) return;
    const timer = window.setTimeout(function () {
      observerTimers.delete(document.body);
      updateLanguage();
    }, 120);
    observerTimers.set(document.body, timer);
  }

  function init() {
    const button = ensureLanguageButton();
    if (!button.dataset.tsiinoBound) {
      button.addEventListener("click", function () {
        const currentLanguage = getCurrentLanguage();
        const nextLanguage = currentLanguage === "pt" ? "en" : "pt";
        setCurrentLanguage(nextLanguage);
        updateLanguage();
      });
      button.dataset.tsiinoBound = "true";
    }

    updateLanguage();
    window.setTimeout(updateLanguage, 250);
    window.setTimeout(updateLanguage, 1000);
    window.setTimeout(updateLanguage, 2500);

    if (document.body && !observer) {
      observer = new MutationObserver(function () {
        if (!isUpdating) scheduleUpdate();
      });
      observer.observe(document.body, {
        childList: true,
        subtree: true
      });
    }

    window.TSIINO_UPDATE_LANGUAGE = updateLanguage;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
