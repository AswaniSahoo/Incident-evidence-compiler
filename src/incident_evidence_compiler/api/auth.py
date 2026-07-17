"""Static bearer-token authentication (ADR 0007).

A ``TokenRegistry`` maps opaque bearer tokens to tenant identifiers. This is deliberately
not a full identity system: tokens are supplied by configuration/environment and map to a
``TenantId`` used to scope every query. Tokens are never logged.
"""

from collections.abc import Mapping

from ..domain.identifiers import TenantId


class TokenRegistry:
    """An immutable bearer-token -> tenant mapping."""

    def __init__(self, tokens: Mapping[str, TenantId]) -> None:
        self._tokens = dict(tokens)

    def tenant_for(self, token: str) -> TenantId | None:
        return self._tokens.get(token)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> "TokenRegistry":
        """Build a registry from a plain ``{token: tenant_id}`` configuration mapping."""
        return cls({token: TenantId(value) for token, value in mapping.items()})
