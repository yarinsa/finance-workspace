"""Settings for the ledger API, read from the environment (never from .env: compose passes them)."""
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger("finance_api")


class ConfigError(RuntimeError):
    """The API refuses to start with an unsafe or incomplete configuration."""


@dataclass(frozen=True)
class Settings:
    origin_secret: str
    allowed_emails: frozenset = field(default_factory=frozenset)
    cognito_region: str = ""
    cognito_pool_id: str = ""
    cognito_client_id: str = ""
    dev_user: str | None = None
    database_url: str = ""
    temporal_address: str = "localhost:7233"

    @property
    def issuer(self):
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_pool_id}"

    @property
    def jwks_url(self):
        return f"{self.issuer}/.well-known/jwks.json"

    def validate(self):
        """Raise ConfigError for anything that would leave the API open or unusable."""
        if not self.origin_secret:
            raise ConfigError("FINANCE_API_ORIGIN_SECRET is not set: refusing to start without an origin secret")
        if self.dev_user:
            log.warning("FINANCE_API_DEV_USER is set: JWT checks are bypassed (the origin secret is still "
                        "required). Never use this outside local development.")
        else:
            missing = [n for n, v in (("FINANCE_API_COGNITO_REGION", self.cognito_region),
                                      ("FINANCE_API_COGNITO_POOL_ID", self.cognito_pool_id),
                                      ("FINANCE_API_COGNITO_CLIENT_ID", self.cognito_client_id),
                                      ("FINANCE_API_ALLOWED_EMAILS", self.allowed_emails)) if not v]
            if missing:
                raise ConfigError(f"missing {', '.join(missing)}: refusing to start without JWT verification")
        return self

    @classmethod
    def from_env(cls, env=os.environ):
        emails = frozenset(e.strip().lower() for e in env.get("FINANCE_API_ALLOWED_EMAILS", "").split(",")
                           if e.strip())
        return cls(
            origin_secret=env.get("FINANCE_API_ORIGIN_SECRET", ""),
            allowed_emails=emails,
            cognito_region=env.get("FINANCE_API_COGNITO_REGION", ""),
            cognito_pool_id=env.get("FINANCE_API_COGNITO_POOL_ID", ""),
            cognito_client_id=env.get("FINANCE_API_COGNITO_CLIENT_ID", ""),
            dev_user=(env.get("FINANCE_API_DEV_USER") or "").strip().lower() or None,
            database_url=env.get("API_DATABASE_URL", ""),
            temporal_address=env.get("TEMPORAL_ADDRESS", "localhost:7233"),
        ).validate()
