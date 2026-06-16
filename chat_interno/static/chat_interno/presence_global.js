(() => {
  const PING_INTERVAL_MS = 30000;
  let pingTimer = null;
  let started = false;
  let currentStatus = "offline";

  function getCookie(name) {
    const v = `; ${document.cookie}`;
    const parts = v.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function csrf() {
    return getCookie("csrftoken");
  }

  async function apiPost(url, formData) {
    const r = await fetch(url, {
      method: "POST",
      body: formData,
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrf(),
        "X-Requested-With": "XMLHttpRequest"
      }
    });
    return await r.json().catch(() => ({}));
  }

  async function ping() {
    try {
      const fd = new FormData();
      await apiPost("/chat/ping/", fd);
    } catch {}
  }

  function loadStatusFromLocalStorage() {
    const saved = localStorage.getItem("chat_presence_status");
    if (saved === "online" || saved === "ausente" || saved === "offline") {
      currentStatus = saved;
    }
  }

  function stopPingLoop() {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  async function startPingLoop() {
    stopPingLoop();

    if (currentStatus !== "online" && currentStatus !== "ausente") {
      return;
    }

    await ping();

    pingTimer = setInterval(() => {
      ping().catch(() => {});
    }, PING_INTERVAL_MS);
  }

  async function refresh() {
    loadStatusFromLocalStorage();

    if (!localStorage.getItem("chat_presence_status")) {
      // Primeira vez (sem preferência salva): entra como "online" por padrão.
      currentStatus = "online";
      localStorage.setItem("chat_presence_status", currentStatus);
      const fd = new FormData();
      fd.append("status", "online");
      await apiPost("/chat/api/status/", fd).catch(() => {});
    }

    await startPingLoop();
  }

  function setStatus(status) {
    if (!["online", "ausente", "offline"].includes(status)) return;

    currentStatus = status;
    localStorage.setItem("chat_presence_status", status);

    if (status === "online" || status === "ausente") {
      startPingLoop().catch(() => {});
    } else {
      stopPingLoop();
    }
  }

  function bindWindowEvents() {
    window.addEventListener("focus", () => {
      if (currentStatus === "online" || currentStatus === "ausente") {
        ping().catch(() => {});
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (currentStatus === "online" || currentStatus === "ausente") {
        ping().catch(() => {});
      }
    });

    window.addEventListener("storage", (e) => {
      if (e.key === "chat_presence_status") {
        loadStatusFromLocalStorage();
        startPingLoop().catch(() => {});
      }
    });
  }

  async function start() {
    if (started) return;
    started = true;

    bindWindowEvents();
    await refresh();
  }

  window.ChatPresenceGlobal = {
    start,
    refresh,
    setStatus,
    getStatus: () => currentStatus,
  };
})();