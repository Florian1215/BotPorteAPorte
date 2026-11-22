"""Emails sent by the site: login code (+ link), invitation of a member added beforehand, sign-up request / approval."""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.utils.html import escape

from .models import Organization, Role, User

BRAND = "#d1271c"


def site_url(request) -> str:
    return settings.PUBLIC_URL or request.build_absolute_uri("/").rstrip("/")


def _layout(title: str, body_html: str, button_label: str, button_url: str, footer: str) -> str:
    return f"""<!doctype html>
<html lang="fr"><body style="margin:0;background:#f4f4f5;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#18181b">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:440px;background:#fff;border-radius:20px;padding:32px 28px">
        <tr><td>
          <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:{BRAND}">Porte-à-porte militant</p>
          <h1 style="margin:0 0 16px;font-size:22px;line-height:1.25">{title}</h1>
          {body_html}
          <p style="margin:24px 0 8px"><a href="{escape(button_url)}" style="display:inline-block;background:{BRAND};color:#fff;text-decoration:none;font-weight:600;padding:13px 22px;border-radius:14px">{button_label}</a></p>
          <p style="margin:24px 0 0;font-size:12px;line-height:1.5;color:#71717a">{footer}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def send_login_code(request, email: str, code: str, token: str, organization: Organization | None) -> None:
    link = f"{site_url(request)}/login/verify?token={token}"
    pretty_code = f"{code[:3]} {code[3:]}"
    minutes = settings.LOGIN_CODE_TTL_MINUTES
    where = f" à {organization.name}" if organization else ""
    subject = f"{pretty_code} — ton code de connexion"
    text = (
        f"Voici ton code pour te connecter{where} : {pretty_code}\n\n"
        f"Ou clique directement sur ce lien :\n{link}\n\n"
        f"Le code et le lien sont valables {minutes} minutes et ne servent qu'une fois.\n"
        "Si tu n'as pas demandé à te connecter, ignore simplement cet email."
    )
    body = f"""<p style="margin:0 0 16px;font-size:15px;line-height:1.5">Voici ton code pour te connecter{escape(where)} :</p>
          <p style="margin:0;font-size:34px;font-weight:700;letter-spacing:6px;font-variant-numeric:tabular-nums">{pretty_code}</p>"""
    html = _layout(
        "Ton code de connexion",
        body,
        "Me connecter directement",
        link,
        f"Le code et le lien sont valables {minutes} minutes et ne servent qu'une fois. "
        "Si tu n'as pas demandé à te connecter, ignore simplement cet email.",
    )
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [email])
    message.attach_alternative(html, "text/html")
    message.send()


def send_invitation(request, email: str, organization: Organization, invited_by: str, role_label: str | None = None) -> None:
    """`role_label`: shown when the person is not a plain militant·e ("comme Responsable d'organisation")."""
    link = f"{site_url(request)}/login"
    as_role = f" comme {role_label.lower() if role_label.startswith('Militant') else role_label}" if role_label else ""
    subject = f"Tu as été ajouté·e à {organization.name}"
    text = (
        f"{invited_by} t'a ajouté·e à {organization.name}{as_role} pour faire du porte-à-porte.\n\n"
        f"Pour te connecter, ouvre {link}, choisis « {organization.name} » et entre cette adresse email : "
        "tu recevras un code de connexion. Pas de mot de passe à retenir."
    )
    body = f"""<p style="margin:0;font-size:15px;line-height:1.5"><strong>{escape(invited_by)}</strong> t'a ajouté·e à
          <strong>{escape(organization.name)}</strong>{escape(as_role)} pour faire du porte-à-porte.</p>
          <p style="margin:12px 0 0;font-size:15px;line-height:1.5">Choisis « {escape(organization.name)} » et entre cette adresse email :
          tu recevras un code de connexion. Pas de mot de passe à retenir.</p>"""
    html = _layout("Bienvenue dans l'équipe", body, "Me connecter", link, "Tu reçois cet email parce qu'un·e responsable de ton groupe d'action a ajouté ton adresse.")
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [email])
    message.attach_alternative(html, "text/html")
    message.send()


def send_email_change_code(request, new_email: str, code: str, token: str) -> None:
    link = f"{site_url(request)}/account/verify-email?token={token}"
    pretty_code = f"{code[:3]} {code[3:]}"
    minutes = settings.LOGIN_CODE_TTL_MINUTES
    subject = f"{pretty_code} — confirme ta nouvelle adresse email"
    text = (
        f"Pour confirmer que cette adresse est bien la tienne, entre ce code dans ton compte : {pretty_code}\n\n"
        f"Ou clique directement sur ce lien :\n{link}\n\n"
        f"Le code et le lien sont valables {minutes} minutes et ne servent qu'une fois.\n"
        "Si tu n'as rien demandé, ignore simplement cet email : ton adresse ne sera pas utilisée."
    )
    body = f"""<p style="margin:0 0 16px;font-size:15px;line-height:1.5">Pour confirmer que cette adresse est bien la tienne, entre ce code dans ton compte :</p>
          <p style="margin:0;font-size:34px;font-weight:700;letter-spacing:6px;font-variant-numeric:tabular-nums">{pretty_code}</p>"""
    html = _layout(
        "Confirme ta nouvelle adresse",
        body,
        "Confirmer cette adresse",
        link,
        f"Le code et le lien sont valables {minutes} minutes et ne servent qu'une fois. "
        "Si tu n'as rien demandé, ignore simplement cet email : ton adresse ne sera pas utilisée.",
    )
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [new_email])
    message.attach_alternative(html, "text/html")
    message.send()


def send_email_changed_notice(request, old_email: str, new_email: str) -> None:
    """Security notice to the previous address."""
    subject = "Ton adresse email de connexion a changé"
    text = (
        f"L'adresse de connexion de ton compte Porte-à-porte est maintenant {new_email}.\n"
        f"Tu ne pourras plus te connecter avec {old_email}.\n\n"
        "Si ce n'est pas toi, préviens au plus vite un·e responsable de ton organisation."
    )
    body = f"""<p style="margin:0;font-size:15px;line-height:1.5">L'adresse de connexion de ton compte est maintenant
          <strong>{escape(new_email)}</strong>. Tu ne pourras plus te connecter avec {escape(old_email)}.</p>"""
    html = _layout(
        "Adresse email modifiée",
        body,
        "Ouvrir le site",
        f"{site_url(request)}/login",
        "Si ce n'est pas toi, préviens au plus vite un·e responsable de ton organisation.",
    )
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [old_email])
    message.attach_alternative(html, "text/html")
    message.send()


def _send(subject: str, text: str, html: str, to: str) -> None:
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [to])
    message.attach_alternative(html, "text/html")
    message.send()


def sign_up_reviewers(organization: Organization):
    """Who is told about a new sign-up: the responsables of the organization, else the site admins."""
    active = User.objects.filter(is_active=True)
    managers = active.filter(organization=organization, role=Role.MANAGER, is_approved=True, suspended_at__isnull=True)
    if managers.exists():
        return managers
    return active.filter(Q(is_superuser=True) | Q(role=Role.ADMIN))


def send_sign_up_request(request, member, organization: Organization) -> None:
    """Tell the responsables of `organization` that `member` asks to join (one email each, recipients not shared)."""
    link = f"{site_url(request)}/members"
    subject = f"Nouvelle demande d'accès à {organization.name} : {member.email}"
    text = (
        f"{member.email} demande à rejoindre {organization.name} pour faire du porte-à-porte.\n\n"
        f"Acceptes-tu cette demande ? Valide-la ou refuse-la ici :\n{link}"
    )
    body = f"""<p style="margin:0;font-size:15px;line-height:1.5"><strong>{escape(member.email)}</strong> demande à rejoindre
          <strong>{escape(organization.name)}</strong> pour faire du porte-à-porte.</p>
          <p style="margin:12px 0 0;font-size:15px;line-height:1.5">Acceptes-tu cette demande ?</p>"""
    html = _layout(
        "Nouvelle demande d'accès",
        body,
        "Valider ou refuser",
        link,
        f"Tu reçois cet email parce que tu es responsable de {escape(organization.name)}.",
    )
    for reviewer in sign_up_reviewers(organization).exclude(pk=member.pk):
        try:
            _send(subject, text, html, reviewer.email)
        except Exception:
            pass  # the request is listed on the site anyway


def send_account_approved(request, member) -> None:
    organization = member.organization
    where = f" à {organization.name}" if organization else ""
    link = f"{site_url(request)}/login"
    subject = "C'est bon, ton compte est validé !"
    text = (
        f"Ta demande pour rejoindre{where} a été acceptée : tu as maintenant accès au porte-à-porte.\n\n"
        f"Connecte-toi ici :\n{link}"
    )
    body = f"""<p style="margin:0;font-size:15px;line-height:1.5">Ta demande pour rejoindre{escape(where)} a été acceptée :
          tu as maintenant accès au porte-à-porte. Bonne tournée !</p>"""
    html = _layout("Ton compte est validé", body, "Me connecter", link, "Tu reçois cet email parce que tu as demandé à rejoindre un groupe d'action.")
    _send(subject, text, html, member.email)
