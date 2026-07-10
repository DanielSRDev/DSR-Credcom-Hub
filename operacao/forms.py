from datetime import timedelta

from django import forms
from django.contrib.auth.models import User
from django.utils import timezone

from core import roles
from .models import Tarefa, Comentario, Anexo, Equipe


PRAZO_MINIMO_HORAS = 1


# =========================================================
# CONTROLE DE CARGOS (compat — ver core/roles.py)
# =========================================================
def is_coord(user) -> bool:
    """'Vê tudo' = Diretoria (GESTAO) ou superuser."""
    return roles.ve_tudo(user)


def is_supervisor(user) -> bool:
    """Líder de equipe (Gestor) — inclui quem vê tudo."""
    return roles.is_gestor(user) or roles.ve_tudo(user)


def is_operador(user) -> bool:
    """Operador comum: acessa Operação mas não é líder, pós-acordo nem vê tudo."""
    return (
        roles.tem_acesso_operacao(user)
        and not is_supervisor(user)
        and not roles.is_pos_acordo(user)
    )


# =========================================================
# FORM DE TAREFA
# =========================================================
class TarefaForm(forms.ModelForm):
    class Meta:
        model = Tarefa
        fields = ["titulo", "descricao", "prazo", "atribuida_para"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "prazo": forms.DateTimeInput(
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                }
            ),
            "atribuida_para": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # ----------------------------
        # prazo mínimo visual
        # ----------------------------
        agora_local = timezone.localtime()
        prazo_minimo = agora_local + timedelta(hours=PRAZO_MINIMO_HORAS)
        self.fields["prazo"].widget.attrs["min"] = prazo_minimo.strftime("%Y-%m-%dT%H:%M")

        # ----------------------------
        # ao editar, mostra data formatada no input datetime-local
        # ----------------------------
        if self.instance and self.instance.pk and self.instance.prazo:
            self.initial["prazo"] = timezone.localtime(
                self.instance.prazo
            ).strftime("%Y-%m-%dT%H:%M")

        if not user:
            self.fields["atribuida_para"].queryset = User.objects.none()
            return

        # =====================================================
        # COORDENAÇÃO -> todos usuários ativos
        # =====================================================
        if is_coord(user):
            self.fields["atribuida_para"].queryset = (
                User.objects.filter(is_active=True)
                .order_by("username")
            )
            return

        # =====================================================
        # SUPERVISOR -> membros da equipe dele + ele mesmo
        # =====================================================
        if is_supervisor(user):
            # ------------------------------------------------------------------
            # ALTERADO: supervisor (FK) -> supervisores (M2M)
            # ------------------------------------------------------------------
            equipes_do_supervisor = Equipe.objects.filter(
                supervisores=user,
                ativa=True,
            )

            membros_ids = equipes_do_supervisor.values_list("membros__id", flat=True)

            self.fields["atribuida_para"].queryset = (
                User.objects.filter(
                    is_active=True,
                    id__in=list(membros_ids) + [user.id],
                )
                .distinct()
                .order_by("username")
            )
            # ------------------------------------------------------------------
            return

        # =====================================================
        # PÓS-ACORDO -> cria chamado para todos da Operação
        # =====================================================
        if roles.is_pos_acordo(user):
            self.fields["atribuida_para"].queryset = (
                roles.usuarios_no_cargo(*roles.CARGOS_OPERACAO).order_by("username")
            )
            return

        # =====================================================
        # OPERADOR -> somente supervisor(es) da equipe dele
        # =====================================================
        if is_operador(user):
            # ------------------------------------------------------------------
            # ALTERADO: supervisor_id (FK) -> supervisores (M2M)
            # select_related removido (não se aplica a M2M).
            # supervisores_ids agora vem da relação M2M diretamente.
            # ------------------------------------------------------------------
            equipes_do_operador = Equipe.objects.filter(
                membros=user,
                ativa=True,
            )

            supervisores_ids = equipes_do_operador.values_list("supervisores__id", flat=True)

            self.fields["atribuida_para"].queryset = (
                User.objects.filter(
                    id__in=supervisores_ids,
                    is_active=True,
                )
                .distinct()
                .order_by("username")
            )
            # ------------------------------------------------------------------
            return

        # fallback
        self.fields["atribuida_para"].queryset = User.objects.none()

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

    def clean_atribuida_para(self):
        atribuida_para = self.cleaned_data.get("atribuida_para")
        user = self.user

        if not user or not atribuida_para:
            return atribuida_para

        permitidos = self.fields["atribuida_para"].queryset

        if not permitidos.filter(id=atribuida_para.id).exists():
            if is_coord(user):
                raise forms.ValidationError("Atribuição inválida.")
            elif is_supervisor(user):
                raise forms.ValidationError("Você só pode atribuir chamados para sua equipe ou para você mesmo.")
            elif is_operador(user):
                raise forms.ValidationError("Você só pode criar chamado para o supervisor da sua equipe.")
            else:
                raise forms.ValidationError("Você não tem permissão para essa atribuição.")

        return atribuida_para


# =========================================================
# FORM DE COMENTÁRIO
# =========================================================
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


# =========================================================
# FORM DE ANEXO
# =========================================================
class AnexoForm(forms.ModelForm):
    class Meta:
        model = Anexo
        fields = ["arquivo", "nome_original"]
        widgets = {
            "arquivo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "nome_original": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nome opcional",
                }
            ),
        }

class DevolucaoForm(forms.Form):
    """
    Formulário de devolução com pendência.
    Aparece quando o criador rejeita um chamado EXECUTADO.
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
            "required":   "É obrigatório informar o motivo da devolução.",
            "min_length": "Descreva o motivo com pelo menos 10 caracteres.",
        },
    )
