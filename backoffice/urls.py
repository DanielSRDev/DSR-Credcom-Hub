from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf.urls.static import static
from django.conf import settings

from backoffice import views  # sua view ambiente
from core import views as core_views

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="login", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/primeiro-acesso/", core_views.primeiro_acesso, name="primeiro_acesso"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("ambiente/", views.ambiente, name="ambiente"),
    path("nibo/", include("nibo_panel.urls")),
    path("gestao/", include("Gestao.urls")),
    path("operacao/", include("operacao.urls")),
    # CHAT (com namespace certo)
    path("chat/", include(("chat_interno.urls", "chat_interno"), namespace="chat_interno")),
    path("zapmsg/", include("zapmsg.urls")),
    path("operacao/painel/", include(("painel_operacao.urls", "painel_operacao"), namespace="painel_operacao")),
    path("core/", include(("core.urls", "core"), namespace="core")),
    path("financeiro/", include(("financeiro.urls", "financeiro"), namespace="financeiro")),

] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)