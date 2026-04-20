from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


@register.filter
def brl(value):
    try:
        numero = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        numero = Decimal("0.00")

    texto = f"{numero:,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")

    return f"R$: {texto}"