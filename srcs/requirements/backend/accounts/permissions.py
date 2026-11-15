from rest_framework.permissions import BasePermission


class IsCanvasser(BasePermission):
    message = (
        "Ton compte n'est pas encore autorisé. "
        "Un·e militant·e aguerri·e ou un·e responsable de ton organisation doit valider ton inscription."
    )

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.can_canvass)


class CanValidate(BasePermission):
    """Militant·e aguerri·e and above: sees and approves the sign-ups of their organization."""

    message = "Réservé aux militant·es aguerri·es et aux responsables de l'organisation."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and (user.can_validate or user.is_site_admin))


class IsSiteAdmin(BasePermission):
    message = "Réservé aux administrateur·rices du site."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_site_admin)
