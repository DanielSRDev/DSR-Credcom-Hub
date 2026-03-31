(() => {
    let conversaAtual = null;
    let conversasCache = [];
    let pollConversasTimer = null;
    let pollStatusTimer = null;
    let currentTargetUserId = null;
    let currentTargetUsername = null;
    let novaConversaModal = null;
    let carregandoMensagens = false;
    let enviandoMensagem = false;
    let ultimoHashMensagens = null;
    let mediaRecorder = null;
    let audioChunks = [];
    let gravandoAudio = false;
    let streamAudio = null; 



    function getCsrfToken() {
        const input = document.querySelector("[name=csrfmiddlewaretoken]");
        if (input) return input.value;

        const cookie = document.cookie
            .split("; ")
            .find((row) => row.startsWith("csrftoken="));
        return cookie ? cookie.split("=")[1] : "";
    }

    function headersJson() {
        return {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
            "X-Requested-With": "XMLHttpRequest",
        };
    }

    function headersForm() {
        return {
            "X-CSRFToken": getCsrfToken(),
            "X-Requested-With": "XMLHttpRequest",
        };
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function normalizarNumero(numero) {
        return String(numero ?? "").replace(/\D/g, "");
    }

    function formatarDataHora(valor) {
        if (!valor) return "";
        try {
            const data = new Date(valor);
            if (Number.isNaN(data.getTime())) return String(valor);
            return data.toLocaleString("pt-BR", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
            });
        } catch {
            return String(valor);
        }
    }

    function toast(msg) {
        alert(msg);
    }

    function ajustarAlturaZapPage() {
        const zapPage = document.querySelector(".zap-page");
        if (!zapPage) return;

        const rect = zapPage.getBoundingClientRect();
        const topOffset = rect.top;
        document.documentElement.style.setProperty("--zap-top-offset", `${topOffset}px`);
    }

    function getPageTargetId() {
        const page = document.querySelector(".zap-page");
        return page?.dataset?.currentTargetId || "";
    }

    function getPageTargetUsername() {
        const page = document.querySelector(".zap-page");
        return page?.dataset?.currentTargetUsername || "";
    }

    function resolveInitialTargetId() {
        const url = new URL(window.location.href);
        const asUser = url.searchParams.get("as_user");
        if (asUser) return asUser;

        const select = document.getElementById("monitor-target");
        if (select && select.value) return select.value;

        return getPageTargetId();
    }

    function setActiveTargetLabel(username) {
        currentTargetUsername = username || "";
        const targetLabel = document.getElementById("target-user-label");
        if (targetLabel) {
            targetLabel.textContent = username || "-";
        }
    }

    function buildUrl(path) {
        const url = new URL(path, window.location.origin);
        if (currentTargetUserId) {
            url.searchParams.set("as_user", currentTargetUserId);
        }
        return url.toString();
    }

    async function fetchJson(url, options = {}) {
        const response = await fetch(url, options);
        let data = {};
        try {
            data = await response.json();
        } catch {
            data = {};
        }

        if (!response.ok) {
            const msg =
                data?.erro ||
                data?.detail ||
                data?.error ||
                data?.message ||
                `Erro HTTP ${response.status}`;
            throw new Error(msg);
        }

        return data;
    }

    function getStatusBadge() {
        return document.getElementById("status-badge");
    }

    function setStatusBadge(statusText, type = "") {
        const badge = getStatusBadge();
        if (!badge) return;

        badge.classList.remove("connected", "warning", "danger");
        badge.textContent = statusText || "Desconhecido";

        if (type) {
            badge.classList.add(type);
        }
    }

    function setFormularioHabilitado(habilitado) {
        const inputMensagem = document.getElementById("input-mensagem");
        const btnEnviar = document.getElementById("btn-enviar");
        const btnAnexo = document.getElementById("btn-anexo");
        const btnAudio = document.getElementById("btn-audio");

        if (inputMensagem) inputMensagem.disabled = !habilitado;
        if (btnEnviar) btnEnviar.disabled = !habilitado;
        if (btnAnexo) btnAnexo.disabled = !habilitado;
        if (btnAudio) btnAudio.disabled = !habilitado;
    }

    async function carregarStatus() {
        try {
            const data = await fetchJson(buildUrl("/zapmsg/status/"));

            const status = String(data?.status || "").toLowerCase();
            const conectado =
                !!data?.conectado ||
                !!data?.connected ||
                status === "connected" ||
                status === "ready" ||
                status === "conectado";

            const qr = data?.qr_code || data?.qr || "";

            const qrPanel = document.getElementById("zap-qr-panel");
            const qrContainer = document.getElementById("qr-container");

            const btnConnect = document.getElementById("btn-connect");
            const btnDisconnect = document.getElementById("btn-disconnect");

            if (conectado) {
                setStatusBadge("Conectado", "connected");
                if (btnConnect) btnConnect.classList.add("d-none");
                if (btnDisconnect) btnDisconnect.classList.remove("d-none");
            } else if (qr) {
                setStatusBadge("Aguardando QR", "warning");
                if (btnConnect) btnConnect.classList.remove("d-none");
                if (btnDisconnect) btnDisconnect.classList.add("d-none");
            } else if (
                status === "connecting" ||
                status === "loading" ||
                status === "starting" ||
                status === "conectando"
            ) {
                setStatusBadge("Conectando...", "warning");
                if (btnConnect) btnConnect.classList.remove("d-none");
                if (btnDisconnect) btnDisconnect.classList.add("d-none");
            } else {
                setStatusBadge("Desconectado", "danger");
                if (btnConnect) btnConnect.classList.remove("d-none");
                if (btnDisconnect) btnDisconnect.classList.add("d-none");
            }

            if (qrPanel && qrContainer) {
                if (qr) {
                    qrPanel.classList.remove("d-none");
                    qrContainer.innerHTML = `<img src="${qr}" alt="QR Code WhatsApp">`;
                } else {
                    qrPanel.classList.add("d-none");
                    qrContainer.innerHTML = `<p class="text-muted mb-0">Nenhum QR disponível.</p>`;
                }
            }
        } catch (error) {
            console.error("Erro ao carregar status:", error);
            setStatusBadge("Desconectado", "danger");
        }
    }

    async function conectarWhatsapp() {
        const btnConnect = document.getElementById("btn-connect");
        const btnDisconnect = document.getElementById("btn-disconnect");

        try {
            if (btnConnect) btnConnect.disabled = true;

            setStatusBadge("Conectando...", "warning");

            await fetchJson(buildUrl("/zapmsg/iniciar/"), {
                method: "POST",
                headers: headersJson(),
                body: JSON.stringify({}),
            });

            let tentativas = 0;
            let conectado = false;

            while (tentativas < 12) {
                tentativas += 1;

                await new Promise((resolve) => setTimeout(resolve, 1500));

                try {
                    const data = await fetchJson(buildUrl("/zapmsg/status/"));
                    const status = String(data?.status || "").toLowerCase();

                    const isConnected =
                        !!data?.conectado ||
                        !!data?.connected ||
                        status === "connected" ||
                        status === "ready" ||
                        status === "conectado";

                    const hasQr = !!(data?.qr_code || data?.qr);

                    if (isConnected) {
                        setStatusBadge("Conectado", "connected");
                        if (btnConnect) btnConnect.classList.add("d-none");
                        if (btnDisconnect) btnDisconnect.classList.remove("d-none");
                        conectado = true;
                        break;
                    }

                    if (hasQr) {
                        setStatusBadge("Aguardando QR", "warning");
                    } else {
                        setStatusBadge("Conectando...", "warning");
                    }
                } catch (err) {
                    console.error("Erro ao consultar status durante conexão:", err);
                }
            }

            if (!conectado) {
                await carregarStatus();
            }
        } catch (error) {
            console.error(error);
            setStatusBadge("Erro ao conectar", "danger");
            toast(`Erro ao conectar: ${error.message}`);
        } finally {
            if (btnConnect) btnConnect.disabled = false;
        }
    }

    async function desconectarWhatsapp() {
        try {
            await fetchJson(buildUrl("/zapmsg/desconectar/"), {
                method: "POST",
                headers: headersJson(),
                body: JSON.stringify({}),
            });

            await carregarStatus();
            toast("Conta desconectada.");
        } catch (error) {
            console.error(error);
            toast(`Erro ao desconectar: ${error.message}`);
        }
    }

    function conversationPreview(item) {
        return (
            item?.ultima_mensagem_preview ||
            item?.ultima_mensagem ||
            item?.last_message_preview ||
            item?.last_message ||
            item?.ultimo_texto ||
            item?.preview ||
            ""
        );
    }

    function conversationTime(item) {
        return (
            item?.ultima_mensagem_em ||
            item?.updated_at ||
            item?.last_message_at ||
            item?.data_ultima_mensagem ||
            item?.timestamp ||
            ""
        );
    }

    function conversationName(item) {
        return (
            item?.nome_exibicao ||
            item?.nome ||
            item?.display_name ||
            item?.contato_nome ||
            item?.numero ||
            item?.wa_id ||
            `Conversa ${item?.id ?? ""}`
        );
    }

    function conversationNumber(item) {
        return (
            item?.numero ||
            item?.telefone ||
            item?.wa_id ||
            item?.contact_number ||
            ""
        );
    }

    function renderConversas(lista) {
        const container = document.getElementById("lista-conversas");
        const busca = document.getElementById("busca-conversa");
        if (!container) return;

        const termo = (busca?.value || "").trim().toLowerCase();

        const filtradas = (lista || []).filter((item) => {
            if (!termo) return true;
            const nome = conversationName(item).toLowerCase();
            const numero = conversationNumber(item).toLowerCase();
            const preview = conversationPreview(item).toLowerCase();
            return nome.includes(termo) || numero.includes(termo) || preview.includes(termo);
        });

        if (!filtradas.length) {
            container.innerHTML = `
                <div class="p-3 text-muted small">
                    Nenhuma conversa encontrada.
                </div>
            `;
            return;
        }

        container.innerHTML = filtradas
            .map((item) => {
                const active = Number(item.id) === Number(conversaAtual?.id);
                return `
                    <button class="zap-conversation-item ${active ? "active" : ""}" data-id="${item.id}" type="button">
                        <div class="zap-conversation-item-top">
                            <strong>${escapeHtml(conversationName(item))}</strong>
                            <small>${escapeHtml(formatarDataHora(conversationTime(item)))}</small>
                        </div>
                        <div class="zap-conversation-item-bottom">
                            <span>${escapeHtml(conversationPreview(item))}</span>
                        </div>
                    </button>
                `;
            })
            .join("");

        container.querySelectorAll(".zap-conversation-item").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = Number(btn.dataset.id);
                const item = conversasCache.find((x) => Number(x.id) === id);
                if (item) {
                    abrirConversa(item);
                }
            });
        });
    }

    function hashMensagens(mensagens) {
        return JSON.stringify(
            (mensagens || []).map((m) => [
                m?.id,
                m?.texto || m?.body || "",
                m?.tipo || m?.message_type || "",
                m?.media_url || m?.arquivo_url || "",
                m?.direction || (m?.enviado_por_mim ?? m?.from_me ?? false),
                m?.enviada_em || m?.criado_em || m?.created_at || "",
            ])
        );
    }

    function getMessageText(msg) {
        return msg?.texto || msg?.body || msg?.caption || "";
    }

    function getMessageType(msg) {
        const tipo = msg?.tipo || msg?.message_type || "";

        if (tipo === "texto") return "text";
        if (tipo === "imagem") return "image";
        if (tipo === "documento") return "document";
        if (tipo === "arquivo") return "file";
        if (tipo === "audio") return "audio";
        if (tipo === "video") return "video";

        if (msg?.mimetype?.startsWith("image/")) return "image";
        if (msg?.mimetype?.startsWith("audio/")) return "audio";
        if (msg?.mimetype?.startsWith("video/")) return "video";
        if (msg?.arquivo_url || msg?.media_url) return "document";

        return "text";
    }

    function getMessageFileUrl(msg) {
        return msg?.media_url || msg?.arquivo_url || msg?.arquivo || msg?.file_url || "";
    }

    function getMessageFileName(msg) {
        return msg?.filename || msg?.nome_arquivo || msg?.file_name || msg?.arquivo_nome || "arquivo";
    }

    function isFromMe(msg) {
        if (msg?.direction) {
            return msg.direction === "out";
        }
        return !!(msg?.enviado_por_mim ?? msg?.from_me ?? msg?.saida ?? false);
    }

    function getMessageDate(msg) {
        return (
            msg?.enviada_em ||
            msg?.criado_em ||
            msg?.created_at ||
            msg?.timestamp ||
            msg?.data_envio ||
            ""
        );
    }

    function getMessageStatus(msg) {
        return msg?.status_envio || msg?.status || msg?.delivery_status || "";
    }

    function renderMensagemConteudo(msg) {
        const texto = getMessageText(msg);
        const tipo = getMessageType(msg);
        const arquivoUrl = getMessageFileUrl(msg);
        const nomeArquivo = getMessageFileName(msg);

        let html = "";

        if (tipo === "image" && arquivoUrl) {
            html += `<img src="${arquivoUrl}" alt="${escapeHtml(nomeArquivo)}" class="zap-media-image">`;
        } else if (tipo === "audio" && arquivoUrl) {
            html += `<audio controls class="zap-media-audio" src="${arquivoUrl}"></audio>`;
        } else if (tipo === "video" && arquivoUrl) {
            html += `<video controls class="zap-media-video" src="${arquivoUrl}"></video>`;
        } else if ((tipo === "document" || tipo === "file") && arquivoUrl) {
            html += `
                <div class="mb-2">
                    <a class="zap-file-link" href="${arquivoUrl}" target="_blank" rel="noopener noreferrer">
                        📄 ${escapeHtml(nomeArquivo)}
                    </a>
                </div>
            `;
        }

        if (texto) {
            html += `<div class="zap-msg-text">${escapeHtml(texto)}</div>`;
        }

        if (!html) {
            html = `<div class="zap-msg-text text-muted">Mensagem sem conteúdo visível.</div>`;
        }

        return html;
    }

    function renderMensagens(mensagens) {
        const box = document.getElementById("mensagens-box");
        if (!box) return;

        if (!mensagens || !mensagens.length) {
            box.innerHTML = `
                <div class="zap-empty-state">
                    <h5>Nenhuma mensagem nesta conversa</h5>
                    <p>Envie algo para começar.</p>
                </div>
            `;
            return;
        }

        box.innerHTML = mensagens
            .map((msg) => {
                const out = isFromMe(msg);
                const data = formatarDataHora(getMessageDate(msg));
                const status = getMessageStatus(msg);

                return `
                    <div class="zap-msg-row ${out ? "out" : "in"}">
                        <div class="zap-msg-bubble">
                            ${renderMensagemConteudo(msg)}
                            <div class="zap-msg-meta">
                                <span>${escapeHtml(data)}</span>
                                ${out && status ? `<span>${escapeHtml(status)}</span>` : ""}
                            </div>
                        </div>
                    </div>
                `;
            })
            .join("");

        box.scrollTop = box.scrollHeight;
    }

    function setChatHeader(conversa) {
        const nome = document.getElementById("chat-nome");
        const numero = document.getElementById("chat-numero");
        const avatar = document.getElementById("chat-avatar");
        const btnExcluir = document.getElementById("btn-excluir-conversa");

        if (!conversa) {
            if (nome) nome.textContent = "Selecione uma conversa";
            if (numero) numero.textContent = "Nenhuma conversa aberta";
            if (avatar) avatar.textContent = "?";
            if (btnExcluir) btnExcluir.classList.add("d-none");
            setFormularioHabilitado(false);
            return;
        }

        const nomeTexto = conversationName(conversa);
        const numeroTexto = conversationNumber(conversa);
        if (nome) nome.textContent = nomeTexto;
        if (numero) numero.textContent = numeroTexto || "Sem número";
        if (avatar) avatar.textContent = (nomeTexto || "?").charAt(0).toUpperCase();
        if (btnExcluir) btnExcluir.classList.remove("d-none");

        setFormularioHabilitado(true);
    }

    async function apiMensagens(conversaId) {
        return fetchJson(buildUrl(`/zapmsg/api/conversas/${conversaId}/mensagens/`));
    }

    async function carregarMensagensConversa(conversaId, force = false) {
        if (!conversaId || carregandoMensagens) return;

        carregandoMensagens = true;
        try {
            const data = await apiMensagens(conversaId);
            const mensagens = data?.mensagens || data?.results || data || [];

            const novoHash = hashMensagens(mensagens);
            if (force || novoHash !== ultimoHashMensagens) {
                renderMensagens(mensagens);
                ultimoHashMensagens = novoHash;
            }

            await marcarConversaLida(conversaId);
        } catch (error) {
            console.error("Erro ao carregar mensagens:", error);
        } finally {
            carregandoMensagens = false;
        }
    }

    async function abrirConversa(conversa) {
        if (!conversa) return;

        conversaAtual = conversa;
        ultimoHashMensagens = null;

        setChatHeader(conversa);
        renderConversas(conversasCache);
        await carregarMensagensConversa(conversa.id, true);
    }

    async function marcarConversaLida(conversaId) {
        try {
            await fetchJson(buildUrl(`/zapmsg/api/conversas/${conversaId}/marcar-lida/`), {
                method: "POST",
                headers: headersJson(),
                body: JSON.stringify({}),
            });
        } catch (error) {
            console.error("Erro ao marcar conversa como lida:", error);
        }
    }

    async function carregarConversas({ preserveSelection = true, openFirstIfNeeded = false } = {}) {
        try {
            const data = await fetchJson(buildUrl("/zapmsg/api/conversas/"));
            const lista = data?.conversas || data?.results || data || [];

            conversasCache = Array.isArray(lista) ? lista : [];
            renderConversas(conversasCache);

            if (!conversasCache.length) {
                conversaAtual = null;
                ultimoHashMensagens = null;
                setChatHeader(null);
                const box = document.getElementById("mensagens-box");
                if (box) {
                    box.innerHTML = `
                        <div class="zap-empty-state">
                            <h5>Seu WhatsApp dentro do sistema</h5>
                            <p>Escolha uma conversa na lateral para começar.</p>
                        </div>
                    `;
                }
                return;
            }

            if (preserveSelection && conversaAtual) {
                const atualizada = conversasCache.find((c) => Number(c.id) === Number(conversaAtual.id));
                if (atualizada) {
                    conversaAtual = atualizada;
                    renderConversas(conversasCache);
                    return;
                }
            }

            if (openFirstIfNeeded) {
                await abrirConversa(conversasCache[0]);
            }
        } catch (error) {
            console.error("Erro ao carregar conversas:", error);
        }
    }

    async function atualizarConversaAtualSilencioso() {
        if (!conversaAtual?.id) return;
        await carregarMensagensConversa(conversaAtual.id, false);
    }

    function clearFileInputs() {
        const inputArquivo = document.getElementById("input-arquivo");
        const inputAudio = document.getElementById("input-audio");
        const inputMensagem = document.getElementById("input-mensagem");

        if (inputArquivo) inputArquivo.value = "";
        if (inputAudio) inputAudio.value = "";
        if (inputMensagem) inputMensagem.placeholder = "Digite uma mensagem...";
    }

    function atualizarBotaoAudioUI() {
        const btnAudio = document.getElementById("btn-audio");
        const inputMensagem = document.getElementById("input-mensagem");

        if (!btnAudio) return;

        if (gravandoAudio) {
            btnAudio.classList.remove("btn-light");
            btnAudio.classList.add("btn-danger");
            btnAudio.textContent = "⏹";
            btnAudio.title = "Parar gravação";

            if (inputMensagem) {
                inputMensagem.placeholder = "Gravando áudio...";
            }
        } else {
            btnAudio.classList.remove("btn-danger");
            btnAudio.classList.add("btn-light");
            btnAudio.textContent = "🎤";
            btnAudio.title = "Gravar áudio";

            if (inputMensagem) {
                inputMensagem.placeholder = "Digite uma mensagem...";
            }
        }
    }

    async function iniciarGravacaoAudio() {
        if (gravandoAudio || enviandoMensagem) return;
        if (!conversaAtual?.id) return;

        try {
            streamAudio = await navigator.mediaDevices.getUserMedia({ audio: true });

            audioChunks = [];

            let options = {};
            if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
                options = { mimeType: "audio/webm;codecs=opus" };
            } else if (MediaRecorder.isTypeSupported("audio/webm")) {
                options = { mimeType: "audio/webm" };
            } else if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
                options = { mimeType: "audio/ogg;codecs=opus" };
            }

            mediaRecorder = new MediaRecorder(streamAudio, options);

            mediaRecorder.ondataavailable = (event) => {
                if (event.data && event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                try {
                    const mimeTypeFinal = mediaRecorder.mimeType || "audio/ogg;codecs=opus";
                    const audioBlob = new Blob(audioChunks, { type: mimeTypeFinal });

                    const extensao = mimeTypeFinal.includes("ogg") ? "ogg" : "webm";
                    const audioFile = new File(
                        [audioBlob],
                        `audio_${Date.now()}.${extensao}`,
                        { type: mimeTypeFinal }
                    );

                    await enviarArquivoAudioGravado(audioFile);
                } catch (error) {
                    console.error("Erro ao processar áudio gravado:", error);
                    toast(`Erro ao processar áudio: ${error.message}`);
                } finally {
                    if (streamAudio) {
                        streamAudio.getTracks().forEach((track) => track.stop());
                        streamAudio = null;
                    }

                    mediaRecorder = null;
                    audioChunks = [];
                    gravandoAudio = false;
                    atualizarBotaoAudioUI();
                }
            };

            mediaRecorder.start();
            gravandoAudio = true;
            atualizarBotaoAudioUI();
        } catch (error) {
            console.error("Erro ao iniciar gravação de áudio:", error);
            toast("Não foi possível acessar o microfone.");
        }
    }

    function pararGravacaoAudio() {
        if (!mediaRecorder || !gravandoAudio) return;

        if (mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
    }

    async function enviarArquivoAudioGravado(audioFile) {
        if (!conversaAtual?.id || enviandoMensagem) return;

        const input = document.getElementById("input-mensagem");
        const fileInput = document.getElementById("input-arquivo");
        const audioInput = document.getElementById("input-audio");
        const btnEnviar = document.getElementById("btn-enviar");
        const btnAnexo = document.getElementById("btn-anexo");
        const btnAudio = document.getElementById("btn-audio");

        const formData = new FormData();
        formData.append("texto", "");
        formData.append("arquivo", audioFile);

        enviandoMensagem = true;
        if (input) input.disabled = true;
        if (fileInput) fileInput.disabled = true;
        if (audioInput) audioInput.disabled = true;
        if (btnEnviar) btnEnviar.disabled = true;
        if (btnAnexo) btnAnexo.disabled = true;
        if (btnAudio) btnAudio.disabled = true;

        try {
            await fetchJson(buildUrl(`/zapmsg/api/conversas/${conversaAtual.id}/enviar/`), {
                method: "POST",
                headers: headersForm(),
                body: formData,
            });

            clearFileInputs();
            await carregarConversas({ preserveSelection: true, openFirstIfNeeded: false });
            await atualizarConversaAtualSilencioso();
        } catch (error) {
            console.error("Erro ao enviar áudio gravado:", error);
            toast(`Erro ao enviar áudio: ${error.message}`);
        } finally {
            enviandoMensagem = false;
            if (input) input.disabled = false;
            if (fileInput) fileInput.disabled = false;
            if (audioInput) audioInput.disabled = false;
            if (btnEnviar) btnEnviar.disabled = false;
            if (btnAnexo) btnAnexo.disabled = false;
            if (btnAudio) btnAudio.disabled = false;
            atualizarBotaoAudioUI();
        }
    }
    



    async function enviarMensagem(event) {
        event.preventDefault();

        if (!conversaAtual?.id || enviandoMensagem) return;

        const input = document.getElementById("input-mensagem");
        const fileInput = document.getElementById("input-arquivo");
        const audioInput = document.getElementById("input-audio");
        const btnEnviar = document.getElementById("btn-enviar");
        const btnAnexo = document.getElementById("btn-anexo");
        const btnAudio = document.getElementById("btn-audio");

        const texto = (input?.value || "").trim();
        const arquivo = fileInput?.files?.[0] || audioInput?.files?.[0];

        if (!texto && !arquivo) return;

        const formData = new FormData();
        formData.append("texto", texto);
        if (arquivo) {
            formData.append("arquivo", arquivo);
        }

        enviandoMensagem = true;
        if (input) input.disabled = true;
        if (fileInput) fileInput.disabled = true;
        if (audioInput) audioInput.disabled = true;
        if (btnEnviar) btnEnviar.disabled = true;
        if (btnAnexo) btnAnexo.disabled = true;
        if (btnAudio) btnAudio.disabled = true;

        try {
            await fetchJson(buildUrl(`/zapmsg/api/conversas/${conversaAtual.id}/enviar/`), {
                method: "POST",
                headers: headersForm(),
                body: formData,
            });

            if (input) input.value = "";
            clearFileInputs();

            await carregarConversas({ preserveSelection: true, openFirstIfNeeded: false });
            await atualizarConversaAtualSilencioso();
        } catch (error) {
            console.error("Erro ao enviar mensagem:", error);
            toast(`Erro ao enviar mensagem: ${error.message}`);
        } finally {
            enviandoMensagem = false;
            if (input) input.disabled = false;
            if (fileInput) fileInput.disabled = false;
            if (audioInput) audioInput.disabled = false;
            if (btnEnviar) btnEnviar.disabled = false;
            if (btnAnexo) btnAnexo.disabled = false;
            if (btnAudio) btnAudio.disabled = false;
        }
    }

    async function excluirConversaAtual() {
        if (!conversaAtual?.id) return;

        const ok = confirm("Deseja realmente excluir esta conversa?");
        if (!ok) return;

        try {
            await fetchJson(buildUrl(`/zapmsg/api/conversas/${conversaAtual.id}/excluir/`), {
                method: "POST",
                headers: headersJson(),
                body: JSON.stringify({}),
            });

            conversaAtual = null;
            ultimoHashMensagens = null;
            await carregarConversas({ preserveSelection: false, openFirstIfNeeded: true });
        } catch (error) {
            console.error("Erro ao excluir conversa:", error);
            toast(`Erro ao excluir conversa: ${error.message}`);
        }
    }

    async function criarNovaConversa(event) {
        event.preventDefault();

        const numeroInput = document.getElementById("nova-conversa-numero");
        const nomeInput = document.getElementById("nova-conversa-nome");

        const numero = normalizarNumero(numeroInput?.value || "");
        const nome = (nomeInput?.value || "").trim();

        if (!numero) {
            toast("Informe um número válido.");
            return;
        }

        try {
            const data = await fetchJson(buildUrl("/zapmsg/api/nova-conversa/"), {
                method: "POST",
                headers: headersJson(),
                body: JSON.stringify({
                    numero,
                    nome,
                }),
            });

            if (numeroInput) numeroInput.value = "";
            if (nomeInput) nomeInput.value = "";

            if (novaConversaModal) novaConversaModal.hide();

            await carregarConversas({ preserveSelection: false, openFirstIfNeeded: false });

            const criada =
                conversasCache.find((c) => Number(c.id) === Number(data?.conversa?.id)) ||
                conversasCache.find((c) => conversationNumber(c).includes(numero));

            if (criada) {
                await abrirConversa(criada);
            }
        } catch (error) {
            console.error("Erro ao criar nova conversa:", error);
            toast(`Erro ao criar conversa: ${error.message}`);
        }
    }

    function startPolling() {
        stopPolling();

        pollStatusTimer = setInterval(() => {
            carregarStatus();
        }, 5000);

        pollConversasTimer = setInterval(async () => {
            await carregarConversas({ preserveSelection: true, openFirstIfNeeded: false });
            if (conversaAtual) {
                await atualizarConversaAtualSilencioso();
            }
        }, 4000);
    }

    function stopPolling() {
        if (pollStatusTimer) clearInterval(pollStatusTimer);
        if (pollConversasTimer) clearInterval(pollConversasTimer);
        pollStatusTimer = null;
        pollConversasTimer = null;
    }

    function changeTarget(targetId) {
        if (!targetId) return;

        const select = document.getElementById("monitor-target");
        const selectedOption = select?.selectedOptions?.[0];
        const username = selectedOption?.textContent || "";

        currentTargetUserId = targetId;
        setActiveTargetLabel(username);

        const url = new URL(window.location.href);
        url.searchParams.set("as_user", targetId);
        window.location.href = url.toString();
    }

    document.addEventListener("DOMContentLoaded", async () => {
        ajustarAlturaZapPage();
        window.addEventListener("resize", ajustarAlturaZapPage);

        if (window.bootstrap) {
            const modalElement = document.getElementById("novaConversaModal");
            if (modalElement) {
                novaConversaModal = new bootstrap.Modal(modalElement);
            }
        }

        currentTargetUserId = resolveInitialTargetId() || getPageTargetId();
        currentTargetUsername = getPageTargetUsername();
        setActiveTargetLabel(currentTargetUsername);

        const buscaInput = document.getElementById("busca-conversa");
        const formEnvio = document.getElementById("form-envio");
        const btnConnect = document.getElementById("btn-connect");
        const btnDisconnect = document.getElementById("btn-disconnect");
        const btnNovaConversa = document.getElementById("btn-nova-conversa");
        const formNovaConversa = document.getElementById("form-nova-conversa");
        const btnExcluirConversa = document.getElementById("btn-excluir-conversa");
        const btnAnexo = document.getElementById("btn-anexo");
        const btnAudio = document.getElementById("btn-audio");
        const inputArquivo = document.getElementById("input-arquivo");
        const inputAudio = document.getElementById("input-audio");

        if (buscaInput) {
            buscaInput.addEventListener("input", () => renderConversas(conversasCache));
        }

        if (formEnvio) {
            formEnvio.addEventListener("submit", enviarMensagem);
        }

        if (btnConnect) {
            btnConnect.addEventListener("click", conectarWhatsapp);
        }

        if (btnDisconnect) {
            btnDisconnect.addEventListener("click", desconectarWhatsapp);
        }

        if (btnNovaConversa) {
            btnNovaConversa.addEventListener("click", () => {
                if (novaConversaModal) novaConversaModal.show();
            });
        }

        if (formNovaConversa) {
            formNovaConversa.addEventListener("submit", criarNovaConversa);
        }

        if (btnExcluirConversa) {
            btnExcluirConversa.addEventListener("click", excluirConversaAtual);
        }

        if (btnAnexo && inputArquivo) {
            btnAnexo.addEventListener("click", () => inputArquivo.click());
        }

        if (btnAudio) {
            btnAudio.addEventListener("click", async () => {
                if (gravandoAudio) {
                    pararGravacaoAudio();
                } else {
                    await iniciarGravacaoAudio();
                }
            });
        }

        if (inputArquivo) {
            inputArquivo.addEventListener("change", () => {
                const file = inputArquivo.files?.[0];
                if (!file) return;
                if (inputAudio) inputAudio.value = "";

                const inputMensagem = document.getElementById("input-mensagem");
                if (inputMensagem) {
                    inputMensagem.placeholder = `Arquivo: ${file.name}`;
                }
            });
        }


        setFormularioHabilitado(false);

        await carregarStatus();
        await carregarConversas({ preserveSelection: true, openFirstIfNeeded: true });
        startPolling();

        document.addEventListener("visibilitychange", async () => {
            if (!document.hidden) {
                ajustarAlturaZapPage();
                await carregarStatus();
                await carregarConversas({ preserveSelection: true, openFirstIfNeeded: true });
                if (conversaAtual) {
                    await atualizarConversaAtualSilencioso();
                }
            }
        });
    });

    window.ZapMsgUI = {
        changeTarget,
        reload: async () => {
            await carregarStatus();
            await carregarConversas({ preserveSelection: true, openFirstIfNeeded: true });
            if (conversaAtual) {
                await atualizarConversaAtualSilencioso();
            }
        },
    };
})();