"""Keycloak JWT validation and user info extraction.

This module provides integration with Keycloak for authentication.
It validates JWT tokens via Keycloak's userinfo endpoint and extracts
user claims including custom attributes like plan tier and quotas.
"""

import os  # pragma: no cover
from typing import Any  # pragma: no cover

import httpx  # pragma: no cover
import jwt  # pragma: no cover
import structlog  # pragma: no cover

logger = structlog.getLogger(__name__)  # pragma: no cover

# Keycloak configuration from environment
KEYCLOAK_SERVER_URL = os.getenv(
    "KEYCLOAK_SERVER_URL", "http://localhost:8080"
)  # pragma: no cover
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "langgraph-app")  # pragma: no cover
KEYCLOAK_CLIENT_ID = os.getenv(
    "KEYCLOAK_CLIENT_ID", "langgraph-client"
)  # pragma: no cover
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")  # pragma: no cover


async def validate_keycloak_token(token: str) -> dict[str, Any]:  # pragma: no cover
    """Validate JWT token with Keycloak userinfo endpoint.

    This function attempts to validate the token by calling Keycloak's
    userinfo endpoint. If that fails, it falls back to decoding the JWT
    locally (without signature verification for development).

    Args:
        token: JWT access token (without "Bearer " prefix)

    Returns:
        Dictionary containing user information:
        - sub: User ID
        - email: User email
        - preferred_username: Username
        - user_plan: Plan tier (free/pro/enterprise) - from custom claims
        - max_tool_calls_per_request: Tool call quota - from custom claims
        - max_model_calls_per_request: Model call quota - from custom claims
        - mcp_tools_enabled: MCP tools access - from custom claims

    Raises:
        ValueError: If token is invalid or cannot be validated
    """
    # Construct Keycloak userinfo endpoint URL
    userinfo_url = f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/userinfo"

    try:
        # Try to validate via Keycloak userinfo endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )

            if response.status_code == 200:
                user_info = response.json()
                logger.info(
                    "Token validated via Keycloak userinfo",
                    user_id=user_info.get("sub"),
                )
                return _extract_user_claims(user_info)

            logger.warning(
                "Keycloak userinfo endpoint returned error",
                status_code=response.status_code,
            )

    except httpx.RequestError as e:
        logger.warning(
            "Failed to connect to Keycloak userinfo endpoint",
            error=str(e),
        )

    # Fallback: Decode JWT locally (without verification for development)
    # In production, you should verify the signature using Keycloak's public key
    try:
        # Decode without verification (for development only)
        # TODO: In production, fetch and use Keycloak's public key for verification
        decoded = jwt.decode(
            token,
            options={"verify_signature": False},  # Development only!
            algorithms=["RS256"],
        )

        logger.info(
            "Token decoded locally (fallback mode)",
            user_id=decoded.get("sub"),
        )
        return _extract_user_claims(decoded)

    except jwt.InvalidTokenError as e:
        logger.error("Invalid JWT token", error=str(e))
        raise ValueError(f"Invalid JWT token: {e}") from e


def _extract_user_claims(token_data: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize user claims from token data.

    This function handles both userinfo endpoint responses and
    decoded JWT payloads, extracting standard and custom claims.

    Args:
        token_data: Raw token data from userinfo or JWT decode

    Returns:
        Normalized user claims dictionary
    """
    # Extract standard OIDC claims
    user_claims = {
        "sub": token_data.get("sub"),
        "email": token_data.get("email"),
        "preferred_username": token_data.get("preferred_username"),
        "email_verified": token_data.get("email_verified", False),
        "name": token_data.get("name"),
    }

    # Extract custom claims (these would be configured in Keycloak)
    # Default values for development
    user_claims["user_plan"] = token_data.get("user_plan", "free")
    user_claims["max_tool_calls_per_request"] = token_data.get(
        "max_tool_calls_per_request", 20
    )
    user_claims["max_model_calls_per_request"] = token_data.get(
        "max_model_calls_per_request", 20
    )
    user_claims["mcp_tools_enabled"] = token_data.get("mcp_tools_enabled", True)

    # Extract roles if present
    resource_access = token_data.get("resource_access", {})
    client_roles = resource_access.get(KEYCLOAK_CLIENT_ID, {}).get("roles", [])
    user_claims["roles"] = client_roles

    # Add any custom attributes from Keycloak user profile
    if "attributes" in token_data:
        user_claims["attributes"] = token_data["attributes"]

    return user_claims
