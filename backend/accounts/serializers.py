from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class BaseRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name"]

    def create(self, validated_data):
        # Use email as username to keep login simple
        email = validated_data["email"].lower()
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.email = email
        user.username = email
        user.set_password(password)  # hashed password (TC-022)
        user.save()
        return user


class ProducerRegisterSerializer(BaseRegisterSerializer):
    def create(self, validated_data):
        user = super().create(validated_data)
        user.role = User.Role.PRODUCER
        user.save(update_fields=["role"])
        return user


class CustomerRegisterSerializer(BaseRegisterSerializer):
    def create(self, validated_data):
        user = super().create(validated_data)
        user.role = User.Role.CUSTOMER
        user.save(update_fields=["role"])
        return user