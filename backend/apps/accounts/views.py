from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegisterSerializer, TenantLoginSerializer, TenantSerializer, UserSerializer


def _tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    refresh["tenant_id"] = str(user.tenant_id)
    refresh["tenant_subdomain"] = user.tenant.subdomain
    refresh["role"] = user.role
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        user = result["user"]
        return Response(
            {
                "tenant": TenantSerializer(result["tenant"]).data,
                "user": UserSerializer(user).data,
                **_tokens_for_user(user),
            },
            status=201,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TenantLoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        return Response(
            {
                "tenant": TenantSerializer(user.tenant).data,
                "user": UserSerializer(user).data,
                **_tokens_for_user(user),
            }
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "tenant": TenantSerializer(request.user.tenant).data,
                "user": UserSerializer(request.user).data,
            }
        )
