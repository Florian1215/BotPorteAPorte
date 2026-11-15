"""Django email backend sending through Brevo's transactional email API (https://developers.brevo.com).

Every email of the site (login code, invitation, email change) goes through Django's mail API: setting
`EMAIL_BACKEND` to this class is enough. The sender (`DEFAULT_FROM_EMAIL`) must be a sender or a domain
verified in the Brevo account, otherwise Brevo refuses the email.
"""
import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

API_URL = "https://api.brevo.com/v3/smtp/email"


def _contact(address: str) -> dict:
    name, email = parseaddr(address)
    return {"email": email, "name": name} if name else {"email": email}


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages) -> int:
        sent = 0
        for message in email_messages:
            try:
                self._send(message)
                sent += 1
            except Exception:
                logger.exception("Brevo: email not sent")
                if not self.fail_silently:
                    raise
        return sent

    def _send(self, message) -> None:
        payload = {
            "sender": _contact(message.from_email or settings.DEFAULT_FROM_EMAIL),
            "to": [_contact(a) for a in message.to],
            "subject": message.subject,
            "textContent": message.body,
        }
        if message.cc:
            payload["cc"] = [_contact(a) for a in message.cc]
        if message.bcc:
            payload["bcc"] = [_contact(a) for a in message.bcc]
        if message.reply_to:
            payload["replyTo"] = _contact(message.reply_to[0])
        html = next((content for content, mimetype in getattr(message, "alternatives", []) if mimetype == "text/html"), None)
        if html:
            payload["htmlContent"] = html

        response = requests.post(
            API_URL,
            json=payload,
            headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"},
            timeout=settings.EMAIL_TIMEOUT,
        )
        if response.status_code >= 300:
            # Brevo's message says why (unverified sender, invalid key…); never the key itself.
            raise RuntimeError(f"Brevo {response.status_code}: {response.text[:300]}")
