from django.apps import AppConfig


def _marcador_path():
    """Arquivo que guarda a data da ultima execucao do envio automatico.
    Fica em var/ para sobreviver a reinicializacoes do HUB."""
    from pathlib import Path

    from django.conf import settings

    base = Path(getattr(settings, "BASE_DIR", Path(".")))
    return base / "var" / "nibo_auto_envio_ultima_exec.txt"


def _ler_ultima_exec():
    """Le do disco a data da ultima execucao (ou None se nao houver/invalida)."""
    from datetime import date

    try:
        txt = _marcador_path().read_text(encoding="utf-8").strip()
        return date.fromisoformat(txt)
    except Exception:
        return None


def _gravar_ultima_exec(d):
    """Persiste no disco a data da ultima execucao."""
    try:
        p = _marcador_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(d.isoformat(), encoding="utf-8")
    except Exception as e:
        print("[nibo_panel] Falha ao gravar marcador de execucao:", e)


def _loop_envio_automatico():
    """
    Servico interno do HUB (mesma ideia do puxador do stage): roda em uma
    thread daemon e, todo DIA UTIL a partir da hora configurada, dispara o
    envio dos lancamentos NAO enviados do dia util anterior.

    O controle de "ja rodei hoje" e PERSISTIDO em disco (var/). Assim, se o
    HUB for desligado e religado no mesmo dia depois da hora alvo, ele NAO
    dispara o envio de novo (antes esse controle ficava so na memoria e
    reiniciar o HUB causava reenvio).
    """
    import time
    from datetime import datetime

    from django.conf import settings
    from django.core.management import call_command

    from .services.remessa import adquirir_lock_envio, liberar_lock_envio

    hora_alvo = int(getattr(settings, "NIBO_AUTO_ENVIO_HORA", 9))
    ultima_data_exec = _ler_ultima_exec()

    print(
        f"[nibo_panel] Envio automatico ATIVO (dia util, a partir das {hora_alvo:02d}:00). "
        f"Ultima execucao registrada: {ultima_data_exec or 'nenhuma'}."
    )

    while True:
        try:
            agora = datetime.now()
            hoje = agora.date()
            eh_dia_util = hoje.weekday() < 5  # 0=seg ... 4=sex
            # SEMPRE relido do disco (nao so da memoria): se houver mais de um
            # processo do HUB no ar (ex.: durante um restart/redeploy), cada um
            # tem sua propria copia em memoria e so o disco e compartilhado.
            ultima_data_exec = _ler_ultima_exec()
            if eh_dia_util and agora.hour >= hora_alvo and ultima_data_exec != hoje:
                # Lock em arquivo: se outro processo (ou este mesmo, disparado
                # por engano) ja estiver enviando agora, nao entra de novo.
                # Isso e o que existia para faltar em jul/2026 e fez o job das
                # 9h disparar 2-3x junto, mandando os mesmos lancamentos
                # repetidos pro Nibo.
                if not adquirir_lock_envio():
                    print(
                        f"[nibo_panel] Envio automatico ({hoje:%d/%m/%Y}) pulado: "
                        f"ja existe um envio em andamento (outro processo/instancia)."
                    )
                else:
                    print(f"[nibo_panel] Disparando envio automatico ({hoje:%d/%m/%Y}).")
                    try:
                        call_command("nibo_enviar_dia_anterior")
                    finally:
                        # marca como executado (em memoria E em disco) mesmo se houver
                        # erro, para nao ficar tentando em loop nem reenviar apos um
                        # reinicio do HUB no mesmo dia.
                        ultima_data_exec = hoje
                        _gravar_ultima_exec(hoje)
                        liberar_lock_envio()
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

        # Opt-in explicito (funciona com runserver --noreload, sem --noreload, ou
        # gunicorn com --workers 1). Nao depende do RUN_MAIN do autoreload do Django,
        # que so fica "true" quando o runserver roda SEM --noreload.
        if os.environ.get("RUN_BACKGROUND_JOBS") == "1":
            pass
        elif "runserver" in sys.argv and os.environ.get("RUN_MAIN") == "true":
            # compatibilidade com o comportamento antigo (runserver sem --noreload)
            pass
        else:
            return
        # desligado por padrao: so liga quando NIBO_AUTO_ENVIO_ATIVO=True
        if not getattr(settings, "NIBO_AUTO_ENVIO_ATIVO", False):
            return

        threading.Thread(target=_loop_envio_automatico, daemon=True).start()
