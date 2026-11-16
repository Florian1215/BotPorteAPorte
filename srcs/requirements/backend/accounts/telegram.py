"""Link a Telegram account to a member, to give them back what they did with the old Telegram bot.

The site's "Lier mon compte Telegram" button opens Telegram's login popup (https://core.telegram.org/widgets/login).
Telegram sends back the account (id, name, auth_date) signed with the bot's token: the signature is checked here,
so nobody can claim someone else's Telegram id.
"""
import hashlib
import hmac
import time

from django.conf import settings
from django.db import transaction

# The signed data is accepted for this long after Telegram issued it.
MAX_AGE_S = 24 * 3600


class TelegramLinkError(Exception):
    pass


def verified_id(data: dict, now: float | None = None) -> int:
    """Telegram id of the signed login data, or TelegramLinkError."""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise TelegramLinkError("La liaison Telegram n'est pas configurée sur ce site.")
    if not isinstance(data, dict):
        raise TelegramLinkError("Réponse de Telegram illisible.")
    received = str(data.get("hash") or "")
    fields = {k: str(v) for k, v in data.items() if k != "hash" and v is not None}
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(expected, received):
        raise TelegramLinkError("La réponse de Telegram n'a pas pu être vérifiée. Réessaie.")
    try:
        auth_date, telegram_id = int(fields["auth_date"]), int(fields["id"])
    except (KeyError, ValueError):
        raise TelegramLinkError("Réponse de Telegram incomplète.") from None
    if (now if now is not None else time.time()) - auth_date > MAX_AGE_S:
        raise TelegramLinkError("La connexion Telegram a expiré. Réessaie.")
    return telegram_id


@transaction.atomic
def link(user, telegram_id: int) -> int:
    """Link the account and give the member the bot visits made with it. Returns the number of visits."""
    from canvassing.models import Visit

    from .models import User

    if user.telegram_id is not None:
        raise TelegramLinkError("Ton compte est déjà lié à un compte Telegram.")
    if User.objects.filter(telegram_id=telegram_id).exclude(pk=user.pk).exists():
        raise TelegramLinkError("Ce compte Telegram est déjà lié à un autre compte du site.")
    user.telegram_id = telegram_id
    user.save(update_fields=["telegram_id"])
    return Visit.objects.filter(user__isnull=True, telegram_user_id=telegram_id).update(user=user)
