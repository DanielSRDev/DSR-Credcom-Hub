from django import forms
from .models import CarteiraSupervisor, SupervisorPainel, PainelOperacaoRegistro, PainelOperacaoRelatorioGeral


class PainelOperacaoFiltroForm(forms.Form):
    data_ini = forms.DateField(
        label="Data inicial",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    data_fim = forms.DateField(
        label="Data final",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    supervisor = forms.ModelChoiceField(
        label="Supervisor",
        queryset=SupervisorPainel.objects.filter(ativo=True).order_by("ordem", "nome"),
        required=False,
        empty_label="Todos",
        widget=forms.Select(attrs={"class": "form-select"})
    )
    operador = forms.ChoiceField(
        label="Operador",
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"})
    )
    credor = forms.ChoiceField(
        label="Carteira",
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        operadores = (
            PainelOperacaoRegistro.objects
            .exclude(emitido_por_nome__exact="")
            .values_list("emitido_por_nome", flat=True)
            .distinct()
            .order_by("emitido_por_nome")
        )
        self.fields["operador"].choices = [("", "Todos")] + [(op, op) for op in operadores]

        credores = (
            PainelOperacaoRegistro.objects
            .exclude(credor__exact="")
            .values_list("credor", flat=True)
            .distinct()
            .order_by("credor")
        )
        self.fields["credor"].choices = [("", "Todas")] + [(c, c) for c in credores]


class AcompanhamentoGeralFiltroForm(forms.Form):
    data_ini = forms.DateField(
        label="Data inicial",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    data_fim = forms.DateField(
        label="Data final",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    supervisor = forms.ModelChoiceField(
        label="Supervisor",
        queryset=SupervisorPainel.objects.filter(ativo=True).order_by("ordem", "nome"),
        required=False,
        empty_label="Todos",
        widget=forms.Select(attrs={"class": "form-select"})
    )
    operador = forms.ChoiceField(
        label="Operador",
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"})
    )
    credor = forms.ChoiceField(
        label="Carteira",
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        cre_ids_vinculados = list(
            CarteiraSupervisor.objects
            .filter(ativo=True, supervisor__ativo=True)
            .values_list("cre_id", flat=True)
        )

        base_relatorio = (
            PainelOperacaoRelatorioGeral.objects
            .filter(cre_id__in=cre_ids_vinculados)
            .exclude(emitido_por_nome__isnull=True)
            .exclude(emitido_por_nome__exact="")
        )

        operadores = (
            base_relatorio
            .values_list("emitido_por_nome", flat=True)
            .distinct()
            .order_by("emitido_por_nome")
        )
        self.fields["operador"].choices = [("", "Todos")] + [(op, op) for op in operadores]

        credores = (
            CarteiraSupervisor.objects
            .filter(ativo=True, supervisor__ativo=True)
            .exclude(credor_nome__exact="")
            .values_list("credor_nome", flat=True)
            .distinct()
            .order_by("credor_nome")
        )
        self.fields["credor"].choices = [("", "Todas")] + [(c, c) for c in credores]
