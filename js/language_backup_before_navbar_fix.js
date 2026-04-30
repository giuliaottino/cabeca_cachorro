(function () {
  "use strict";

  if (window.__TSIINO_I18N_RUNTIME_LOADED__) {
    return;
  }
  window.__TSIINO_I18N_RUNTIME_LOADED__ = true;

  const DEFAULT_LANGUAGE = "pt";
  const STORAGE_KEY = "site-language";

  let observerStarted = false;
  let updateScheduled = false;
  let isUpdating = false;

  function getTranslations() {
    return window.TRANSLATIONS || null;
  }

  function getCurrentLanguage() {
    const saved = localStorage.getItem(STORAGE_KEY);
    const translations = getTranslations();

    if (saved && translations && translations[saved]) {
      return saved;
    }

    return DEFAULT_LANGUAGE;
  }

  function setCurrentLanguage(language) {
    localStorage.setItem(STORAGE_KEY, language);
  }

  function getTranslation(key, language) {
    const translations = getTranslations();

    if (!translations || !translations[language] || !key) {
      return undefined;
    }

    return key.split(".").reduce(function (obj, part) {
      return obj && obj[part];
    }, translations[language]);
  }

  function getTextContainer(link) {
    return (
      link.querySelector(".menu-text") ||
      link.querySelector("span") ||
      link
    );
  }

  function normalizePathFromHref(href) {
    try {
      const url = new URL(href, window.location.href);
      let pathname = url.pathname.replace(/\\/g, "/");

      if (pathname.endsWith("/")) {
        pathname += "index.html";
      }

      return pathname;
    } catch (error) {
      return href || "";
    }
  }

  function hrefMatchesTarget(href, target) {
    if (!href || !target) {
      return false;
    }

    const normalizedHref = normalizePathFromHref(href);
    const normalizedTarget = target.replace(/\\/g, "/");
    const indexTarget = normalizedTarget.replace(/\/index\.html$/, "/index.html");

    return (
      normalizedHref.endsWith("/" + normalizedTarget) ||
      normalizedHref.endsWith(normalizedTarget) ||
      normalizedHref.endsWith("/" + indexTarget) ||
      normalizedHref.endsWith(indexTarget) ||
      (normalizedTarget === "index.html" && normalizedHref.endsWith("/index.html"))
    );
  }

  function buildNavbarTextMap(language) {
    const translations = getTranslations();
    const map = {};

    if (!translations || !translations.pt || !translations.en) {
      return map;
    }

    const ptLinks = translations.pt.navbar && translations.pt.navbar.links;
    const enLinks = translations.en.navbar && translations.en.navbar.links;

    if (!ptLinks || !enLinks) {
      return map;
    }

    Object.keys(ptLinks).forEach(function (target) {
      const ptLabel = ptLinks[target];
      const enLabel = enLinks[target];

      if (language === "en" && ptLabel && enLabel) {
        map[ptLabel.trim()] = enLabel;
      }

      if (language === "pt" && ptLabel && enLabel) {
        map[enLabel.trim()] = ptLabel;
      }
    });

    // Fallbacks for Quarto home links that may render as ./, ../, /, or an empty relative path.
    if (language === "en") {
      map["Sobre"] = "About";
    } else {
      map["About"] = "Sobre";
    }

    return map;
  }

  function findNavbarContainer() {
    return (
      document.querySelector("#quarto-header .quarto-navbar-tools") ||
      document.querySelector(".quarto-navbar-tools") ||
      document.querySelector("#quarto-header .navbar-nav.ms-auto") ||
      document.querySelector(".navbar .navbar-nav.ms-auto") ||
      document.querySelector("#quarto-header .navbar-collapse") ||
      document.querySelector(".navbar .navbar-collapse")
    );
  }

  function ensureLanguageButton() {
    let button = document.getElementById("language-toggle");

    if (!button) {
      button = document.createElement("button");
      button.id = "language-toggle";
      button.className = "language-toggle";
      button.type = "button";
    }

    let wrapper = document.getElementById("language-toggle-wrapper");

    if (!wrapper) {
      wrapper = document.createElement("div");
      wrapper.id = "language-toggle-wrapper";
      wrapper.className = "language-toggle-item";
    }

    if (!wrapper.contains(button)) {
      wrapper.appendChild(button);
    }

    const container = findNavbarContainer();

    // Do not append the button to the page body. If the Quarto navbar is not ready yet,
    // wait for the retry/update cycle instead of placing the button in the content area.
    if (!container) {
      return null;
    }

    if (!container.contains(wrapper)) {
      container.appendChild(wrapper);
    }

    return button;
  }

  function translateMarkedElements(language) {
    document.querySelectorAll("[data-i18n]").forEach(function (element) {
      const key = element.getAttribute("data-i18n");
      const translation = getTranslation(key, language);

      if (translation !== undefined) {
        element.textContent = String(translation).trim();
      }
    });

    document.querySelectorAll("[data-i18n-html]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-html");
      const translation = getTranslation(key, language);

      if (translation !== undefined) {
        element.innerHTML = String(translation).trim();
      }
    });

    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-placeholder");
      const translation = getTranslation(key, language);

      if (translation !== undefined) {
        element.setAttribute("placeholder", String(translation).trim());
      }
    });

    document.querySelectorAll("[data-i18n-alt]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-alt");
      const translation = getTranslation(key, language);

      if (translation !== undefined) {
        element.setAttribute("alt", String(translation).trim());
      }
    });

    document.querySelectorAll("[data-i18n-title]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-title");
      const translation = getTranslation(key, language);

      if (translation !== undefined) {
        element.setAttribute("title", String(translation).trim());
      }
    });

    document.querySelectorAll("[data-i18n-aria]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-aria");
      const translation = getTranslation(key, language);

      if (translation !== undefined) {
        element.setAttribute("aria-label", String(translation).trim());
      }
    });

    document.querySelectorAll("[data-i18n-tip]").forEach(function (element) {
      const key = element.getAttribute("data-i18n-tip");
      const translation = getTranslation(key, language);

      if (translation !== undefined) {
        element.setAttribute("data-tip", String(translation).trim());
      }
    });
  }

  function translateNavbar(language) {
    const links = getTranslation("navbar.links", language);
    const textMap = buildNavbarTextMap(language);

    document.querySelectorAll("#quarto-header .navbar a[href], .navbar a[href]").forEach(function (link) {
      const href = link.getAttribute("href");
      const textContainer = getTextContainer(link);
      let replacement = null;

      if (links && href) {
        Object.keys(links).forEach(function (target) {
          if (!replacement && hrefMatchesTarget(href, target)) {
            replacement = links[target];
          }
        });
      }

      const currentText = textContainer.textContent.trim();

      if (!replacement && textMap[currentText]) {
        replacement = textMap[currentText];
      }

      if (replacement) {
        textContainer.textContent = replacement;
      }
    });
  }

  function translateQuartoUI(language) {
    const q = getTranslation("quarto", language);

    if (!q) {
      return;
    }

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

  function translateMetadata(language) {
    const meta = getTranslation("meta", language);

    if (!meta) {
      return;
    }

    document.documentElement.lang = meta.htmlLang || language;
  }

  function updateLanguage() {
    const translations = getTranslations();

    if (!translations) {
      return;
    }

    const language = getCurrentLanguage();
    const meta = getTranslation("meta", language);

    if (!meta) {
      return;
    }

    isUpdating = true;

    const button = ensureLanguageButton();

    translateMarkedElements(language);
    translateNavbar(language);
    translateQuartoUI(language);
    translateMetadata(language);

    if (button) {
      button.textContent = meta.languageButton;
      button.setAttribute("aria-label", meta.languageButtonLabel);
      button.setAttribute("title", meta.languageButtonLabel);
      button.onclick = function () {
        const currentLanguage = getCurrentLanguage();
        const nextLanguage = currentLanguage === "pt" ? "en" : "pt";

        setCurrentLanguage(nextLanguage);
        updateLanguage();
      };
    }

    window.setTimeout(function () {
      isUpdating = false;
    }, 0);
  }

  function scheduleUpdate() {
    if (isUpdating || updateScheduled) {
      return;
    }

    updateScheduled = true;

    window.setTimeout(function () {
      updateScheduled = false;
      updateLanguage();
    }, 100);
  }

  function startObserver() {
    if (observerStarted || !document.body) {
      return;
    }

    observerStarted = true;

    const observer = new MutationObserver(function () {
      scheduleUpdate();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
  }

  function init() {
    if (!getTranslations()) {
      window.setTimeout(init, 50);
      return;
    }

    updateLanguage();
    startObserver();

    // Retries for Quarto widgets/search/navbar tools that can be inserted shortly after page load.
    window.setTimeout(updateLanguage, 250);
    window.setTimeout(updateLanguage, 750);
    window.setTimeout(updateLanguage, 1500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
