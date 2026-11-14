from django.contrib.auth import password_validation
from rest_framework import serializers

from .models import Scope, User


class ScopeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scope
        fields = ["code", "name", "country_code"]


class MeSerializer(serializers.ModelSerializer):
    scope = ScopeSerializer(read_only=True)
    can_canvass = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "is_approved", "is_staff", "can_canvass", "scope"]


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    first_name = serializers.CharField(max_length=150)
    password = serializers.CharField(trim_whitespace=False, write_only=True)
    scope = serializers.SlugRelatedField(slug_field="code", queryset=Scope.objects.all(), required=False, allow_null=True)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Ce nom d'utilisateur est déjà pris.")
        return value

    def validate(self, attrs):
        password_validation.validate_password(attrs["password"], User(username=attrs["username"]))
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            first_name=validated_data["first_name"],
            password=validated_data["password"],
            scope=validated_data.get("scope"),
            is_approved=False,
        )
