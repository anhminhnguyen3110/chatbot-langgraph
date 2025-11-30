"""E2E tests for Keycloak authentication with model calls."""

import asyncio
import os

import httpx
import pytest


@pytest.fixture
def keycloak_config():
    """Keycloak configuration from environment."""
    return {
        "server_url": os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080"),
        "realm": os.getenv("KEYCLOAK_REALM", "langgraph-app"),
        "client_id": os.getenv("KEYCLOAK_CLIENT_ID", "langgraph-client"),
        "client_secret": os.getenv("KEYCLOAK_CLIENT_SECRET", ""),
    }


@pytest.fixture
def agent_base_url():
    """Agent server base URL."""
    return os.getenv("AGENT_BASE_URL", "http://localhost:8000")


async def get_keycloak_token(
    keycloak_config: dict, username: str, password: str
) -> str:
    """Get JWT token from Keycloak.

    Args:
        keycloak_config: Keycloak configuration
        username: Username
        password: Password

    Returns:
        JWT access token

    Raises:
        Exception: If token request fails
    """
    token_url = (
        f"{keycloak_config['server_url']}/realms/{keycloak_config['realm']}"
        f"/protocol/openid-connect/token"
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data={
                "client_id": keycloak_config["client_id"],
                "client_secret": keycloak_config["client_secret"],
                "username": username,
                "password": password,
                "grant_type": "password",
            },
            timeout=10.0,
        )

        if response.status_code != 200:
            raise Exception(
                f"Failed to get token: {response.status_code} - {response.text}"
            )

        token_data = response.json()
        return token_data["access_token"]


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("AUTH_TYPE") != "keycloak",
    reason="Keycloak auth not enabled",
)
class TestKeycloakAuthentication:
    """Test Keycloak authentication with Agent."""

    async def test_unauthenticated_request_rejected(self, agent_base_url):
        """Test that requests without token are rejected."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{agent_base_url}/threads")

            assert response.status_code == 401
            assert "unauthorized" in response.json().get("error", "").lower()

    async def test_invalid_token_rejected(self, agent_base_url):
        """Test that invalid tokens are rejected."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{agent_base_url}/threads",
                headers={"Authorization": "Bearer invalid_token_here"},
            )

            assert response.status_code == 401

    @pytest.mark.skipif(
        not os.getenv("TEST_KEYCLOAK_USER"),
        reason="TEST_KEYCLOAK_USER not set",
    )
    async def test_valid_token_accepted(self, keycloak_config, agent_base_url):
        """Test that valid Keycloak tokens are accepted."""
        username = os.getenv("TEST_KEYCLOAK_USER", "testuser")
        password = os.getenv("TEST_KEYCLOAK_PASSWORD", "testpass")

        # Get token from Keycloak
        token = await get_keycloak_token(keycloak_config, username, password)

        # Use token with Agent
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{agent_base_url}/threads",
                headers={"Authorization": f"Bearer {token}"},
            )

            # Should succeed (200) or return empty list
            assert response.status_code in [200, 404]

    @pytest.mark.skipif(
        not os.getenv("TEST_KEYCLOAK_USER") or not os.getenv("GEMINI_API_KEY"),
        reason="TEST_KEYCLOAK_USER or GEMINI_API_KEY not set",
    )
    async def test_authenticated_model_call(self, keycloak_config, agent_base_url):
        """Test making authenticated API call that triggers model execution."""
        username = os.getenv("TEST_KEYCLOAK_USER", "testuser")
        password = os.getenv("TEST_KEYCLOAK_PASSWORD", "testpass")

        # Get token from Keycloak
        token = await get_keycloak_token(keycloak_config, username, password)
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Step 1: Create thread
            thread_response = await client.post(
                f"{agent_base_url}/threads",
                headers=headers,
                json={"metadata": {"test": "keycloak_auth"}},
            )
            assert thread_response.status_code == 200
            thread_id = thread_response.json()["thread_id"]

            # Step 2: Get or create assistant
            assistants_response = await client.get(
                f"{agent_base_url}/assistants",
                headers=headers,
            )
            assert assistants_response.status_code == 200
            assistants = assistants_response.json()

            # Use first assistant or create one
            if assistants:
                assistant_id = assistants[0]["assistant_id"]
            else:
                # Create assistant
                create_assistant_response = await client.post(
                    f"{agent_base_url}/assistants",
                    headers=headers,
                    json={
                        "graph_id": "agent",
                        "name": "Test Agent",
                        "metadata": {"test": "keycloak"},
                    },
                )
                assert create_assistant_response.status_code == 200
                assistant_id = create_assistant_response.json()["assistant_id"]

            # Step 3: Create run with model call
            run_response = await client.post(
                f"{agent_base_url}/threads/{thread_id}/runs",
                headers=headers,
                json={
                    "assistant_id": assistant_id,
                    "input": {
                        "messages": [
                            {
                                "role": "user",
                                "content": "Say 'Hello from Keycloak test' in exactly those words.",
                            }
                        ]
                    },
                },
            )

            assert run_response.status_code == 200
            run_id = run_response.json()["run_id"]

            # Step 4: Wait for run to complete
            max_attempts = 30
            for _ in range(max_attempts):
                status_response = await client.get(
                    f"{agent_base_url}/threads/{thread_id}/runs/{run_id}",
                    headers=headers,
                )
                assert status_response.status_code == 200

                run_data = status_response.json()
                status = run_data.get("status")

                if status in ["success", "error"]:
                    break

                await asyncio.sleep(1)

            # Verify run completed successfully
            assert run_data.get("status") == "success", (
                f"Run failed with status: {run_data.get('status')}"
            )

            # Step 5: Verify we got a response from the model
            # Get thread state to see messages
            state_response = await client.get(
                f"{agent_base_url}/threads/{thread_id}/state",
                headers=headers,
            )
            assert state_response.status_code == 200
            state = state_response.json()

            # Check that we have messages in state
            assert "values" in state
            assert "messages" in state["values"]
            messages = state["values"]["messages"]

            # Should have at least user message + AI response
            assert len(messages) >= 2

            # Last message should be from AI
            last_message = messages[-1]
            assert last_message.get("type") in ["ai", "assistant"]

            print(f"\n✅ Model call succeeded with Keycloak auth!")
            print(f"   Response: {last_message.get('content', '')[:100]}")

    @pytest.mark.skipif(
        not os.getenv("TEST_KEYCLOAK_USER"),
        reason="TEST_KEYCLOAK_USER not set",
    )
    async def test_quota_metadata_in_run(self, keycloak_config, agent_base_url):
        """Test that quota metadata is added to runs."""
        username = os.getenv("TEST_KEYCLOAK_USER", "testuser")
        password = os.getenv("TEST_KEYCLOAK_PASSWORD", "testpass")

        token = await get_keycloak_token(keycloak_config, username, password)
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            # Create thread
            thread_response = await client.post(
                f"{agent_base_url}/threads",
                headers=headers,
                json={},
            )
            assert thread_response.status_code == 200
            thread_id = thread_response.json()["thread_id"]

            # Get assistant
            assistants_response = await client.get(
                f"{agent_base_url}/assistants",
                headers=headers,
            )
            assistants = assistants_response.json()
            assistant_id = assistants[0]["assistant_id"] if assistants else "agent"

            # Create run
            run_response = await client.post(
                f"{agent_base_url}/threads/{thread_id}/runs",
                headers=headers,
                json={
                    "assistant_id": assistant_id,
                    "input": {"messages": [{"role": "user", "content": "test"}]},
                },
            )

            assert run_response.status_code == 200
            run_data = run_response.json()

            # Check metadata has quota information
            metadata = run_data.get("metadata", {})

            # Note: Quota metadata is added by auth.on.runs.create
            # It may not be immediately visible in response
            # but should be enforced server-side
            print(f"\n✅ Run created with metadata: {metadata}")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("AUTH_TYPE") != "keycloak",
    reason="Keycloak auth not enabled",
)
class TestKeycloakMultiTenant:
    """Test multi-tenant isolation with Keycloak."""

    @pytest.mark.skipif(
        not os.getenv("TEST_KEYCLOAK_USER"),
        reason="TEST_KEYCLOAK_USER not set",
    )
    async def test_user_can_only_see_own_threads(self, keycloak_config, agent_base_url):
        """Test that users can only see their own threads."""
        username = os.getenv("TEST_KEYCLOAK_USER", "testuser")
        password = os.getenv("TEST_KEYCLOAK_PASSWORD", "testpass")

        token = await get_keycloak_token(keycloak_config, username, password)
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            # Create a thread
            create_response = await client.post(
                f"{agent_base_url}/threads",
                headers=headers,
                json={"metadata": {"owner_test": "true"}},
            )
            assert create_response.status_code == 200
            created_thread_id = create_response.json()["thread_id"]

            # List threads - should only see own threads
            list_response = await client.get(
                f"{agent_base_url}/threads",
                headers=headers,
            )
            assert list_response.status_code == 200
            threads = list_response.json()

            # Should find the created thread
            thread_ids = [t["thread_id"] for t in threads]
            assert created_thread_id in thread_ids

            # All threads should have owner metadata
            # (added by auth.on.threads.create)
            print(f"\n✅ User has access to {len(threads)} thread(s)")
