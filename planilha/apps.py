from django.apps import AppConfig


def _loop_sync_status_virtua():
    """
    Roda em thread daemon e, a cada N minutos, atualiza o Status Atual dos
    contratos com o último evento de cobrança do Virtua (mesma ideia do
    envio automático do nibo_panel). Falha de conexão com o Virtua não
    derruba o HUB — só loga e tenta de novo no próximo ciclo.
    """
    import time

    from django.conf import settings

    from .services import adquirir_lock_sync_status, liberar_lock_sync_status, sincronizar_status_virtua

    minutos = int(getattr(settings, "PLANILHA_SYNC_STATUS_MINUTOS", 60))
    print(f"[planilha] Sincronização de Status Atual (Virtua) ATIVA, a cada {minutos} min.")

    while True:
        if not adquirir_lock_sync_status():
            print("[planilha] Sync status Virtua pulado: já há uma sincronização em andamento (provavelmente disparada manualmente).")
        else:
            try:
                resultado = sincronizar_status_virtua()
                print(
                    f"[planilha] Sync status Virtua: base={resultado['total_base']} "
                    f"encontrados={resultado['encontrados']} atualizados={resultado['atualizados']} "
                    f"limpos={resultado['limpos']}"
                )
            except Exception as e:
                print("[planilha] Erro no sync de status Virtua:", e)
            finally:
                liberar_lock_sync_status()
        time.sleep(minutos * 60)


class PlanilhaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'planilha'

    def ready(self):
        import os
        import sys
        import threading

        from django.conf import settings

        if os.environ.get("RUN_BACKGROUND_JOBS") == "1":
            pass
        elif "runserver" in sys.argv and os.environ.get("RUN_MAIN") == "true":
            pass
        else:
            return
        if not getattr(settings, "PLANILHA_SYNC_STATUS_ATIVO", False):
            return

        threading.Thread(target=_loop_sync_status_virtua, daemon=True).start()
