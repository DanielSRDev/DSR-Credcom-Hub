from django import forms


class ImportUploadForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo Excel (.xlsx) com a aba 'Operador'",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx", "class": "form-control"}),
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        nome = (arquivo.name or "").lower()
        if not nome.endswith(".xlsx"):
            raise forms.ValidationError("Envie um arquivo .xlsx.")
        return arquivo
