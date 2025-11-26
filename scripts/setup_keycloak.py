#!/usr/bin/env python3
"""
Setup Keycloak for Agent testing.

This script configures Keycloak with:
1. Realm: langgraph-app
2. Client: langgraph-client
3. Test user with attributes

Usage:
    python scripts/setup_keycloak.py
"""

import asyncio
import os

import httpx
import structlog
from dotenv import load_dotenv

load_dotenv()

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger(__name__)


async def get_admin_token(keycloak_url: str) -> str | None:
    """Get admin access token from Keycloak.
    
    Args:
        keycloak_url: Keycloak server URL
        
    Returns:
        Admin access token or None if failed
    """
    token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": "admin-cli",
                    "username": "admin",
                    "password": "admin",
                    "grant_type": "password",
                },
                timeout=10.0,
            )

            if response.status_code == 200:
                return response.json()["access_token"]
            else:
                logger.error(f"Failed to get admin token: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return None

    except Exception as e:
        logger.error(f"Failed to connect to Keycloak: {e}")
        return None


async def create_realm(keycloak_url: str, token: str, realm_name: str) -> bool:
    """Create realm in Keycloak.
    
    Args:
        keycloak_url: Keycloak server URL
        token: Admin access token
        realm_name: Realm name to create
        
    Returns:
        True if successful
    """
    try:
        async with httpx.AsyncClient() as client:
            # Check if realm exists
            check_response = await client.get(
                f"{keycloak_url}/admin/realms/{realm_name}",
                headers={"Authorization": f"Bearer {token}"},
            )

            if check_response.status_code == 200:
                logger.info(f"✅ Realm '{realm_name}' already exists")
                return True

            # Create realm
            response = await client.post(
                f"{keycloak_url}/admin/realms",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "realm": realm_name,
                    "enabled": True,
                },
            )

            if response.status_code in [201, 409]:
                logger.info(f"✅ Realm '{realm_name}' created")
                return True
            else:
                logger.error(f"Failed to create realm: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False

    except Exception as e:
        logger.error(f"Failed to create realm: {e}")
        return False


async def create_client(
    keycloak_url: str, token: str, realm_name: str, client_id: str
) -> tuple[bool, str | None]:
    """Create client in Keycloak.
    
    Args:
        keycloak_url: Keycloak server URL
        token: Admin access token
        realm_name: Realm name
        client_id: Client ID to create
        
    Returns:
        Tuple of (success, client_secret)
    """
    try:
        async with httpx.AsyncClient() as client:
            # Check if client exists
            clients_response = await client.get(
                f"{keycloak_url}/admin/realms/{realm_name}/clients",
                headers={"Authorization": f"Bearer {token}"},
                params={"clientId": client_id},
            )

            if clients_response.status_code == 200:
                existing_clients = clients_response.json()
                if existing_clients:
                    logger.info(f"✅ Client '{client_id}' already exists")
                    # Get secret
                    client_uuid = existing_clients[0]["id"]
                    secret_response = await client.get(
                        f"{keycloak_url}/admin/realms/{realm_name}/clients/{client_uuid}/client-secret",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if secret_response.status_code == 200:
                        secret = secret_response.json().get("value")
                        return True, secret
                    return True, None

            # Create client
            create_response = await client.post(
                f"{keycloak_url}/admin/realms/{realm_name}/clients",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "clientId": client_id,
                    "enabled": True,
                    "publicClient": False,
                    "serviceAccountsEnabled": True,
                    "directAccessGrantsEnabled": True,
                    "standardFlowEnabled": True,
                },
            )

            if create_response.status_code == 201:
                logger.info(f"✅ Client '{client_id}' created")

                # Get client UUID from location header or fetch
                clients_response = await client.get(
                    f"{keycloak_url}/admin/realms/{realm_name}/clients",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"clientId": client_id},
                )

                if clients_response.status_code == 200:
                    clients = clients_response.json()
                    if clients:
                        client_uuid = clients[0]["id"]

                        # Get client secret
                        secret_response = await client.get(
                            f"{keycloak_url}/admin/realms/{realm_name}/clients/{client_uuid}/client-secret",
                            headers={"Authorization": f"Bearer {token}"},
                        )

                        if secret_response.status_code == 200:
                            secret = secret_response.json().get("value")
                            logger.info(f"   Client secret: {secret}")
                            return True, secret

                return True, None
            else:
                logger.error(f"Failed to create client: {create_response.status_code}")
                logger.error(f"Response: {create_response.text}")
                return False, None

    except Exception as e:
        logger.error(f"Failed to create client: {e}")
        return False, None


async def create_user(
    keycloak_url: str,
    token: str,
    realm_name: str,
    username: str,
    password: str,
) -> bool:
    """Create user in Keycloak with attributes.
    
    Args:
        keycloak_url: Keycloak server URL
        token: Admin access token
        realm_name: Realm name
        username: Username
        password: Password
        
    Returns:
        True if successful
    """
    try:
        async with httpx.AsyncClient() as client:
            # Check if user exists
            users_response = await client.get(
                f"{keycloak_url}/admin/realms/{realm_name}/users",
                headers={"Authorization": f"Bearer {token}"},
                params={"username": username},
            )

            if users_response.status_code == 200:
                existing_users = users_response.json()
                if existing_users:
                    logger.info(f"✅ User '{username}' already exists")
                    return True

            # Create user
            create_response = await client.post(
                f"{keycloak_url}/admin/realms/{realm_name}/users",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "username": username,
                    "enabled": True,
                    "emailVerified": True,
                    "firstName": "Test",
                    "lastName": "User",
                    "email": f"{username}@example.com",
                    "attributes": {
                        "user_plan": ["pro"],
                        "max_tool_calls_per_request": ["50"],
                        "max_model_calls_per_request": ["30"],
                        "mcp_tools_enabled": ["true"],
                    },
                    "credentials": [
                        {
                            "type": "password",
                            "value": password,
                            "temporary": False,
                        }
                    ],
                },
            )

            if create_response.status_code in [201, 409]:
                logger.info(f"✅ User '{username}' created with password '{password}'")
                logger.info(f"   Attributes: Pro plan, 50 tool calls, 30 model calls")
                return True
            else:
                logger.error(f"Failed to create user: {create_response.status_code}")
                logger.error(f"Response: {create_response.text}")
                return False

    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        return False


async def main():
    """Setup Keycloak for testing."""
    logger.info("\n🚀 Setting up Keycloak for Agent\n")

    keycloak_url = os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080")
    realm_name = os.getenv("KEYCLOAK_REALM", "langgraph-app")
    client_id = os.getenv("KEYCLOAK_CLIENT_ID", "langgraph-client")
    test_username = os.getenv("TEST_KEYCLOAK_USER", "testuser")
    test_password = os.getenv("TEST_KEYCLOAK_PASSWORD", "testpass")

    logger.info(f"Keycloak URL: {keycloak_url}")
    logger.info(f"Realm: {realm_name}")
    logger.info(f"Client ID: {client_id}")
    logger.info(f"Test user: {test_username}\n")

    # Step 1: Get admin token
    logger.info("Step 1: Getting admin token...")
    token = await get_admin_token(keycloak_url)
    if not token:
        logger.error("❌ Failed to get admin token")
        logger.info("   Make sure Keycloak is running:")
        logger.info("   docker compose -f docker-compose.keycloak.yml up -d")
        return 1

    logger.info("✅ Got admin token\n")

    # Step 2: Create realm
    logger.info(f"Step 2: Creating realm '{realm_name}'...")
    if not await create_realm(keycloak_url, token, realm_name):
        return 1
    logger.info("")

    # Step 3: Create client
    logger.info(f"Step 3: Creating client '{client_id}'...")
    success, client_secret = await create_client(
        keycloak_url, token, realm_name, client_id
    )
    if not success:
        return 1
    logger.info("")

    # Step 4: Create user
    logger.info(f"Step 4: Creating user '{test_username}'...")
    if not await create_user(
        keycloak_url, token, realm_name, test_username, test_password
    ):
        return 1
    logger.info("")

    # Summary
    logger.info("=" * 60)
    logger.info("✅ Keycloak setup complete!")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Update your .env file:")
    logger.info(f"KEYCLOAK_CLIENT_SECRET={client_secret}")
    logger.info(f"TEST_KEYCLOAK_USER={test_username}")
    logger.info(f"TEST_KEYCLOAK_PASSWORD={test_password}")
    logger.info("")
    logger.info("Test authentication:")
    logger.info("python scripts/test_keycloak_model.py")
    logger.info("")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
