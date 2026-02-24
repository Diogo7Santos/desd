from django.shortcuts import render
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import CustomerRegisterSerializer, ProducerRegisterSerializer

User = get_user_model()


class RegisterProducerView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ProducerRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"id": user.id, "email": user.email, "role": user.role, "token": token.key},
            status=status.HTTP_201_CREATED,
        )


class RegisterCustomerView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CustomerRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"id": user.id, "email": user.email, "role": user.role, "token": token.key},
            status=status.HTTP_201_CREATED,
        )


class LoginView(ObtainAuthToken):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # expects username + password; we set username=email at registration
        response = super().post(request, *args, **kwargs)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        return Response({"id": u.id, "email": u.email, "role": u.role})
# Create your views here.
