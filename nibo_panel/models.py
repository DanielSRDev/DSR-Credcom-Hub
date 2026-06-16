from django.db import models

class StakeholderMap(models.Model):
    """
    Cache local dos IDs de stakeholders no Nibo.
    Evita hits desnecessários à API e mantém o vínculo CPF/CNPJ -> nibo_id.
    """
    KIND_CUSTOMER = "customer"
    KIND_SUPPLIER = "supplier"

    KIND_CHOICES = (
        (KIND_CUSTOMER, "customer"),
        (KIND_SUPPLIER, "supplier"),
    )

    doc = models.CharField(max_length=20)                  # CPF/CNPJ só com dígitos
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    nibo_id = models.UUIDField()
    name = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "nibo_stakeholder_map"
        constraints = [
            models.UniqueConstraint(
                fields=["doc", "kind"],
                name="uniq_nibo_stakeholder_map_doc_kind",
            )
        ]

    def __str__(self) -> str:
        return f"{self.doc} [{self.kind}] -> {self.nibo_id}"


class CredorVisivel(models.Model):
    """
    Controla quais credores (por credor_id) aparecem no filtro do Painel Nibo.
    Apenas credores marcados como ativos são exibidos para o usuário.
    O campo 'sigla' é apenas um rótulo de apoio para facilitar a identificação no admin.
    """
    credor_id = models.BigIntegerField(unique=True)
    sigla = models.CharField(max_length=50, blank=True, null=True)
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "nibo_credor_visivel"
        ordering = ["ordem", "credor_id"]
        verbose_name = "Credor visível (Painel Nibo)"
        verbose_name_plural = "Credores visíveis (Painel Nibo)"

    def __str__(self) -> str:
        label = self.sigla or self.credor_id
        return f"{label} ({'ativo' if self.ativo else 'inativo'})"
