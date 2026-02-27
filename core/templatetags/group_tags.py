from django import template

register = template.Library()

@register.filter
def has_any_group(user, group_names: str) -> bool:
    """
    Uso no template:
      {% if user|has_any_group:"NIBO" %} ... {% endif %}
      {% if user|has_any_group:"GESTAO,GESTAO_GESTOR" %} ... {% endif %}
    """
    if not user or not user.is_authenticated:
        return False

    # Superuser vê tudo (se você quiser travar superuser também, tira essa linha)
    if user.is_superuser:
        return True

    names = [n.strip() for n in (group_names or "").split(",") if n.strip()]
    if not names:
        return False

    return user.groups.filter(name__in=names).exists()