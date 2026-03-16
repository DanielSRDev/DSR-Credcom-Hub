from datetime import timedelta

from django import forms
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Tarefa, Comentario, Anexo


PRAZO_MINIMO_HORAS = 1


# ===============================
# CONTROLE DE GRUPOS
# ===============================
def _in_group(user, group_name: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name=group_name).exists()


def is_coord(user) -> bool:
    return _in_group(user, "OPERACAO_CORDENACAO")


def is_supervisor(user) -> bool:
    return _in_group(user, "OPERACAO_SUPERVISOR") or is_coord(user)


# ===============================
# FORM TAREFA
# ===============================
class TarefaForm(forms.ModelForm):
    class Meta:
        model = Tarefa
        fields = ["titulo", "descricao", "prazo", "atribuida_para"]

        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "prazo": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "atribuida_para": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        agora_local = timezone.localtime()
        prazo_minimo = agora_local + timedelta(hours=PRAZO_MINIMO_HORAS)

        # ajuda visual no input do navegador
        self.fields["prazo"].widget.attrs["min"] = prazo_minimo.strftime("%Y-%m-%dT%H:%M")

        if self.instance and self.instance.pk and self.instance.prazo:
            self.initial["prazo"] = timezone.localtime(self.instance.prazo).strftime("%Y-%m-%dT%H:%M")

        if not user:
            return

        # ===============================
        # COORDENAÇÃO → vê todos
        # ===============================
        if is_coord(user):
            self.fields["atribuida_para"].queryset = (
                User.objects.filter(is_active=True)
                .order_by("username")
            )
            return

        # ===============================
        # SUPERVISOR → só equipe dele + ele
        # ===============================
        if is_supervisor(user):
            membros = User.objects.filter(
                operacao_equipes__supervisor=user
            )

            self.fields["atribuida_para"].queryset = (
                (membros | User.objects.filter(id=user.id))
                .distinct()
                .order_by("username")
            )
            return

        # ===============================
        # OPERADOR → só ele mesmo
        # ===============================
        self.fields["atribuida_para"].queryset = User.objects.filter(id=user.id)

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


# ===============================
# FORM COMENTÁRIO
# ===============================
class ComentarioForm(forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ["texto"]
        widgets = {
            "texto": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Escreva um comentário...",
                }
            ),
        }


# ===============================
# FORM ANEXO
# ===============================
class AnexoForm(forms.ModelForm):
    class Meta:
        model = Anexo
        fields = ["arquivo", "nome_original"]
        widgets = {
            "arquivo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "nome_original": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Nome opcional"}
            ),
        }