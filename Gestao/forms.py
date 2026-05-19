# ==============================================================
# CONTEÚDO PARA: Gestao/forms.py
# ==============================================================
# Cole este arquivo em Gestao/forms.py substituindo o existente.
# ==============================================================

from datetime import timedelta
from django import forms
from django.utils import timezone
from .models import Tarefa, Anexo, Comentario

PRAZO_MINIMO_HORAS = 1


class TarefaForm(forms.ModelForm):
    class Meta:
        model  = Tarefa
        fields = ["titulo", "descricao", "prazo", "atribuida_para"]
        widgets = {
            "titulo":         forms.TextInput(attrs={"class": "form-control", "placeholder": "Título da tarefa"}),
            "descricao":      forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Descreva a tarefa..."}),
            "prazo":          forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "atribuida_para": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        agora_local  = timezone.localtime()
        prazo_minimo = agora_local + timedelta(hours=PRAZO_MINIMO_HORAS)
        self.fields["prazo"].widget.attrs["min"] = prazo_minimo.strftime("%Y-%m-%dT%H:%M")
        if self.instance and self.instance.pk and self.instance.prazo:
            self.initial["prazo"] = timezone.localtime(self.instance.prazo).strftime("%Y-%m-%dT%H:%M")

    def clean_prazo(self):
        prazo = self.cleaned_data.get("prazo")
        if not prazo:
            return prazo
        prazo_minimo = timezone.now() + timedelta(hours=PRAZO_MINIMO_HORAS)
        if prazo < prazo_minimo:
            minimo_fmt = timezone.localtime(prazo_minimo).strftime("%d/%m/%Y %H:%M")
            raise forms.ValidationError(
                f"O prazo mínimo deve ser de pelo menos {PRAZO_MINIMO_HORAS} hora(s) a partir de agora. "
                f"Escolha um horário igual ou posterior a {minimo_fmt}."
            )
        return prazo


class AnexoForm(forms.ModelForm):
    class Meta:
        model  = Anexo
        fields = ["arquivo"]
        widgets = {"arquivo": forms.ClearableFileInput(attrs={"class": "form-control"})}


class ComentarioForm(forms.ModelForm):
    class Meta:
        model  = Comentario
        fields = ["texto"]
        widgets = {
            "texto": forms.Textarea(attrs={
                "class": "form-control", "rows": 3,
                "placeholder": "Escreva o que você fez / o que aconteceu...",
            })
        }


class DevolucaoForm(forms.Form):
    """
    Formulário de devolução com pendência.
    Aparece quando o criador rejeita um card EXECUTADO.
    O campo 'motivo' é obrigatório e vira um Comentario com eh_devolucao=True.
    """
    motivo = forms.CharField(
        label="O que precisa ser corrigido?",
        min_length=10,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 3,
            "placeholder": "Descreva o que está faltando ou precisa ser refeito...",
        }),
        error_messages={
            "required":  "É obrigatório informar o motivo da devolução.",
            "min_length": "Descreva o motivo com pelo menos 10 caracteres.",
        },
    )


# ==============================================================
# CONTEÚDO PARA: operacao/forms.py
# ==============================================================
# A única diferença é a importação dos models do app operacao.
# Copie o bloco abaixo para operacao/forms.py substituindo o existente.
# Os forms TarefaForm e AnexoForm do operacao têm lógica adicional
# (filtro de atribuida_para por cargo) — mantenha o TarefaForm original
# e apenas ADICIONE o DevolucaoForm ao final do arquivo.
# ==============================================================

# ---- ADICIONAR AO FINAL DE operacao/forms.py ----

# from django import forms
#
# class DevolucaoForm(forms.Form):
#     motivo = forms.CharField(
#         label="O que precisa ser corrigido?",
#         min_length=10,
#         widget=forms.Textarea(attrs={
#             "class": "form-control",
#             "rows": 3,
#             "placeholder": "Descreva o que está faltando ou precisa ser refeito...",
#         }),
#         error_messages={
#             "required":   "É obrigatório informar o motivo da devolução.",
#             "min_length": "Descreva o motivo com pelo menos 10 caracteres.",
#         },
#     )
