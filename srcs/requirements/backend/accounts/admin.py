from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Scope, User


@admin.register(Scope)
class ScopeAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "country_code", "created_at"]
    search_fields = ["name", "code"]
    prepopulated_fields = {"code": ["name"]}


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "first_name", "scope", "is_approved", "is_staff", "date_joined"]
    list_filter = ["is_approved", "scope", "is_staff"]
    fieldsets = BaseUserAdmin.fieldsets + (("Porte-à-porte", {"fields": ["scope", "is_approved"]}),)
    actions = ["approve"]

    @admin.action(description="Valider les comptes sélectionnés")
    def approve(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"{updated} compte(s) validé(s).", messages.SUCCESS)
