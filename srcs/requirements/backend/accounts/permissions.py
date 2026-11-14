from rest_framework.permissions import BasePermission


class IsCanvasser(BasePermission):
    message = (
        "Ton compte n'est pas encore autorisé. "
        "Contacte ta/ton responsable porte-à-porte pour être ajouté·e à la liste."
    )

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.can_canvass)
