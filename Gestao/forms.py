# Gestao/forms.py
from django import forms
from .models import Tarefa, Anexo, Comentario


class TarefaForm(forms.ModelForm):
    class Meta:
        model = Tarefa
        fields = ["titulo", "descricao", "prazo", "atribuida_para"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Título da tarefa"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 6, "placeholder": "Descreva a tarefa..."}),
            "prazo": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "atribuida_para": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.prazo:
            self.initial["prazo"] = self.instance.prazo.strftime("%Y-%m-%dT%H:%M")


class AnexoForm(forms.ModelForm):
    class Meta:
        model = Anexo
        fields = ["arquivo"]
        widgets = {"arquivo": forms.ClearableFileInput(attrs={"class": "form-control"})}


class ComentarioForm(forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ["texto"]
        widgets = {
            "texto": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Escreva o que foi feito / aconteceu..."})
        }