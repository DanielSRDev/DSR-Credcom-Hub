window.ChatUI = (() => {
  let currentOtherId = null;
  let pollTimer = null;
  let pingTimer = null;
  let lastMsgId = 0;

  function getCSRFToken() {
    const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : null;
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
      headers: { "X-CSRFToken": getCSRFToken() || "" },
    });
    return await r.json();
  }

  async function loadContacts() {
    // pega contatos conforme regra (services.allowed_contacts)
    const data = await apiGet("/chat/contacts/");
    const list = document.getElementById("chatUserList");
    if (!list) return;

    list.innerHTML = "";
    if (!data.items || data.items.length === 0) {
      list.innerHTML = `<div class="text-secondary small">Nenhum contato disponível para você.</div>`;
      return;
    }

    data.items.forEach(u => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "list-group-item list-group-item-action";
      btn.onclick = () => open(u.id);

      btn.innerHTML = `
        <div class="fw-semibold">${escapeHtml(u.nome || u.username)}</div>
        <div class="small text-secondary">
          ${u.online ? "🟢 Online" : "⚪ Offline"}
          ${u.unread ? ` • <b>${u.unread}</b> nova(s)` : ""}
        </div>
      `;
      list.appendChild(btn);
    });
  }

  async function open(otherId) {
    currentOtherId = otherId;
    lastMsgId = 0;

    // se você tiver área da conversa em um div, define hidden
    const otherHidden = document.getElementById("chatOtherId");
    if (otherHidden) otherHidden.value = otherId;

    await loadHistory(true);

    // reinicia polling da conversa
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => loadHistory(false), 2000); // 2s
  }

  async function loadHistory(forceScroll) {
    if (!currentOtherId) return;

    const data = await apiGet(`/chat/history/${currentOtherId}/`);
    if (data.error) return;

    const box = document.getElementById("chatMsgs");
    if (!box) return;

    // render simples (você pode adaptar pro seu layout)
    box.innerHTML = "";
    (data.items || []).forEach(m => {
      if (m.id > lastMsgId) lastMsgId = m.id;

      const wrap = document.createElement("div");
      wrap.className = `mb-2 d-flex ${m.is_me ? "justify-content-end" : "justify-content-start"}`;
      wrap.innerHTML = `
        <div class="p-2 rounded shadow-sm ${m.is_me ? "bg-primary text-white" : "bg-white"}"
             style="max-width:75%; white-space:pre-wrap;">
          <div class="small opacity-75">${m.is_me ? "Você" : "Ele"} • ${formatDate(m.criado_em)}</div>
          <div>${escapeHtml(m.texto)}</div>
        </div>
      `;
      box.appendChild(wrap);
    });

    if (forceScroll) box.scrollTop = box.scrollHeight;

    // atualiza badges/online também
    await loadContacts();
  }

  async function send(ev) {
    ev.preventDefault();
    const input = document.getElementById("chatInput");
    if (!input) return;

    const texto = (input.value || "").trim();
    if (!texto) return;

    const otherId = currentOtherId || Number(document.getElementById("chatOtherId")?.value || 0);
    if (!otherId) return;

    const fd = new FormData();
    fd.append("texto", texto);

    const data = await apiPost(`/chat/send/${otherId}/`, fd);
    if (data.error) {
      alert(data.error);
      return;
    }

    input.value = "";
    await loadHistory(true);
  }

async function start() {
  // espera o DOM do widget existir
  const waitForList = () => new Promise(resolve => {
    const i = setInterval(() => {
      if (document.getElementById("chatUserList")) {
        clearInterval(i);
        resolve();
      }
    }, 200);
  });

  await waitForList();

  await loadContacts();

  // ping online
  if (pingTimer) clearInterval(pingTimer);
  pingTimer = setInterval(() => {
    const fd = new FormData();
    apiPost("/chat/ping/", fd).catch(() => {});
  }, 25000);
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

  return { start, open, send };
})();