#!/usr/bin/env python3
"""Generador de JWT tokens para testing y demo"""
import sys
from datetime import UTC, datetime, timedelta

from jose import jwt

from data_platform.core.config import settings

# Scopes disponibles
SCOPES = {
    "admin": ["admin", "sources:read", "sources:write", "pipelines:read", "pipelines:write", "analysis:read", "analysis:write"],
    "analyst": ["sources:read", "pipelines:read", "analysis:read", "analysis:write"],
    "operator": ["sources:read", "pipelines:read", "pipelines:write"],
    "viewer": ["sources:read", "pipelines:read", "analysis:read"],
}


def generate_token(
    subject: str = "demo-user",
    role: str = "analyst",
    custom_scopes: list[str] | None = None,
    expires_hours: int = 24,
) -> str:
    """
    Genera un JWT token firmado con HS256.

    Args:
        subject: Identificador del usuario (sub claim)
        role: Rol predefinido (admin, analyst, operator, viewer)
        custom_scopes: Scopes personalizados (sobrescribe role)
        expires_hours: Horas hasta expiración
    """
    scopes = custom_scopes if custom_scopes is not None else SCOPES.get(role, SCOPES["analyst"])

    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "scopes": scopes,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decodifica y valida un token"""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Genera JWT tokens para la Plataforma Agéntica")
    parser.add_argument("-u", "--user", default="demo-user", help="Subject/user ID")
    parser.add_argument("-r", "--role", choices=list(SCOPES.keys()), default="analyst", help="Rol predefinido")
    parser.add_argument("-s", "--scopes", nargs="+", help="Scopes personalizados (ej: analysis:read sources:write)")
    parser.add_argument("-e", "--expire", type=int, default=24, help="Horas de expiración")
    parser.add_argument("-d", "--decode", help="Decodificar token existente")
    parser.add_argument("--curl", action="store_true", help="Mostrar comando curl de ejemplo")

    args = parser.parse_args()

    if args.decode:
        result = decode_token(args.decode)
        print("Decoded payload:")
        for k, v in result.items():
            print(f"  {k}: {v}")
        sys.exit(0)

    token = generate_token(
        subject=args.user,
        role=args.role,
        custom_scopes=args.scopes,
        expires_hours=args.expire,
    )

    print(f"🔐 JWT Token ({args.role}, {args.expire}h):")
    print(token)
    print()

    # Verificar
    payload = decode_token(token)
    print("Payload:")
    for k, v in payload.items():
        print(f"  {k}: {v}")
    print()

    if args.curl:
        print("📋 Ejemplo curl:")
        print('curl -X POST http://localhost:8000/analysis/ask \\')
        print(f'  -H "Authorization: Bearer {token}" \\')
        print('  -H "X-Client-ID: demo" \\')
        print('  -d \'{"question": "Ventas por canal última semana"}\'')
