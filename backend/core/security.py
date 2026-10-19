"""Phase 5: Supabase Auth JWT verification for authenticated FastAPI routes.

Supabase (GoTrue) issues access tokens as asymmetrically signed JWTs (RS256 or
ES256). The signing public keys are published at `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`.
The frontend's `@supabase/ssr` cookie session attaches this token as
`Authorization: Bearer <token>` on every request to this backend (see
`frontend/lib/api.ts`); this module is the only place that token is decoded
and trusted.

We deliberately verify the signature/expiry/audience server-side with PyJWT
and the Supabase JWKS endpoint rather than trusting a client-supplied user id
in the request body — the `sub` claim extracted here is the *only* source of
truth for "who is making this request" throughout the backend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException

from core.config import settings

logger = logging.getLogger(__name__)

# Supabase access tokens are issued with RS256 or ES256 (asymmetric JWKS).
SUPABASE_JWT_AUDIENCE = "authenticated"
SUPABASE_JWT_ALGORITHMS = ["RS256", "ES256"]

_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    """Return a module-level JWKS client so keys are fetched once and cached."""
    global _jwks_client
    if _jwks_client is None:
        if not settings.supabase_url:
            logger.error("SUPABASE_URL is not configured; cannot verify auth tokens")
            raise HTTPException(status_code=500, detail="Server authentication is not configured")
        jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        _jwks_client = jwt.PyJWKClient(jwks_url)
    return _jwks_client


@dataclass(frozen=True)
class AuthenticatedUser:
    """The authenticated principal for a request, derived from a verified
    Supabase JWT. `user_id` is the Supabase `auth.uid()` value (the JWT's
    `sub` claim) and is what every downstream Supabase query (profiles,
    sessions, chats) is scoped to.
    """

    user_id: str
    email: str | None = None


def _decode_supabase_jwt(token: str) -> dict:
    """Verifies and decodes a Supabase access token, raising `HTTPException`
    (never a raw PyJWT error) on any failure so route handlers don't need
    their own try/except around this.
    """
    jwks_client = _get_jwks_client()

    try:
        jwt.get_unverified_header(token)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=SUPABASE_JWT_ALGORITHMS,
            audience=SUPABASE_JWT_AUDIENCE,
        )
    except jwt.ExpiredSignatureError as exc:
        logger.error("[Auth Error] Token expired: %s", exc)
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.InvalidAudienceError as exc:
        logger.error(
            "[Auth Error] Invalid audience (expected %s): %s",
            SUPABASE_JWT_AUDIENCE,
            exc,
        )
        raise HTTPException(
            status_code=401,
            detail=f"Invalid session token: {exc}",
        ) from exc
    except jwt.InvalidTokenError as exc:
        logger.error("[Auth Error] Invalid token: %s", exc)
        raise HTTPException(
            status_code=401,
            detail=f"Invalid session token: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("[Auth Error] Unexpected auth failure: %s", exc)
        raise HTTPException(status_code=401, detail="Authentication failed") from exc


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    auth_header = authorization.strip()
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header must be of the form 'Bearer <token>'",
        )

    token = auth_header.replace("Bearer ", "", 1).replace("bearer ", "", 1).strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authorization header must be of the form 'Bearer <token>'",
        )
    return token


async def get_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    """FastAPI dependency that requires and verifies a Supabase session.

    Use as `user: AuthenticatedUser = Depends(get_current_user)` on any
    route that must be scoped to a signed-in user. Raises 401 if the header
    is missing/malformed or the token fails signature, expiry, or audience
    verification.
    """
    token = _extract_bearer_token(authorization)
    claims = _decode_supabase_jwt(token)

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token is missing a subject (sub) claim")

    return AuthenticatedUser(user_id=user_id, email=claims.get("email"))
