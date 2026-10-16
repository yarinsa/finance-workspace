"""Request authentication for the ledger API.

Three layers, in this order (see docs/ledger-api.md, Safety model):

1. `check_origin`  `X-Origin-Secret` header, constant-time compare. Applies to every route.
2. `current_user`  the Cognito id token in the `plangram_session` cookie (RS256 via the
                   pool's JWKS), and the email must be on the allow list. Returns the email,
                   which is the audit actor. `FINANCE_API_DEV_USER` skips only this step.
3. `check_csrf`    writes need `Content-Type: application/json` and `X-Requested-With: finance-app`.
"""
import hmac
import logging

import jwt
from fastapi import Request

from .errors import ApiError

log = logging.getLogger("finance_api")

COOKIE = "plangram_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "finance-app"


class TokenVerifier:
    """Verifies a Cognito id token. `jwk_client` is injectable so tests never call AWS."""

    def __init__(self, settings, jwk_client=None):
        self.settings = settings
        self._jwks = jwk_client or jwt.PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=3600)

    def email(self, token):
        """The verified, lower-cased email in `token`. Raises ApiError 401 if it is not valid."""
        s = self.settings
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=s.cognito_client_id,
                                issuer=s.issuer, options={"require": ["exp", "iss", "aud"]})
        except jwt.PyJWTError as e:
            log.info("rejected token: %s", type(e).__name__)
            raise ApiError(401, "unauthenticated", "invalid or expired session") from None
        if claims.get("token_use") != "id":
            raise ApiError(401, "unauthenticated", "not an id token")
        email = str(claims.get("email") or "").lower()
        if not email:
            raise ApiError(401, "unauthenticated", "token has no email")
        return email


def check_origin(request: Request):
    """Reject anything that did not come through CloudFront (which adds the secret)."""
    given = request.headers.get("x-origin-secret", "")
    expected = request.app.state.settings.origin_secret
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise ApiError(403, "forbidden", "missing or wrong origin secret")


def current_user(request: Request):
    """The signed-in, allow-listed user's email (the audit actor)."""
    settings = request.app.state.settings
    if settings.dev_user:
        return settings.dev_user
    token = request.cookies.get(COOKIE)
    if not token:
        raise ApiError(401, "unauthenticated", "no session cookie")
    email = request.app.state.verifier.email(token)
    if email not in settings.allowed_emails:
        raise ApiError(403, "forbidden", "this account may not use the ledger API")
    return email


def check_csrf(request: Request):
    """Writes must be same-origin JSON from the app: a form post or foreign page cannot send these."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise ApiError(403, "csrf", "writes require Content-Type: application/json")
    if request.headers.get(CSRF_HEADER, "") != CSRF_VALUE:
        raise ApiError(403, "csrf", "writes require X-Requested-With: finance-app")
