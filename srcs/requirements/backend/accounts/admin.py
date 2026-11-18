from django.contrib import admin, messages

from .models import LoginCode, Organization, User, VoterList


@admin.register(VoterList)
class VoterListAdmin(admin.ModelAdmin):
    list_display = ["name", "country_code", "created_at"]
    search_fields = ["name"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "city", "voter_list", "radius_km", "created_at"]
    search_fields = ["name", "code"]
    prepopulated_fields = {"code": ["name"]}


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """No passwords: everyone logs in with a code sent by email."""

    list_display = ["email", "first_name", "last_name", "organization", "role", "is_approved", "is_staff", "last_login"]
    list_filter = ["is_approved", "role", "organization", "is_staff", "is_active"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]
    readonly_fields = ["last_login", "date_joined"]
    filter_horizontal = ["groups", "user_permissions"]
    fieldsets = [
        (None, {"fields": ["email", "first_name", "last_name"]}),
        ("Porte-à-porte", {"fields": ["organization", "role", "is_approved"]}),
        ("Accès", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    actions = ["approve"]

    def save_model(self, request, obj, form, change):
        if not obj.password:
            obj.set_unusable_password()
        super().save_model(request, obj, form, change)

    @admin.action(description="Valider les comptes sélectionnés")
    def approve(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"{updated} compte(s) validé(s).", messages.SUCCESS)


@admin.register(LoginCode)
class LoginCodeAdmin(admin.ModelAdmin):
    list_display = ["email", "organization", "created_at", "expires_at", "used_at", "attempts"]
    search_fields = ["email"]
    readonly_fields = [f.name for f in LoginCode._meta.fields]

    def has_add_permission(self, request):
        return False
