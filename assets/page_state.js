(function () {
  const PREFIX = "powerPlanPageState:";
  const CONTEXT_KEY = "powerPlanActiveContext";
  const CONTEXT_SYNC_KEYS = new Set(["planning", "optimization", "evaluation", "frequency", "reliability", "report", "sensitivity"]);

  function storageKey(key) {
    return `${PREFIX}${key || "default"}`;
  }

  function clone(value) {
    if (value == null || typeof value !== "object") return value;
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return value;
    }
  }

  function readUrlContext() {
    try {
      const params = new URLSearchParams(window.location.search || "");
      const scheme = String(params.get("scheme") || "").trim();
      const filename = String(params.get("file") || params.get("filename") || params.get("result") || "").trim();
      return { scheme, filename };
    } catch (_) {
      return { scheme: "", filename: "" };
    }
  }

  function readStoredContext() {
    try {
      const raw = window.localStorage.getItem(CONTEXT_KEY);
      if (!raw) return { scheme: "", filename: "", updatedAt: 0 };
      const parsed = JSON.parse(raw);
      return {
        scheme: String(parsed?.scheme || "").trim(),
        filename: String(parsed?.filename || "").trim(),
        updatedAt: Number(parsed?.updatedAt) || 0,
      };
    } catch (_) {
      return { scheme: "", filename: "", updatedAt: 0 };
    }
  }

  function getActiveContext() {
    const urlCtx = readUrlContext();
    const stored = readStoredContext();
    const scheme = urlCtx.scheme || stored.scheme || "";
    const filename = urlCtx.filename || (urlCtx.scheme && urlCtx.scheme !== stored.scheme ? "" : stored.filename) || "";
    return { scheme, filename, updatedAt: stored.updatedAt };
  }

  function setActiveContext(partial = {}, options = {}) {
    const prev = readStoredContext();
    const nextScheme =
      partial && Object.prototype.hasOwnProperty.call(partial, "scheme")
        ? String(partial.scheme || "").trim()
        : prev.scheme;
    let nextFile = prev.filename;
    if (partial && Object.prototype.hasOwnProperty.call(partial, "filename")) {
      nextFile = String(partial.filename || "").trim();
    } else if (nextScheme && prev.scheme && nextScheme !== prev.scheme) {
      nextFile = "";
    }
    const next = {
      scheme: nextScheme,
      filename: nextFile,
      updatedAt: Date.now(),
    };
    try {
      window.localStorage.setItem(CONTEXT_KEY, JSON.stringify(next));
    } catch (_) {
      // 忽略本地存储受限异常
    }
    if (!options.silent && typeof window.dispatchEvent === "function") {
      window.dispatchEvent(new CustomEvent("powerplan:contextchange", { detail: next }));
    }
    return next;
  }

  function buildContextUrl(page, overrides = {}) {
    const ctx = getActiveContext();
    const scheme =
      overrides && Object.prototype.hasOwnProperty.call(overrides, "scheme")
        ? String(overrides.scheme || "").trim()
        : ctx.scheme;
    const filename =
      overrides && Object.prototype.hasOwnProperty.call(overrides, "filename")
        ? String(overrides.filename || "").trim()
        : ctx.filename;
    const params = new URLSearchParams();
    if (scheme) params.set("scheme", scheme);
    if (filename) params.set("file", filename);
    if (overrides && overrides.extra && typeof overrides.extra === "object") {
      Object.entries(overrides.extra).forEach(([k, v]) => {
        if (v !== undefined && v !== null && String(v) !== "") params.set(k, String(v));
      });
    }
    const qs = params.toString();
    return qs ? `${page}?${qs}` : page;
  }

  function readRaw(key, fallback = {}) {
    try {
      const raw = window.localStorage.getItem(storageKey(key));
      if (!raw) return clone(fallback);
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : clone(fallback);
    } catch (error) {
      return clone(fallback);
    }
  }

  function read(key, fallback = {}) {
    const base = readRaw(key, fallback);
    if (!CONTEXT_SYNC_KEYS.has(key) || !base || typeof base !== "object") {
      return base;
    }
    const urlCtx = readUrlContext();
    const storedCtx = readStoredContext();
    const savedAt = Number(base._savedAt) || 0;

    if (urlCtx.scheme) {
      base.currentScheme = urlCtx.scheme;
      if (urlCtx.filename) {
        base.selectedResultFile = urlCtx.filename;
        base.selectedResult = urlCtx.filename;
      } else if (base.currentScheme !== readRaw(key, {}).currentScheme) {
        base.selectedResultFile = "";
        base.selectedResult = "";
      }
      setActiveContext({ scheme: urlCtx.scheme, ...(urlCtx.filename ? { filename: urlCtx.filename } : {}) }, { silent: true });
    } else if (storedCtx.scheme && storedCtx.updatedAt > savedAt) {
      const schemeChanged = storedCtx.scheme !== base.currentScheme;
      base.currentScheme = storedCtx.scheme;
      if (storedCtx.filename) {
        base.selectedResultFile = storedCtx.filename;
        base.selectedResult = storedCtx.filename;
      } else if (schemeChanged) {
        base.selectedResultFile = "";
        base.selectedResult = "";
      }
    }
    return base;
  }

  function write(key, value) {
    try {
      if (value == null) {
        window.localStorage.removeItem(storageKey(key));
        return;
      }
      const payload = typeof value === "object" ? { ...value, _savedAt: Date.now() } : value;
      window.localStorage.setItem(storageKey(key), JSON.stringify(payload));
      if (CONTEXT_SYNC_KEYS.has(key) && payload && typeof payload === "object") {
        const scheme = String(payload.currentScheme || payload.scheme || "").trim();
        const hasFileField =
          Object.prototype.hasOwnProperty.call(payload, "selectedResultFile") ||
          Object.prototype.hasOwnProperty.call(payload, "selectedResult") ||
          Object.prototype.hasOwnProperty.call(payload, "filename");
        const filename = String(payload.selectedResultFile || payload.selectedResult || payload.filename || "").trim();
        if (scheme) {
          setActiveContext(hasFileField ? { scheme, filename } : { scheme });
        }
      }
    } catch (error) {
      // State restore is an interface convenience; storage failures must not block the page.
    }
  }

  function patch(key, partial) {
    const current = readRaw(key, {});
    const next = {
      ...(current && typeof current === "object" ? current : {}),
      ...(partial && typeof partial === "object" ? partial : {}),
    };
    write(key, next);
    return next;
  }

  function isFiniteNumber(value) {
    return value !== null && value !== "" && Number.isFinite(Number(value));
  }

  function number(value, fallback = null) {
    return isFiniteNumber(value) ? Number(value) : fallback;
  }

  window.PowerPlanPageState = {
    read,
    write,
    patch,
    isFiniteNumber,
    number,
    getActiveContext,
    setActiveContext,
    buildContextUrl,
  };
})();
