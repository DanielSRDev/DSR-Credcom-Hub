window.ChatUI = (() => {
  let currentOtherId = null;
  let pollTimer = null;
  let pingTimer = null;
  let canExport = false;

  let bound = false;      // ✅ garante 1 bind só
  let sending = false;    // ✅ trava duplo envio

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
  }

  async function markRead(otherId) {
    if (!otherId) return;
    const fd = new FormData();
    await apiPost(`/chat/mark_read/${otherId}/`, fd);
    await refreshUnreadBadge();
  }

  function sortContacts(items) {
    return (items || []).slice().sort((a, b) => {
      const ao = a.online ? 1 : 0;
      const bo = b.online ? 1 : 0;
      if (ao !== bo) return bo - ao;
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

      btn.innerHTML = `
        <div class="fw-semibold">${escapeHtml(u.nome || u.username)}</div>
        <div class="small text-secondary">
          ${u.online ? "🟢 Online" : "⚪ Offline"}
          ${u.unread ? ` • <b>${u.unread}</b> nova(s)` : ""}
        </div>
      `;
      if (Number(u.id) === Number(currentOtherId)) btn.classList.add("active");
      list.appendChild(btn);
    });
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
  function setActiveContact(otherId){
    const list = document.getElementById("chatUserList");
    if (!list) return;
    [...list.querySelectorAll(".list-group-item")].forEach((btn) => {
      const id = Number(btn.dataset.userId || 0);
      if (id && id === Number(otherId)) btn.classList.add("active");
      else btn.classList.remove("active");
    });
  }



  async function open(otherId, otherName=null) {
    currentOtherId = otherId;

    const otherHidden = document.getElementById("chatOtherId");
    if (otherHidden) otherHidden.value = otherId;

    enableConversationUI(true);

    const hint = document.getElementById("chatHint");
    if (hint) hint.textContent = otherName ? `Conversa com: ${otherName}` : "Conversa aberta.";
    const head = document.getElementById("chatConvHead");
    if (head) head.classList.add("active");
    const badge = document.getElementById("chatSelectedBadge");
    if (badge) {
      if (otherName) { badge.textContent = otherName; badge.classList.remove("d-none"); }
      else { badge.classList.add("d-none"); }
    }
    setActiveContact(otherId);

    await doPing();
    await markRead(otherId);

    await loadContacts();
    await loadHistory(true);

    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => loadHistory(false), 2000);
  }

  async function loadHistory(forceScroll) {
    if (!currentOtherId) return;

    const data = await apiGet(`/chat/history/${currentOtherId}/`);
    if (data.error) return;

    const box = document.getElementById("chatMsgs");
    if (!box) return;

    box.innerHTML = "";
    (data.items || []).forEach((m) => {
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

    await markRead(currentOtherId);
    await loadContacts();
  }

  async function send() {
    if (sending) return;          // ✅ bloqueia clique duplo / listener duplicado
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
    if (bound) return;   // ✅ aqui é o segredo
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
      // Se for admin/staff/coordenacao, pode exportar qualquer par via prompt.
      // Caso contrário, exporta a conversa atual (eu x selecionado).
      const meId = document.getElementById("chatMeId")?.value;
      if (!meId) return;
      let u1 = meId;
      let u2 = currentOtherId;
      if (!u2) return;
      if (canExport) {
        const ask = prompt("Exportar histórico.\n\nDigite dois usuários (ID ou username) separados por vírgula, ou deixe vazio para exportar a conversa atual.\nEx: hudson,gabriel");
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
        const pick = prompt("Digite um emoji (ex: 😀😎🔥✅😃😄😁😆😅🤣😂🙂🙃😉😊😇🥰😍🤩😘😗☺️😚😙😋😛😜🤪😝🤑🤗🤭🤫🤔🤐🤨😐😑😶😶😏😒🙄😬😮‍💨🤥🫨🙂‍↔️🙂‍↕️😌😔😪🤤😴☹️😮😯😲😳🥺😦😧😨😰😥😢😭😱😖😣😞😓😩😫🥱😤😡😠🤬😈👿💀☠️💩🤡👹👺👻👽👾🤖😺😸😹😻😼😽🙀😿😾🙈🙉🙊💋💯💢💥💫💦💨🕳️💤👋🤚🖐️✋🖖👌🤏✌️🤞🤟🤘🤙👈👉👆🖕👇☝️✍️💅🤳💪🦾🦿🦵🦶👂🦻👃🧠🦷🦴👀👁️👅👄👶🧒👦👧🧑👱👨🧔👨‍🦰👨‍🦱👨‍🦳👨‍🦲👩👩‍🦰🧑‍🦰👩‍🦱🧑‍🦱👩‍🦳🧑‍🦳👩‍🦲🧑‍🦲👱‍♀️👱‍♂️🧓👴👵🙍🙍‍♂️🙍‍♀️🙎🙎‍♂️🙎‍♀️🙅🙅‍♂️🙅‍♀️🙆🙆‍♂️🙆‍♀️💁💁‍♂️💁‍♀️🙋🙋‍♂️🙋‍♀️🧏🧏‍♂️🧏‍♀️🙇🙇‍♂️🙇‍♀️🤦🤦‍♂️🤦‍♀️🤷🤷‍♂️🤷‍♀️🫅🤴👸👳👲🧕🤵👰🤰🤱👩‍🍼👨‍🍼🧑‍🍼💃🕺🛀🛌🧑‍🤝‍🧑👭👫👬💏👩‍❤️‍💋‍👨👨‍❤️‍💋‍👨👩‍❤️‍💋‍👩💑👩‍❤️‍👨👨‍❤️‍👨👩‍❤️‍👩💌💘💝💖💗💓💞💕💟❣️💔❤️‍🔥❤️‍🩹❤️):", "😀");
        if (pick) input.value = (input.value || "") + pick;
        input.focus();
      });
    }

    if (imgBtn && imgIn) {
      imgBtn.addEventListener("click", () => imgIn.click());
    }
  }

  async function start() {
    // ✅ bind só uma vez (mesmo abrindo/fechando painel)
    bindUIOnce();

    enableConversationUI(false);

    await doPing();
    await loadContacts();
    await refreshUnreadBadge();

    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(() => doPing().catch(() => {}), 8000);
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