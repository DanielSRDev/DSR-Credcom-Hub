# nibo_panel/forms.py
from django import forms

ENVIADO_CHOICES = (("", "Todos"), ("nao", "Não enviados"), ("sim", "Enviados"))

class FiltroForm(forms.Form):
    data_ini = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    data_fim = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    cliente  = forms.CharField(required=False, label="Cliente")
    enviado  = forms.ChoiceField(required=False, label="Enviado",
               choices=[("", "Todos"), ("sim", "Sim"), ("nao", "Não")])

    credores = forms.MultipleChoiceField(
        required=False, choices=[], label="Credor (sigla)",
        widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, credor_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["credores"].choices = [(c, c) for c in credor_choices]
        if not self.data:  # abre já com todos marcados
            self.fields["credores"].initial = [c for c, _ in self.fields["credores"].choices]



class LoginForm(forms.Form):
    username = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))



