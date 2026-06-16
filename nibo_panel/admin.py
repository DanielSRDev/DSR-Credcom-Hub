from django.contrib import admin
from .models import CredorVisivel


@admin.register(CredorVisivel)
class CredorVisivelAdmin(admin.ModelAdmin):
    list_display = ("credor_id", "sigla", "ativo", "ordem")
    list_editable = ("ativo", "ordem")
    list_filter = ("ativo",)
    search_fields = ("credor_id", "sigla")
    ordering = ("ordem", "credor_id")
