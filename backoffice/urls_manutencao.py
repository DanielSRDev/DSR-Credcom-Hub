"""
URLconf de MANUTENÇÃO.

Autossuficiente de propósito: não importa nenhum app, então é impossível
quebrar por erro de import enquanto você copia arquivos do sistema.

Como usar (no settings.py):
    ROOT_URLCONF = "backoffice.urls_manutencao"   # ENTRA em manutenção
    ROOT_URLCONF = "backoffice.urls"              # VOLTA ao normal

Responde HTTP 503 (Service Unavailable) para qualquer rota — o código correto
para "indisponível temporariamente" (buscadores e navegadores entendem que é
passageiro).
"""
from django.http import HttpResponse
from django.urls import re_path

HTML = """<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Em manutenção</title>
<style>
  body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:system-ui,Segoe UI,Arial;background:#0f172a;color:#e2e8f0;text-align:center}
  .box{max-width:480px;padding:32px}
  h1{font-size:22px;margin:0 0 12px}
  p{color:#94a3b8;line-height:1.5}
  .dot{font-size:48px;margin-bottom:8px}
</style></head>
<body><div class="box">
  <div class="dot">🛠️</div>
  <h1>Sistema em manutenção</h1>
  <p>Estamos aplicando uma atualização rápida. Já voltamos — tente novamente em alguns minutos.</p>
</div></body></html>"""


def manutencao(request):
    return HttpResponse(HTML, status=503)


urlpatterns = [re_path(r"^.*$", manutencao)]
