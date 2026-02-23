from django import template

register = template.Library()

@register.filter
def has_group(user, group_name: str) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.groups.filter(name=group_name).exists()
