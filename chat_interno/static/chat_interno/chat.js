window.ChatUI = (() => {
  let currentOtherId = null;
  let pollTimer = null;
  let unreadTimer = null;
  let canExport = false;
  let started = false;

  let actorUserId = "";
  let monitorBound = false;

  let bound = false;
  let sending = false;
  let historyLoading = false;

  let lastRenderedLastId = 0;
  let lastMarkAt = 0;

  let lastSoundId = 0;
  let lastUnreadTotal = null;

  let suppressHistorySound = false;
  let myStatus = "offline";

  let lastNotifiedMessageId = 0;
  let notificationPermissionRequested = false;
  const originalDocumentTitle = document.title || "Hub";

  let contactsMap = {};

  // Reply state
  let replyTo = null;

  const soundMsg = new Audio("/static/chat_interno/sounds/msg.mp3");
  soundMsg.volume = 0.6;
  let soundUnlocked = false;

  function unlockAudioOnce() {
    function tryUnlock() {
      soundMsg.play()
        .then(() => { soundMsg.pause(); soundMsg.currentTime = 0; soundUnlocked = true; document.removeEventListener("click", tryUnlock); })
        .catch(() => {});
    }
    document.addEventListener("click", tryUnlock);
  }

  function playNewMessageSound() {
    try { soundMsg.currentTime = 0; soundMsg.play().catch(() => {}); } catch (_) {}
  }

  function myUserId() {
    return Number(document.getElementById("chatMeId")?.value || 0);
  }

  function getCookie(name) {
    const v = `; ${document.cookie}`;
    const parts = v.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function csrf() { return getCookie("csrftoken"); }

  function withActor(url) {
    if (!actorUserId) return url;
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}as_user=${encodeURIComponent(actorUserId)}`;
  }

  async function apiGet(url) {
    const r = await fetch(withActor(url), {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    return await r.json().catch(() => ({}));
  }

  async function apiPost(url, formData) {
    const r = await fetch(withActor(url), {
      method: "POST",
      body: formData,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
    });
    return await r.json().catch(() => ({}));
  }

  async function doPing() {
    const fd = new FormData();
    await apiPost("/chat/ping/", fd);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatTextWithLineBreaks(text) {
    if (!text) return "";
    return escapeHtml(text).replace(/\n/g, "<br>");
  }

  function formatDate(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
    } catch (_) { return iso; }
  }

  function paintStatusButtons() {
    const box = document.querySelector(".chat-status-box");
    if (!box) return;
    box.querySelectorAll("button.status").forEach((btn) => {
      const st = (btn.dataset.status || "").toLowerCase();
      if (st === myStatus) btn.classList.add("active");
      else btn.classList.remove("active");
    });
  }

  async function setStatus(status) {
    const fd = new FormData();
    fd.append("status", status);
    const data = await apiPost("/chat/api/status/", fd);
    if (data?.error) { alert(data.error); return; }
    myStatus = data.status || status || "offline";
    paintStatusButtons();
    localStorage.setItem("chat_presence_status", myStatus);
    if (window.ChatPresenceGlobal) {
      window.ChatPresenceGlobal.setStatus(myStatus);
      window.ChatPresenceGlobal.refresh().catch(() => {});
    }
    await loadContacts();
  }

  async function refreshUnreadBadge() {
    const badge = document.getElementById("chatUnreadBadge");
    if (!badge) return;
    const data = await apiGet("/chat/unread_total/");
    const count = Number(data.count || 0);
    if (count > 0) {
      badge.style.display = "";
      badge.textContent = String(count);
    } else {
      badge.style.display = "none";
      badge.textContent = "0";
    }
    if (window.ChatNotificationsGlobal) {
      window.ChatNotificationsGlobal.refreshUnread().catch(() => {});
    }
  }

  async function markRead(otherId) {
    if (!otherId || actorUserId) return;
    const fd = new FormData();
    await apiPost(`/chat/mark_read/${otherId}/`, fd);
    await refreshUnreadBadge();
  }

  function sortContacts(items) {
    const weight = (st) => st === "online" ? 2 : st === "ausente" ? 1 : 0;
    return (items || []).slice().sort((a, b) => {
      const au = a.unread > 0 ? 1 : 0;
      const bu = b.unread > 0 ? 1 : 0;
      if (au !== bu) return bu - au;
      const aw = weight(a.status);
      const bw = weight(b.status);
      if (aw !== bw) return bw - aw;
      const an = (a.nome || a.username || "").toLowerCase();
      const bn = (b.nome || b.username || "").toLowerCase();
      return an.localeCompare(bn);
    });
  }

  function enableConversationUI(on) {
    ["chatInput","chatSendBtn","chatSearchMsg","chatSearchBtn","chatEmojiBtn","chatImgBtn"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = !on;
    });
    const exportBtn = document.getElementById("chatExportBtn");
    if (exportBtn) exportBtn.style.display = on && canExport ? "" : "none";
  }

  function setActiveContact(otherId) {
    const list = document.getElementById("chatUserList");
    if (!list) return;
    [...list.querySelectorAll(".list-group-item")].forEach((btn) => {
      const id = Number(btn.dataset.userId || 0);
      if (id && id === Number(otherId)) btn.classList.add("active");
      else btn.classList.remove("active");
    });
  }

  function ensureToastContainer() {
    let c = document.getElementById("chat-toast-container");
    if (!c) { c = document.createElement("div"); c.id = "chat-toast-container"; document.body.appendChild(c); }
    return c;
  }

  function showInternalToast(title, body, onClick = null) {
    const container = ensureToastContainer();
    const toast = document.createElement("div");
    toast.className = "chat-toast";
    toast.innerHTML = `<div class="chat-toast-title">${escapeHtml(title)}</div><div class="chat-toast-body">${escapeHtml(body || "")}</div>`;
    if (typeof onClick === "function") {
      toast.style.cursor = "pointer";
      toast.addEventListener("click", () => { onClick(); toast.remove(); });
    }
    container.appendChild(toast);
    setTimeout(() => toast.classList.add("show"), 10);
    setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 250); }, 6000);
  }

  // ─── Notificação browser (apenas HTTPS/localhost) ──────────────────────────
  async function requestBrowserNotificationPermissionOnce() {
    if (!window.isSecureContext) return "insecure";
    if (!("Notification" in window)) return "unsupported";
    if (Notification.permission === "granted") return "granted";
    if (Notification.permission === "denied") return "denied";
    if (notificationPermissionRequested) return Notification.permission;
    notificationPermissionRequested = true;
    try { return await Notification.requestPermission(); } catch (_) { return "default"; }
  }

  function showBrowserNotification(title, body, otherUserId = null) {
    if (!window.isSecureContext) return false;
    if (!("Notification" in window) || Notification.permission !== "granted") return false;
    try {
      const n = new Notification(title, {
        body: body || "Você recebeu uma nova mensagem.",
        tag: otherUserId ? `chat-${otherUserId}` : "chat-message",
        renotify: true,
      });
      n.onclick = () => { window.focus(); try { n.close(); } catch (_) {} if (otherUserId) open(otherUserId); };
      setTimeout(() => { try { n.close(); } catch (_) {} }, 8000);
      return true;
    } catch (_) { return false; }
  }

  function flashDocumentTitle() {
    try {
      document.title = "(Nova mensagem) Hub";
      setTimeout(() => { document.title = originalDocumentTitle; }, 4000);
    } catch (_) {}
  }

  function notifyIncomingMessage({ messageId, senderName, text, otherUserId }) {
    if (!messageId || messageId <= lastNotifiedMessageId) return;
    lastNotifiedMessageId = messageId;
    const title = `Nova mensagem de ${senderName || "Contato"}`;
    const body = text || "Você recebeu uma nova mensagem no chat.";
    showInternalToast(title, body, () => { if (otherUserId) open(otherUserId); });
    playNewMessageSound();
    showBrowserNotification(title, body, otherUserId);
    flashDocumentTitle();
  }

  // ─── Reply ─────────────────────────────────────────────────────────────────
  function setReply(msgId, senderLabel, texto) {
    replyTo = { id: msgId, sender: senderLabel, texto };
    const bar = document.getElementById("chatReplyBar");
    const senderEl = document.getElementById("chatReplySender");
    const textEl = document.getElementById("chatReplyText");
    if (bar) bar.style.display = "";
    if (senderEl) senderEl.textContent = `Respondendo a: ${senderLabel}`;
    if (textEl) textEl.textContent = texto || "[imagem]";
    document.getElementById("chatInput")?.focus();
  }

  function clearReply() {
    replyTo = null;
    const bar = document.getElementById("chatReplyBar");
    if (bar) bar.style.display = "none";
  }

  // ─── Reactions ─────────────────────────────────────────────────────────────
  async function toggleReaction(msgId, emoji) {
    const fd = new FormData();
    fd.append("emoji", emoji);
    await apiPost(`/chat/react/${msgId}/`, fd);
    lastRenderedLastId = 0; // força re-render sem esperar o próximo poll
    await loadHistory(false);
  }

  async function loadContacts() {
    const data = await apiGet("/chat/contacts/");
    const list = document.getElementById("chatUserList");
    if (!list) return;

    canExport = !!data.can_export;
    if (data.my_status) {
      myStatus = data.my_status;
      localStorage.setItem("chat_presence_status", myStatus);
      paintStatusButtons();
    }

    (data.items || []).forEach((u) => {
      contactsMap[u.id] = { nome: u.nome, username: u.username };
    });

    const box = document.getElementById("chatMonitorBox");
    const sel = document.getElementById("chatMonitorSelect");
    if (data.can_monitor && box && sel) {
      box.style.display = "";
      const current = String(actorUserId || "");
      sel.innerHTML = `<option value="">Minha visão</option>`;
      (data.monitor_users || []).forEach((u) => {
        const opt = document.createElement("option");
        opt.value = String(u.id);
        opt.textContent = u.username;
        if (opt.value === current) opt.selected = true;
        sel.appendChild(opt);
      });
      if (!monitorBound) {
        monitorBound = true;
        sel.addEventListener("change", async () => {
          actorUserId = sel.value || "";
          currentOtherId = null;
          const otherHidden = document.getElementById("chatOtherId");
          if (otherHidden) otherHidden.value = "";
          const msgs = document.getElementById("chatMsgs");
          if (msgs) msgs.innerHTML = "";
          const hint = document.getElementById("chatHint");
          if (hint) hint.textContent = actorUserId ? "Monitorando usuário selecionado" : "Selecione um contato.";
          enableConversationUI(false);
          await loadContacts();
        });
      }
    } else if (box) { box.style.display = "none"; }

    list.innerHTML = "";
    const items = sortContacts(data.items || []);

    if (items.length === 0) {
      list.innerHTML = `<div class="text-secondary small">Nenhum contato disponível para você.</div>`;
      return;
    }

    items.forEach((u) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.userId = u.id;

      const hasUnread = u.unread > 0;
      btn.className = "list-group-item list-group-item-action" + (hasUnread ? " chat-item-unread" : "");

      const nm = u.nome || u.username;
      btn.onclick = () => open(u.id, nm);

      const dotClass = u.status === "online" ? "chat-dot-online" : u.status === "ausente" ? "chat-dot-ausente" : "chat-dot-offline";
      const statusTxt = u.status === "online" ? "Online" : u.status === "ausente" ? "Ausente" : "Offline";

      btn.innerHTML = `
        <div class="d-flex align-items-center justify-content-between">
          <div class="fw-semibold">${escapeHtml(nm)}</div>
          ${hasUnread ? `<span class="chat-unread-badge">${u.unread}</span>` : ""}
        </div>
        <div class="small d-flex align-items-center gap-1" style="opacity:.75;">
          <span class="chat-dot ${dotClass}"></span> ${statusTxt}
        </div>`;

      if (Number(u.id) === Number(currentOtherId)) btn.classList.add("active");
      list.appendChild(btn);
    });

    paintStatusButtons();
  }

  async function open(otherId, otherName = null) {
    currentOtherId = Number(otherId);
    suppressHistorySound = true;
    lastRenderedLastId = 0;
    lastSoundId = 0;
    clearReply();

    const otherHidden = document.getElementById("chatOtherId");
    if (otherHidden) otherHidden.value = currentOtherId;

    enableConversationUI(true);
    if (actorUserId) enableConversationUI(false);

    const hint = document.getElementById("chatHint");
    if (hint) hint.textContent = otherName ? `Conversa com: ${otherName}` : "Conversa aberta.";

    const head = document.getElementById("chatConvHead");
    if (head) head.classList.add("active");

    setActiveContact(currentOtherId);

    await doPing();
    await loadContacts();
    await loadHistory(true);

    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => { loadHistory(false).catch(() => {}); }, 4000);
  }

  async function loadHistory(forceScroll) {
    if (!currentOtherId || historyLoading) return;
    historyLoading = true;

    try {
      const data = await apiGet(`/chat/history/${currentOtherId}/`);
      if (data?.error) return;

      const box = document.getElementById("chatMsgs");
      if (!box) return;

      const items = data.items || [];
      const lastMsg = items.length ? items[items.length - 1] : null;
      const lastId = lastMsg ? Number(lastMsg.id || 0) : 0;

      if (lastId && lastId === lastRenderedLastId && !forceScroll) return;

      const wasAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
      box.innerHTML = "";

      const me = myUserId();

      items.forEach((m) => {
        const wrap = document.createElement("div");
        wrap.className = `mb-2 d-flex align-items-center chat-msg-wrap ${m.is_me ? "justify-content-end" : "justify-content-start"}`;
        wrap.dataset.msgId = m.id;

        const bubble = document.createElement("div");
        bubble.className = `chat-bubble ${m.is_me ? "mine" : "theirs"}`;

        const senderLabel = m.is_me ? "Você" : (m.sender_name || "Contato");

        // Bloco de citação (reply_to)
        if (m.reply_to) {
          const rt = m.reply_to;
          const rtSender = rt.sender_name || "?";
          const rtText = rt.texto
            ? (rt.texto.length > 80 ? rt.texto.substring(0, 80) + "…" : rt.texto)
            : (rt.imagem_url ? "[imagem]" : "");
          const quote = document.createElement("div");
          quote.className = "chat-reply-quote";
          quote.dataset.replyId = rt.id;
          quote.innerHTML = `<div class="reply-sender">${escapeHtml(rtSender)}</div><div class="reply-text">${escapeHtml(rtText)}</div>`;
          bubble.appendChild(quote);
        }

        // Meta + texto
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = `${senderLabel} • ${formatDate(m.criado_em)}`;
        bubble.appendChild(meta);

        if (m.texto) {
          const body = document.createElement("div");
          body.className = "body";
          body.innerHTML = formatTextWithLineBreaks(m.texto);
          bubble.appendChild(body);
        }

        if (m.imagem_url) {
          const img = document.createElement("img");
          img.className = "chat-img";
          img.src = m.imagem_url;
          img.alt = "imagem";
          bubble.appendChild(img);
        }

        // Reactions
        const reactions = m.reactions || {};
        const reactionEntries = Object.entries(reactions);
        if (reactionEntries.length > 0) {
          const reactionDiv = document.createElement("div");
          reactionDiv.className = "chat-reactions";
          reactionEntries.forEach(([emoji, info]) => {
            const span = document.createElement("span");
            span.className = "chat-reaction-item" + (info.mine ? " mine" : "");
            span.dataset.action = "react";
            span.dataset.msgId = m.id;
            span.dataset.emoji = emoji;
            span.textContent = `${emoji} ${info.count}`;
            reactionDiv.appendChild(span);
          });
          bubble.appendChild(reactionDiv);
        }

        // Botões de ação (visíveis no hover)
        const actions = document.createElement("div");
        actions.className = "chat-msg-actions";

        const replyBtn = document.createElement("button");
        replyBtn.className = "chat-action-btn";
        replyBtn.dataset.action = "reply";
        replyBtn.dataset.msgId = m.id;
        replyBtn.dataset.sender = senderLabel;
        replyBtn.dataset.texto = (m.texto || "").substring(0, 100);
        replyBtn.title = "Responder";
        replyBtn.textContent = "↩";

        const reactBtn = document.createElement("button");
        reactBtn.className = "chat-action-btn";
        reactBtn.dataset.action = "react";
        reactBtn.dataset.msgId = m.id;
        reactBtn.dataset.emoji = "👍";
        reactBtn.title = "Curtir";
        reactBtn.textContent = "👍";

        actions.appendChild(replyBtn);
        actions.appendChild(reactBtn);

        // "mine" → ações à esquerda do bubble; "theirs" → ações à direita
        if (m.is_me) {
          wrap.appendChild(actions);
          wrap.appendChild(bubble);
        } else {
          wrap.appendChild(bubble);
          wrap.appendChild(actions);
        }

        box.appendChild(wrap);
      });

      if (forceScroll || wasAtBottom) box.scrollTop = box.scrollHeight;

      if (lastId && lastId !== lastRenderedLastId) {
        if (suppressHistorySound) {
          lastSoundId = lastId;
          lastRenderedLastId = lastId;
          suppressHistorySound = false;
          const now = Date.now();
          if (now - lastMarkAt > 1500) { lastMarkAt = now; await markRead(currentOtherId); }
          await loadContacts();
          return;
        }

        if (lastMsg && !lastMsg.is_me && lastId !== lastSoundId) {
          lastSoundId = lastId;
          const senderName = lastMsg.sender_name ||
            (contactsMap[currentOtherId]
              ? (contactsMap[currentOtherId].nome || contactsMap[currentOtherId].username)
              : "Contato");
          notifyIncomingMessage({ messageId: lastId, senderName, text: lastMsg.texto || "", otherUserId: currentOtherId });
        }

        lastRenderedLastId = lastId;
        const now = Date.now();
        if (now - lastMarkAt > 1500) { lastMarkAt = now; await markRead(currentOtherId); }
        await loadContacts();
      } else if (!lastId) {
        // sem mensagens — garante que lastRenderedLastId fica zerado para nova conversa
        lastRenderedLastId = 0;
      }
    } finally { historyLoading = false; }
  }

  async function checkNewMessagesWhileClosed() {
    const panel = document.getElementById("chatPanel");
    const isOpen = panel && panel.classList.contains("open");
    if (isOpen && currentOtherId) return;

    const data = await apiGet("/chat/contacts/");
    const items = data.items || [];

    items.forEach((u) => { contactsMap[u.id] = { nome: u.nome, username: u.username }; });

    let totalUnread = 0;
    let firstUnreadUser = null;
    for (const u of items) {
      if (u.unread > 0) { totalUnread += u.unread; if (!firstUnreadUser) firstUnreadUser = u; }
    }

    const badge = document.getElementById("chatUnreadBadge");
    if (badge) {
      if (totalUnread > 0) { badge.style.display = ""; badge.textContent = String(totalUnread); }
      else { badge.style.display = "none"; badge.textContent = "0"; }
    }

    if (lastUnreadTotal !== null && totalUnread > lastUnreadTotal && firstUnreadUser) {
      const nome = firstUnreadUser.nome || firstUnreadUser.username;
      const otherId = firstUnreadUser.id;
      showInternalToast(
        `Nova mensagem de ${nome}`,
        `${firstUnreadUser.unread} mensagem(ns) não lida(s)`,
        () => {
          if (panel && !panel.classList.contains("open")) {
            const toggle = document.getElementById("chatToggleBtn");
            if (toggle) toggle.click();
          }
          setTimeout(() => open(otherId, nome), 150);
        }
      );
      playNewMessageSound();
      showBrowserNotification(`Nova mensagem de ${nome}`, `${firstUnreadUser.unread} mensagem(ns) não lida(s)`, otherId);
      flashDocumentTitle();
    }

    lastUnreadTotal = totalUnread;
  }

  function dataURLtoBlob(dataURL) {
    try {
      const arr = dataURL.split(",");
      const mime = arr[0].match(/:(.*?);/)[1];
      const bstr = atob(arr[1]);
      let n = bstr.length;
      const u8arr = new Uint8Array(n);
      while (n--) u8arr[n] = bstr.charCodeAt(n);
      return new Blob([u8arr], { type: mime });
    } catch (_) { return null; }
  }

  function clearPastedImagePreview() {
    const input = document.getElementById("chatInput");
    if (input) delete input.dataset.pastedImage;
    const preview = document.getElementById("chatPastePreview");
    if (preview) preview.remove();
    const hint = document.getElementById("chatFileHint");
    if (hint) { hint.style.display = "none"; hint.innerHTML = ""; }
  }

  function showPastedImagePreview(dataURL) {
    clearPastedImagePreview();
    const input = document.getElementById("chatInput");
    if (!input) return;
    input.dataset.pastedImage = dataURL;

    const preview = document.createElement("div");
    preview.id = "chatPastePreview";
    preview.style.cssText = "display:inline-flex;align-items:flex-start;gap:6px;margin-top:6px;";

    const img = document.createElement("img");
    img.src = dataURL;
    img.style.cssText = "max-height:70px;max-width:180px;border-radius:6px;border:2px solid #2f7df6;";

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.innerHTML = "✕";
    removeBtn.title = "Remover imagem";
    removeBtn.style.cssText = "background:#e74c3c;color:#fff;border:none;border-radius:50%;width:18px;height:18px;font-size:10px;cursor:pointer;flex-shrink:0;";
    removeBtn.onclick = clearPastedImagePreview;

    preview.appendChild(img);
    preview.appendChild(removeBtn);

    const hint = document.getElementById("chatFileHint");
    if (hint) {
      hint.style.display = "";
      hint.innerHTML = "";
      hint.appendChild(preview);
    }
  }

  async function send() {
    if (actorUserId) { alert("Modo monitor: somente visualização."); return; }
    if (sending) return;
    sending = true;

    try {
      const input = document.getElementById("chatInput");
      const file = document.getElementById("chatImg");
      if (!input) return;

      const texto = (input.value || "").replace(/\n+$/, "");
      const otherId = currentOtherId || Number(document.getElementById("chatOtherId")?.value || 0);
      if (!otherId) return;

      const hasImage = file && file.files && file.files.length > 0;
      const pastedImage = input.dataset.pastedImage || "";

      if (!texto && !hasImage && !pastedImage) return;

      await doPing();

      const fd = new FormData();
      if (texto) fd.append("texto", texto);
      if (hasImage) {
        fd.append("imagem", file.files[0]);
      } else if (pastedImage) {
        const blob = dataURLtoBlob(pastedImage);
        if (blob) fd.append("imagem", blob, "imagem_colada.png");
      }
      if (replyTo && replyTo.id) fd.append("reply_to_id", replyTo.id);

      const data = await apiPost(`/chat/send/${otherId}/`, fd);
      if (data?.error) { alert(data.error); return; }

      input.value = "";
      if (file) file.value = "";
      clearPastedImagePreview();
      clearReply();

      await loadHistory(true);
    } finally { sending = false; }
  }

  function bindUIOnce() {
    if (bound) return;
    bound = true;

    const sendBtn = document.getElementById("chatSendBtn");
    const input = document.getElementById("chatInput");
    const emoji = document.getElementById("chatEmojiBtn");
    const imgBtn = document.getElementById("chatImgBtn");
    const imgIn = document.getElementById("chatImg");
    const exportBtn = document.getElementById("chatExportBtn");
    const clearReplyBtn = document.getElementById("chatClearReply");

    if (sendBtn) sendBtn.addEventListener("click", (e) => { e.preventDefault(); send(); });

    if (clearReplyBtn) clearReplyBtn.addEventListener("click", clearReply);

    // Delegação de eventos na área de mensagens
    const msgsBox = document.getElementById("chatMsgs");
    if (msgsBox) {
      msgsBox.addEventListener("click", (e) => {
        // Botões de ação (reply / react) e badges de reação
        const btn = e.target.closest("[data-action]");
        if (btn) {
          const action = btn.dataset.action;
          const msgId = Number(btn.dataset.msgId || 0);
          if (!msgId) return;

          if (action === "reply") {
            setReply(msgId, btn.dataset.sender || "?", btn.dataset.texto || "");
          } else if (action === "react" && !actorUserId) {
            toggleReaction(msgId, btn.dataset.emoji || "👍").catch(() => {});
          }
          return;
        }

        // Clique no bloco de citação → rola até a mensagem original
        const quote = e.target.closest("[data-reply-id]");
        if (quote) {
          const replyId = quote.dataset.replyId;
          const orig = msgsBox.querySelector(`.chat-msg-wrap[data-msg-id="${replyId}"]`);
          if (orig) {
            orig.scrollIntoView({ behavior: "smooth", block: "center" });
            const bbl = orig.querySelector(".chat-bubble");
            if (bbl) {
              bbl.classList.add("chat-bubble-highlight");
              setTimeout(() => bbl.classList.remove("chat-bubble-highlight"), 1600);
            }
          }
        }
      });
    }

    if (exportBtn) {
      exportBtn.addEventListener("click", (e) => {
        e.preventDefault();
        const meId = document.getElementById("chatMeId")?.value;
        if (!meId) return;
        let u1 = actorUserId || meId;
        let u2 = currentOtherId;
        if (!u2) return;
        if (canExport) {
          const ask = prompt("Exportar histórico.\n\nDigite dois usuários separados por vírgula, ou vazio para conversa atual.\nEx: hudson,gabriel");
          if (ask && ask.includes(",")) {
            const parts = ask.split(",").map((s) => s.trim()).filter(Boolean);
            if (parts.length >= 2) { u1 = parts[0]; u2 = parts[1]; }
          }
        }
        window.open(`/chat/export/?u1=${encodeURIComponent(u1)}&u2=${encodeURIComponent(u2)}`, "_blank");
      });
    }

    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
      });

      input.addEventListener("paste", (e) => {
        const items = (e.clipboardData || e.originalEvent?.clipboardData)?.items;
        if (!items) return;
        for (const item of items) {
          if (item.type.indexOf("image") !== -1) {
            e.preventDefault();
            const blob = item.getAsFile();
            if (!blob) continue;
            const reader = new FileReader();
            reader.onload = (ev) => showPastedImagePreview(ev.target.result);
            reader.readAsDataURL(blob);
            return;
          }
        }
      });
    }

    if (emoji) {
      emoji.addEventListener("click", () => {
        if (!input) return;
        const pick = prompt("Digite um emoji:", "😀");
        if (pick) input.value = (input.value || "") + pick;
        input.focus();
      });
    }

    if (imgBtn && imgIn) imgBtn.addEventListener("click", () => imgIn.click());
  }

  async function start() {
    bindUIOnce();
    unlockAudioOnce();
    await requestBrowserNotificationPermissionOnce().catch(() => {});
    enableConversationUI(false);
    await doPing();
    await loadContacts();
    await refreshUnreadBadge();

    if (!started) {
      started = true;
      unreadTimer = setInterval(() => { checkNewMessagesWhileClosed().catch(() => {}); }, 4000);
    }

    paintStatusButtons();
  }

  return { start, open, send, setStatus };
})();
