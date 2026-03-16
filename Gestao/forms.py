# Gestao/forms.py
from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Tarefa, Anexo, Comentario


PRAZO_MINIMO_HORAS = 1


class TarefaForm(forms.ModelForm):
    class Meta:
        model = Tarefa
        fields = ["titulo", "descricao", "prazo", "atribuida_para"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Título da tarefa"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Descreva a tarefa..."}),
            "prazo": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "atribuida_para": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        agora_local = timezone.localtime()
        prazo_minimo = agora_local + timedelta(hours=PRAZO_MINIMO_HORAS)

        # ajuda visual no input do navegador
        self.fields["prazo"].widget.attrs["min"] = prazo_minimo.strftime("%Y-%m-%dT%H:%M")

        if self.instance and self.instance.pk and self.instance.prazo:
            self.initial["prazo"] = timezone.localtime(self.instance.prazo).strftime("%Y-%m-%dT%H:%M")

    def clean_prazo(self):
        prazo = self.cleaned_data.get("prazo")
        if not prazo:
            return prazo

        agora = timezone.now()
        prazo_minimo = agora + timedelta(hours=PRAZO_MINIMO_HORAS)

        if prazo < prazo_minimo:
            minimo_formatado = timezone.localtime(prazo_minimo).strftime("%d/%m/%Y %H:%M")
            raise forms.ValidationError(
                f"O prazo mínimo deve ser de pelo menos {PRAZO_MINIMO_HORAS} hora(s) a partir de agora. "
                f"Escolha um horário igual ou posterior a {minimo_formatado}."
            )

        return prazo


class AnexoForm(forms.ModelForm):
    class Meta:
        model = Anexo
        fields = ["arquivo"]
        widgets = {
            "arquivo": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }


class ComentarioForm(forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ["texto"]
        widgets = {
            "texto": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Escreva o que você fez / o que aconteceu...",
                }
            )
        }