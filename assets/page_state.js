(function () {
  const PREFIX = "powerPlanPageState:";

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

  function read(key, fallback = {}) {
    try {
      const raw = window.localStorage.getItem(storageKey(key));
      if (!raw) return clone(fallback);
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : clone(fallback);
    } catch (error) {
      return clone(fallback);
    }
  }

  function write(key, value) {
    try {
      if (value == null) {
        window.localStorage.removeItem(storageKey(key));
        return;
      }
      window.localStorage.setItem(storageKey(key), JSON.stringify(value));
    } catch (error) {
      // State restore is an interface convenience; storage failures must not block the page.
    }
  }

  function patch(key, partial) {
    const current = read(key, {});
    const next = {
      ...(current && typeof current === "object" ? current : {}),
      ...(partial && typeof partial === "object" ? partial : {}),
    };
    write(key, next);
    return next;
  }

  window.PowerPlanPageState = {
    read,
    write,
    patch,
  };
})();
