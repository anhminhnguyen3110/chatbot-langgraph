"""Security module for authentication and authorization."""

from .keycloak_client import validate_keycloak_token

__all__ = ["validate_keycloak_token"]
