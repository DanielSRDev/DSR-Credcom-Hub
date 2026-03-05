window.ChatUI = (() => {
  let currentOtherId = null;
  let pollTimer = null;
  let pingTimer = null;
  let canExport = false;

  let bound = false;      // ✅ garante 1 bind só
  let sending = false;    // ✅ trava duplo envio
  let historyLoading = false;

  // ✅ controle de mudança
  let lastRenderedLastId = 0;
  let lastMarkAt = 0;

  // 🔊 controle do som
  let lastSoundId = 0;
  let lastUnreadTotal = 0;

  // ✅ NOVO: ao abrir conversa, não tocar som do histórico antigo
  let suppressHistorySound = false;

  // ✅ NOVO: status atual do ME (para pintar botões)
  let myStatus = "offline";

  // 🔊 som de nova mensagem
  const soundMsg = new Audio("/static/chat_interno/sounds/msg.mp3");
  soundMsg.volume = 0.6;

  function unlockAudioOnce() {
    document.addEventListener("click", () => {
      soundMsg.play().then(() => {
        soundMsg.pause();
        soundMsg.currentTime = 0;
      }).catch(() => {});
    }, { once: true });
  }

  function playNewMessageSound() {
    try {
      soundMsg.currentTime = 0;
      soundMsg.play().catch(() => {});
    } catch {}
  }

  function getCookie(name) {
    const v = `; ${document.cookie}`;
    const parts = v.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function csrf() {
    return getCookie("csrftoken");
  }

  async function apiGet(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    return await r.json();
  }

  async function apiPost(url, formData) {
    const r = await fetch(url, {
      method: "POST",
      body: formData,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf() },
    });
    return await r.json().catch(() => ({}));
  }

  async function doPing() {
    const fd = new FormData();
    await apiPost("/chat/ping/", fd);
  }

  function paintStatusButtons() {
    const box = document.querySelector(".chat-status-box");
    if (!box) return;

    box.querySelectorAll("button.status").forEach(btn => {
      const st = (btn.dataset.status || "").toLowerCase();
      if (st === myStatus) btn.classList.add("active");
      else btn.classList.remove("active");
    });
  }

  async function setStatus(status) {
    const fd = new FormData();
    fd.append("status", status);

    const data = await apiPost("/chat/api/status/", fd);

    if (data?.error) {
      alert(data.error);
      return;
    }

    myStatus = data.status || status || "offline";
    paintStatusButtons();

    // ✅ reflete na lista na hora
    await loadContacts();
  }

  async function refreshUnreadBadge() {
    const badge = document.getElementById("chatUnreadBadge");
    if (!badge) return;

    const data = await apiGet("/chat/unread_total/");
    const count = Number(data.count || 0);

    if (count > lastUnreadTotal && !currentOtherId) {
      playNewMessageSound();
    }

    lastUnreadTotal = count;

    if (count > 0) {
      badge.style.display = "";
      badge.textContent = String(count);
    } else {
      badge.style.display = "none";
      badge.textContent = "0";
    }
  }

  async function markRead(otherId) {
    if (!otherId) return;
    const fd = new FormData();
    await apiPost(`/chat/mark_read/${otherId}/`, fd);
    await refreshUnreadBadge();
  }

  function sortContacts(items) {
    const weight = (st) => {
      if (st === "online") return 2;
      if (st === "ausente") return 1;
      return 0;
    };

    return (items || []).slice().sort((a, b) => {
      const aw = weight(a.status);
      const bw = weight(b.status);
      if (aw !== bw) return bw - aw;

      const an = (a.nome || a.username || "").toLowerCase();
      const bn = (b.nome || b.username || "").toLowerCase();
      return an.localeCompare(bn);
    });
  }

  async function loadContacts() {
    const data = await apiGet("/chat/contacts/");
    const list = document.getElementById("chatUserList");
    if (!list) return;

    canExport = !!data.can_export;

    if (data.my_status) {
      myStatus = data.my_status;
      paintStatusButtons();
    }

    list.innerHTML = "";
    const items = sortContacts(data.items || []);

    if (items.length === 0) {
      list.innerHTML = `<div class="text-secondary small">Nenhum contato disponível para você.</div>`;
      return;
    }

    items.forEach((u) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "list-group-item list-group-item-action";
      btn.dataset.userId = u.id;
      const nm = (u.nome || u.username);
      btn.onclick = () => open(u.id, nm);

      const statusTxt =
        u.status === "online" ? "🟢 Online" :
        (u.status === "ausente" ? "🟡 Ausente" : "⚪ Offline");

      btn.innerHTML = `
        <div class="fw-semibold">${escapeHtml(u.nome || u.username)}</div>
        <div class="small text-secondary">
          ${statusTxt}
          ${u.unread ? ` • <b>${u.unread}</b> nova(s)` : ""}
        </div>
      `;

      if (Number(u.id) === Number(currentOtherId)) btn.classList.add("active");
      list.appendChild(btn);
    });

    // tenta pintar botões com base em algo que já sabemos
    paintStatusButtons();
  }

  function enableConversationUI(on) {
    const ids = ["chatInput", "chatSendBtn", "chatSearchMsg", "chatSearchBtn", "chatEmojiBtn", "chatImgBtn"];
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = !on;
    });

    const exportBtn = document.getElementById("chatExportBtn");
    if (exportBtn) {
      exportBtn.style.display = on && canExport ? "" : "none";
    }
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

  async function open(otherId, otherName = null) {
    currentOtherId = otherId;

    suppressHistorySound = true;
    lastRenderedLastId = 0;
    lastSoundId = 0;

    const otherHidden = document.getElementById("chatOtherId");
    if (otherHidden) otherHidden.value = otherId;

    enableConversationUI(true);

    const hint = document.getElementById("chatHint");
    if (hint) hint.textContent = otherName ? `Conversa com: ${otherName}` : "Conversa aberta.";

    const head = document.getElementById("chatConvHead");
    if (head) head.classList.add("active");

    setActiveContact(otherId);

    await doPing();
    await loadContacts();
    await loadHistory(true);

    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => loadHistory(false), 4000);
  }

  async function loadHistory(forceScroll) {
    if (!currentOtherId) return;
    if (historyLoading) return;
    historyLoading = true;

    try {
      const data = await apiGet(`/chat/history/${currentOtherId}/`);
      if (data?.error) return;

      const box = document.getElementById("chatMsgs");
      if (!box) return;

      const items = data.items || [];
      const lastMsg = items.length ? items[items.length - 1] : null;
      const lastId = lastMsg ? Number(lastMsg.id) : 0;

      if (lastId && lastId === lastRenderedLastId && !forceScroll) {
        return;
      }

      box.innerHTML = "";
      items.forEach((m) => {
        const wrap = document.createElement("div");
        wrap.className = `mb-2 d-flex ${m.is_me ? "justify-content-end" : "justify-content-start"}`;

        const bubble = document.createElement("div");
        bubble.className = `chat-bubble ${m.is_me ? "mine" : "theirs"}`;

        bubble.innerHTML = `
          <div class="meta">${m.is_me ? "Você" : "Ele"} • ${formatDate(m.criado_em)}</div>
          ${m.texto ? `<div class="body">${escapeHtml(m.texto)}</div>` : ""}
        `;

        if (m.imagem_url) {
          const img = document.createElement("img");
          img.className = "chat-img";
          img.src = m.imagem_url;
          img.alt = "imagem";
          bubble.appendChild(img);
        }

        wrap.appendChild(bubble);
        box.appendChild(wrap);
      });

      if (forceScroll) box.scrollTop = box.scrollHeight;

      if (lastId && lastId !== lastRenderedLastId) {
        if (suppressHistorySound) {
          lastSoundId = lastId;
          lastRenderedLastId = lastId;
          suppressHistorySound = false;

          const now = Date.now();
          if (now - lastMarkAt > 1500) {
            lastMarkAt = now;
            await markRead(currentOtherId);
          }
          await loadContacts();
          return;
        }

        if (lastMsg && !lastMsg.is_me && lastId !== lastSoundId) {
          lastSoundId = lastId;
          playNewMessageSound();
        }

        lastRenderedLastId = lastId;

        const now = Date.now();
        if (now - lastMarkAt > 1500) {
          lastMarkAt = now;
          await markRead(currentOtherId);
        }

        await loadContacts();
      }
    } finally {
      historyLoading = false;
    }
  }

  async function send() {
    if (sending) return;
    sending = true;

    try {
      const input = document.getElementById("chatInput");
      const file = document.getElementById("chatImg");
      if (!input) return;

      const texto = (input.value || "").trim();
      const otherId = currentOtherId || Number(document.getElementById("chatOtherId")?.value || 0);
      if (!otherId) return;

      const hasImage = file && file.files && file.files.length > 0;
      if (!texto && !hasImage) return;

      await doPing();

      const fd = new FormData();
      if (texto) fd.append("texto", texto);
      if (hasImage) fd.append("imagem", file.files[0]);

      const data = await apiPost(`/chat/send/${otherId}/`, fd);
      if (data.error) {
        alert(data.error);
        return;
      }

      input.value = "";
      if (file) file.value = "";

      await loadHistory(true);
    } finally {
      sending = false;
    }
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

    if (sendBtn) sendBtn.addEventListener("click", (e) => {
      e.preventDefault();
      send();
    });

    if (exportBtn) exportBtn.addEventListener("click", (e) => {
      e.preventDefault();

      const meId = document.getElementById("chatMeId")?.value;
      if (!meId) return;

      let u1 = meId;
      let u2 = currentOtherId;
      if (!u2) return;

      if (canExport) {
        const ask = prompt(
          "Exportar histórico.\n\nDigite dois usuários (ID ou username) separados por vírgula, ou deixe vazio para exportar a conversa atual.\nEx: hudson,gabriel"
        );
        if (ask && ask.includes(",")) {
          const parts = ask.split(",").map(s => s.trim()).filter(Boolean);
          if (parts.length >= 2) { u1 = parts[0]; u2 = parts[1]; }
        }
      }

      const url = `/chat/export/?u1=${encodeURIComponent(u1)}&u2=${encodeURIComponent(u2)}`;
      window.open(url, "_blank");
    });

    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          send();
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

    if (imgBtn && imgIn) {
      imgBtn.addEventListener("click", () => imgIn.click());
    }
  }

  async function start() {
    bindUIOnce();
    unlockAudioOnce();

    enableConversationUI(false);

    await doPing();
    await loadContacts();
    await refreshUnreadBadge();

    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(() => doPing().catch(() => {}), 30000);

    setInterval(() => {
      refreshUnreadBadge().catch(() => {});
    }, 4000);

    // ✅ pinta botões ao iniciar
    paintStatusButtons();
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatDate(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch {
      return iso;
    }
  }

  // ✅ EXPORTA TUDO QUE O HTML PRECISA
  return { start, open, send, setStatus };
})();