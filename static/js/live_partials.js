(function () {
  function initLivePartials() {
    const nodes = document.querySelectorAll("[data-live-url]");
    if (!nodes.length) return;

    nodes.forEach((el) => {
      const url = el.getAttribute("data-live-url");
      const intervalMs = parseInt(el.getAttribute("data-live-interval") || "5000", 10);

      let running = false;

      async function refresh() {
        if (running) return;
        running = true;

        try {
          const resp = await fetch(url, {
            method: "GET",
            headers: { "X-Requested-With": "XMLHttpRequest" },
            cache: "no-store",
          });

          if (!resp.ok) {
            el.innerHTML = `<div class="text-danger small">Erro ao carregar indicadores (${resp.status}).</div>`;
            return;
          }

          const html = await resp.text();
          el.innerHTML = html;
        } catch (err) {
          el.innerHTML = `<div class="text-danger small">Erro ao carregar indicadores.</div>`;
        } finally {
          running = false;
        }
      }

      // primeira carga imediata
      refresh();

      // atualiza em loop
      setInterval(refresh, intervalMs);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLivePartials);
  } else {
    initLivePartials();
  }
})();