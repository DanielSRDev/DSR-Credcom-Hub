from django.apps import AppConfig


def _loop_envio_automatico():
    """
    Servico interno do HUB (mesma ideia do puxador do stage): roda em uma
    thread daemon e, todo DIA UTIL a partir da hora configurada, dispara o
    envio dos lancamentos NAO enviados do dia util anterior.

    Como o comando so envia registros com enviado=FALSE, rodar de novo no
    mesmo dia (ex: apos reiniciar o HUB) nao reenvia nada.
    """
    import time
    from datetime import datetime

    from django.conf import settings
    from django.core.management import call_command

    hora_alvo = int(getattr(settings, "NIBO_AUTO_ENVIO_HORA", 9))
    ultima_data_exec = None

    print(f"[nibo_panel] Envio automatico ATIVO (dia util, a partir das {hora_alvo:02d}:00).")

    while True:
        try:
            agora = datetime.now()
            hoje = agora.date()
            eh_dia_util = hoje.weekday() < 5  # 0=seg ... 4=sex
            if eh_dia_util and agora.hour >= hora_alvo and ultima_data_exec != hoje:
                print(f"[nibo_panel] Disparando envio automatico ({hoje:%d/%m/%Y}).")
                try:
                    call_command("nibo_enviar_dia_anterior")
                finally:
                    # marca como executado mesmo se houver erro, para nao
                    # ficar tentando em loop no mesmo dia.
                    ultima_data_exec = hoje
        except Exception as e:
            print("[nibo_panel] Erro no loop de envio automatico:", e)
        time.sleep(60)


class NiboPanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "nibo_panel"

    def ready(self):
        import os
        import sys
        import threading

        from django.conf import settings

        # so dentro do runserver (nao em migrate/shell/etc.)
        if "runserver" not in sys.argv:
            return
        # evita thread dupla por causa do autoreload do runserver
        if os.environ.get("RUN_MAIN") != "true":
            return
        # desligado por padrao: so liga quando NIBO_AUTO_ENVIO_ATIVO=True
        if not getattr(settings, "NIBO_AUTO_ENVIO_ATIVO", False):
            return

        threading.Thread(target=_loop_envio_automatico, daemon=True).start()
