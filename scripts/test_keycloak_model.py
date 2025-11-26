#!/usr/bin/env python3
"""
Quick test script for Keycloak authentication with model calls.

This script:
1. Checks if Keycloak is running
2. Tries to get a token (simulated or real)
3. Makes API calls with authentication
4. Triggers a model call through the agent
5. Verifies the response

Usage:
    # With real Keycloak user
    export TEST_KEYCLOAK_USER=testuser
    export TEST_KEYCLOAK_PASSWORD=testpass
    python scripts/test_keycloak_model.py

    # Without real user (will test rejection only)
    python scripts/test_keycloak_model.py
"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
import structlog
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Setup logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger(__name__)


async def get_keycloak_token(username: str, password: str) -> str | None:
    """Get JWT token from Keycloak.
    
    Args:
        username: Keycloak username
        password: Keycloak password
        
    Returns:
        JWT access token or None if failed
    """
    keycloak_url = os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080")
    realm = os.getenv("KEYCLOAK_REALM", "langgraph-app")
    client_id = os.getenv("KEYCLOAK_CLIENT_ID", "langgraph-client")
    client_secret = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                    "grant_type": "password",
                },
                timeout=10.0,
            )

            if response.status_code == 200:
                token_data = response.json()
                logger.info("[OK] Got token from Keycloak", username=username)
                return token_data["access_token"]
            else:
                logger.error(
                    "Failed to get token",
                    status=response.status_code,
                    response=response.text[:200],
                )
                return None

    except Exception as e:
        logger.error(f"Keycloak connection failed: {e}")
        return None


async def test_unauthenticated_request():
    """Test that requests without token are rejected."""
    logger.info("=" * 60)
    logger.info("TEST 1: Unauthenticated Request")
    logger.info("=" * 60)

    agent_url = os.getenv("AGENT_BASE_URL", "http://localhost:8000")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{agent_url}/threads", timeout=5.0)

            if response.status_code == 401:
                logger.info("[OK] Unauthenticated request correctly rejected")
                logger.info(f"   Response: {response.json()}")
                return True
            else:
                logger.error(
                    f"[FAIL] Expected 401, got {response.status_code}"
                )
                return False

    except Exception as e:
        logger.error(f"[FAIL] Test failed: {e}")
        return False


async def test_authenticated_model_call(token: str):
    """Test making authenticated API call with model execution.
    
    Args:
        token: JWT access token
        
    Returns:
        True if test passed
    """
    logger.info("=" * 60)
    logger.info("TEST 2: Authenticated Model Call")
    logger.info("=" * 60)

    agent_url = os.getenv("AGENT_BASE_URL", "http://localhost:8000")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Step 1: Create thread
            logger.info("Creating thread...")
            thread_response = await client.post(
                f"{agent_url}/threads",
                headers=headers,
                json={"metadata": {"test": "keycloak_model_call"}},
            )

            if thread_response.status_code != 200:
                logger.error(
                    f"Failed to create thread: {thread_response.status_code}"
                )
                logger.error(f"Response: {thread_response.text}")
                return False

            thread_id = thread_response.json()["thread_id"]
            logger.info(f"[OK] Thread created: {thread_id}")

            # Step 2: Get assistants
            logger.info("Getting assistants...")
            assistants_response = await client.get(
                f"{agent_url}/assistants",
                headers=headers,
            )

            if assistants_response.status_code != 200:
                logger.error(f"Failed to get assistants: {assistants_response.status_code}")
                return False

            assistants = assistants_response.json()
            
            # Use first assistant or default to "agent"
            assistant_list = assistants.get("assistants", [])
            if assistant_list:
                assistant_id = assistant_list[0]["assistant_id"]
                logger.info(f"[OK] Using assistant: {assistant_id}")
            else:
                assistant_id = "agent"
                logger.info(f"[OK] Using default assistant: {assistant_id}")

            # Step 3: Create run with model call
            logger.info("Creating run with model call...")
            
            # Get model config from environment
            primary_model = os.getenv("PRIMARY_MODEL_ID", "google_genai/gemini-2.5-flash")
            
            run_response = await client.post(
                f"{agent_url}/threads/{thread_id}/runs",
                headers=headers,
                json={
                    "assistant_id": assistant_id,
                    "input": {
                        "messages": [
                            {
                                "role": "user",
                                "content": "Say exactly: 'Keycloak authentication test successful!'",
                            }
                        ]
                    },
                    "config": {
                        "configurable": {
                            "model": primary_model,
                        }
                    },
                },
            )

            if run_response.status_code != 200:
                logger.error(f"Failed to create run: {run_response.status_code}")
                logger.error(f"Response: {run_response.text}")
                return False

            run_id = run_response.json()["run_id"]
            logger.info(f"[OK] Run created: {run_id}")

            # Step 4: Wait for run to complete
            logger.info("Waiting for model response...")
            max_attempts = 30
            run_data = None

            for attempt in range(max_attempts):
                status_response = await client.get(
                    f"{agent_url}/threads/{thread_id}/runs/{run_id}",
                    headers=headers,
                )

                if status_response.status_code != 200:
                    logger.error(f"Failed to get run status: {status_response.status_code}")
                    return False

                run_data = status_response.json()
                status = run_data.get("status")

                logger.info(f"   Attempt {attempt + 1}/{max_attempts}: Status = {status}")

                if status in ["success", "error", "cancelled"]:
                    break

                await asyncio.sleep(2)

            # Step 5: Verify run completed successfully
            if not run_data or run_data.get("status") != "success":
                logger.error(f"[FAIL] Run failed with status: {run_data.get('status') if run_data else 'unknown'}")
                if run_data:
                    logger.error(f"   Run data: {run_data}")
                return False

            logger.info("[OK] Run completed successfully!")

            # Step 6: Get thread state to see messages
            logger.info("Getting thread state...")
            state_response = await client.get(
                f"{agent_url}/threads/{thread_id}/state",
                headers=headers,
            )

            if state_response.status_code != 200:
                logger.error(f"Failed to get state: {state_response.status_code}")
                return False

            state = state_response.json()

            # Check messages
            if "values" in state and "messages" in state["values"]:
                messages = state["values"]["messages"]
                logger.info(f"[OK] Got {len(messages)} message(s)")

                # Show last message (AI response)
                if messages:
                    last_message = messages[-1]
                    content = last_message.get("content", "")
                    logger.info(f"\n📝 AI Response:")
                    logger.info(f"   {content[:200]}")

                return True
            else:
                logger.error("[FAIL] No messages in state")
                return False

    except Exception as e:
        logger.error(f"[FAIL] Test failed: {e}", exc_info=True)
        return False


async def main():
    """Run all tests."""
    logger.info("\n")
    logger.info("Keycloak Authentication + Model Call Test")
    logger.info("\n")

    # Check environment
    auth_type = os.getenv("AUTH_TYPE", "noop")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    logger.info(f"AUTH_TYPE: {auth_type}")
    logger.info(f"GEMINI_API_KEY: {'[OK] Set' if gemini_key else '[FAIL] Not set'}")
    logger.info("\n")

    if auth_type != "keycloak":
        logger.error("[FAIL] AUTH_TYPE must be 'keycloak' for this test")
        logger.info("   Set AUTH_TYPE=keycloak in your .env file")
        return 1

    if not gemini_key:
        logger.error("[FAIL] GEMINI_API_KEY not set")
        logger.info("   Add GEMINI_API_KEY to your .env file")
        return 1

    # Test 1: Unauthenticated request
    test1_passed = await test_unauthenticated_request()

    # Test 2: Authenticated model call
    test2_passed = False
    username = os.getenv("TEST_KEYCLOAK_USER")
    password = os.getenv("TEST_KEYCLOAK_PASSWORD")

    if username and password:
        logger.info("\n")
        logger.info(f"Getting token for user: {username}")
        token = await get_keycloak_token(username, password)

        if token:
            test2_passed = await test_authenticated_model_call(token)
        else:
            logger.error("[FAIL] Failed to get Keycloak token")
            logger.info("   Make sure:")
            logger.info("   1. Keycloak is running (docker compose -f docker-compose.keycloak.yml up)")
            logger.info("   2. Realm 'langgraph-app' is created")
            logger.info("   3. User exists with correct password")
    else:
        logger.warning("⚠️  TEST_KEYCLOAK_USER or TEST_KEYCLOAK_PASSWORD not set")
        logger.info("   Skipping authenticated model call test")
        logger.info("   To run full test:")
        logger.info("   export TEST_KEYCLOAK_USER=testuser")
        logger.info("   export TEST_KEYCLOAK_PASSWORD=testpass")

    # Summary
    logger.info("\n")
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"{'[OK] PASS' if test1_passed else '[FAIL] FAIL'} - Unauthenticated Request Rejected")
    
    if username and password:
        logger.info(f"{'[OK] PASS' if test2_passed else '[FAIL] FAIL'} - Authenticated Model Call")
    else:
        logger.info("⏭️  SKIP - Authenticated Model Call (no credentials)")

    logger.info("=" * 60)

    if test1_passed and (test2_passed or not (username and password)):
        logger.info("🎉 All tests passed!")
        return 0
    else:
        logger.error("[FAIL] Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
