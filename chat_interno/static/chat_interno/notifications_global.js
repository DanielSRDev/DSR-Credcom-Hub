(() => {
  let started = false;
  let pollTimer = null;
  let lastUnreadTotal = null;

  function setBadge(count) {
    const badge = document.getElementById("chatUnreadBadge");
    if (!badge) return;

    if (count > 0) {
      badge.style.display = "";
      badge.textContent = String(count);
    } else {
      badge.style.display = "none";
      badge.textContent = "0";
    }
  }

  async function apiGet(url) {
    const r = await fetch(url, {
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest"
      }
    });
    return await r.json().catch(() => ({}));
  }

  async function ensurePermission() {
    if (!("Notification" in window)) return false;

    if (Notification.permission === "granted") {
      return true;
    }

    if (Notification.permission === "default") {
      try {
        const result = await Notification.requestPermission();
        return result === "granted";
      } catch {
        return false;
      }
    }

    return false;
  }

  function showNotification(title, body) {
    if (!("Notification" in window)) return;
    if (Notification.permission !== "granted") return;

    try {
      const n = new Notification(title, {
        body: body || "Você recebeu uma nova mensagem.",
        tag: "chat-global-msg",
        renotify: true,
      });

      n.onclick = () => {
        window.focus();
        const btn = document.getElementById("chatToggleBtn");
        if (btn) {
          btn.click();
        } else {
          window.location.href = "/chat/";
        }
        n.close();
      };

      setTimeout(() => {
        try { n.close(); } catch {}
      }, 8000);
    } catch {}
  }

  async function refreshUnread() {
    try {
      const data = await apiGet("/chat/unread_total/");
      const count = Number(data.count || 0);

      setBadge(count);

      if (lastUnreadTotal === null) {
        lastUnreadTotal = count;
        return;
      }

      if (count > lastUnreadTotal) {
        const pageHidden = document.hidden || document.visibilityState !== "visible";
        if (pageHidden) {
          showNotification("Nova mensagem no chat", "Você recebeu uma nova mensagem.");
        }
      }

      lastUnreadTotal = count;
    } catch {}
  }

  async function start() {
    if (started) return;
    started = true;

    await ensurePermission().catch(() => {});
    await refreshUnread();

    pollTimer = setInterval(() => {
      refreshUnread().catch(() => {});
    }, 4000);
  }

  window.ChatNotificationsGlobal = {
    start,
    refreshUnread,
    ensurePermission,
    showNotification,
  };
})();