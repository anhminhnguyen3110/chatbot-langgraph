"""
Authentication configuration for LangGraph Agent Server.

This module provides environment-based authentication switching between:
- noop: No authentication (allow all requests)
- custom: Custom authentication integration
- keycloak: Keycloak JWT authentication with resource-level authorization

Set AUTH_TYPE environment variable to choose authentication mode.
"""

import os
from typing import Any

import structlog
from langgraph_sdk import Auth

logger = structlog.getLogger(__name__)

# Initialize LangGraph Auth instance
auth = Auth()

# Get authentication type from environment
AUTH_TYPE = os.getenv("AUTH_TYPE", "noop").lower()

if AUTH_TYPE == "noop":
    logger.info("Using noop authentication (no auth required)")

    @auth.authenticate
    async def authenticate(headers: dict[str, str]) -> Auth.types.MinimalUserDict:
        """No-op authentication that allows all requests."""
        _ = headers  # Suppress unused warning
        return {
            "identity": "anonymous",
            "display_name": "Anonymous User",
            "is_authenticated": True,
        }

    @auth.on
    async def authorize(
        ctx: Auth.types.AuthContext, value: dict[str, Any]
    ) -> dict[str, Any]:
        """No-op authorization that allows access to all resources."""
        _ = ctx, value  # Suppress unused warnings
        return {}  # Empty filter = no access restrictions

elif AUTH_TYPE == "custom":
    logger.info("Using custom authentication")

    @auth.authenticate
    async def authenticate(headers: dict[str, str]) -> Auth.types.MinimalUserDict:
        """
        Custom authentication handler.

        Modify this function to integrate with your authentication service.
        """
        # Extract authorization header
        authorization = (
            headers.get("authorization")
            or headers.get("Authorization")
            or headers.get(b"authorization")
            or headers.get(b"Authorization")
        )

        # Handle bytes headers
        if isinstance(authorization, bytes):
            authorization = authorization.decode("utf-8")

        if not authorization:
            logger.warning("Missing Authorization header")
            raise Auth.exceptions.HTTPException(
                status_code=401, detail="Authorization header required"
            )

        # Development token for testing
        if authorization == "Bearer dev-token":
            return {
                "identity": "dev-user",
                "display_name": "Development User",
                "email": "dev@example.com",
                "permissions": ["admin"],
                "org_id": "dev-org",
                "is_authenticated": True,
            }

        # Example: Simple API key validation (replace with your logic)
        if authorization.startswith("Bearer "):
            # TODO: Replace with your auth service integration
            logger.warning("Invalid token")
            raise Auth.exceptions.HTTPException(
                status_code=401, detail="Invalid authentication token"
            )

        # Reject requests without proper format
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Invalid authorization format. Expected 'Bearer <token>'",
        )

    @auth.on
    async def authorize(
        ctx: Auth.types.AuthContext, value: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Multi-tenant authorization with user-scoped access control.
        """
        try:
            # Get user identity from authentication context
            user_id = ctx.user.identity

            if not user_id:
                logger.error("Missing user identity in auth context")
                raise Auth.exceptions.HTTPException(
                    status_code=401, detail="Invalid user identity"
                )

            # Create owner filter for resource access control
            owner_filter = {"owner": user_id}

            # Add owner information to metadata for create/update operations
            metadata = value.setdefault("metadata", {})
            metadata.update(owner_filter)

            # Return filter for database operations
            return owner_filter

        except Auth.exceptions.HTTPException:
            raise
        except Exception as e:
            logger.error(f"Authorization error: {e}", exc_info=True)
            raise Auth.exceptions.HTTPException(
                status_code=500, detail="Authorization system error"
            ) from e

elif AUTH_TYPE == "keycloak":
    logger.info("Using Keycloak authentication with quota enforcement")

    # Import Keycloak client
    from src.agent_server.security.keycloak_client import validate_keycloak_token

    @auth.authenticate
    async def authenticate(headers: dict[str, str]) -> Auth.types.MinimalUserDict:
        """
        Keycloak JWT authentication handler.

        Validates JWT tokens with Keycloak and extracts user claims.
        """
        # Extract authorization header
        authorization = (
            headers.get("authorization")
            or headers.get("Authorization")
            or headers.get("x-api-key")
            or headers.get("X-Api-Key")
            or headers.get(b"authorization")
            or headers.get(b"Authorization")
        )

        # Handle bytes headers
        if isinstance(authorization, bytes):
            authorization = authorization.decode("utf-8")

        if not authorization:
            logger.warning("Missing Authorization header")
            raise Auth.exceptions.HTTPException(
                status_code=401, detail="Authorization header required"
            )

        # Extract token from Bearer format
        token = None
        if authorization.startswith("Bearer "):
            token = authorization[7:]  # Remove "Bearer " prefix
        else:
            # Support direct token for X-Api-Key compatibility
            token = authorization

        if not token:
            raise Auth.exceptions.HTTPException(
                status_code=401, detail="Invalid authorization format"
            )

        # Validate with Keycloak
        try:
            user_claims = await validate_keycloak_token(token)

            # Map Keycloak claims to LangGraph user format
            return {
                "identity": user_claims["sub"],
                "display_name": user_claims.get("name")
                or user_claims.get("preferred_username")
                or "Unknown User",
                "is_authenticated": True,
                # Store additional claims for quota enforcement
                "email": user_claims.get("email"),
                "user_plan": user_claims.get("user_plan", "free"),
                "max_tool_calls_per_request": user_claims.get(
                    "max_tool_calls_per_request", 20
                ),
                "max_model_calls_per_request": user_claims.get(
                    "max_model_calls_per_request", 20
                ),
                "mcp_tools_enabled": user_claims.get("mcp_tools_enabled", True),
                "roles": user_claims.get("roles", []),
            }

        except ValueError as e:
            logger.warning(f"Keycloak token validation failed: {e}")
            raise Auth.exceptions.HTTPException(
                status_code=401, detail=f"Invalid authentication token: {e}"
            ) from e

    @auth.on.threads.create
    async def on_thread_create(ctx: Auth.types.AuthContext, _value: dict[str, Any]):
        """Add owner metadata to new threads"""
        user_id = ctx.user.identity
        metadata = _value.setdefault("metadata", {})
        metadata["owner"] = user_id
        logger.debug(f"Thread creation by user: {user_id}")

    @auth.on.threads.read
    async def on_thread_read(ctx: Auth.types.AuthContext, _value: dict[str, Any]):
        """Verify thread ownership before read"""
        user_id = ctx.user.identity
        # Return filter to only show user's own threads
        return {"owner": user_id}

    @auth.on.threads.update
    async def on_thread_update(ctx: Auth.types.AuthContext, _value: dict[str, Any]):
        """Verify ownership before update"""
        user_id = ctx.user.identity
        return {"owner": user_id}

    @auth.on.threads.delete
    async def on_thread_delete(ctx: Auth.types.AuthContext, _value: dict[str, Any]):
        """Verify ownership before delete"""
        user_id = ctx.user.identity
        return {"owner": user_id}

else:
    raise ValueError(
        f"Unknown AUTH_TYPE: {AUTH_TYPE}. Supported values: 'noop', 'custom', 'keycloak'"
    )
