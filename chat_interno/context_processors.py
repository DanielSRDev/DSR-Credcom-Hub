from .services import unread_count, allowed_contacts, is_online, unread_by_contact


def chat_nav(request):
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return {
            "chat_enabled": False,
            "chat_unread_total": 0,
            "chat_contacts": [],
            "chat_unread_map": {},
        }

    contacts_qs = allowed_contacts(user)

    unread_map = unread_by_contact(user)

    contacts = []
    for u in contacts_qs:
        contacts.append({
            "id": u.id,
            "username": u.get_username(),
            "name": (u.get_full_name() or u.get_username()),
            "online": is_online(u.id),
            "unread": int(unread_map.get(u.id, 0)),
        })

    return {
        "chat_enabled": True,
        "chat_unread_total": int(unread_count(user)),
        "chat_contacts": contacts,
        "chat_unread_map": unread_map,
    }