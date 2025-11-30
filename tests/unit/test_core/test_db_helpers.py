"""Unit tests for database session helpers (Phase 1.2)

Tests the new short-lived session helpers that prevent connection
pool exhaustion.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC


@pytest.mark.unit
@pytest.mark.session_management
class TestShortSession:
    """Test short-lived session context manager"""

    @pytest.mark.asyncio
    async def test_get_short_session_creates_session(self):
        """get_short_session should create and close session"""
        from src.agent_server.core.db_helpers import get_short_session

        with patch("src.agent_server.core.db_helpers._get_session_maker") as mock_maker:
            mock_session = AsyncMock()
            mock_session.close = AsyncMock()

            # Create async context manager mock
            async_cm = AsyncMock()
            async_cm.__aenter__ = AsyncMock(return_value=mock_session)
            async_cm.__aexit__ = AsyncMock(return_value=None)
            mock_maker.return_value.return_value = async_cm

            async with get_short_session() as session:
                assert session is not None

            # Session should be closed (async call)
            mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_short_session_rolls_back_on_error(self):
        """get_short_session should rollback on exception"""
        from src.agent_server.core.db_helpers import get_short_session

        with patch("src.agent_server.core.db_helpers._get_session_maker") as mock_maker:
            mock_session = AsyncMock()
            mock_session.rollback = AsyncMock()
            mock_session.close = AsyncMock()

            # Create async context manager mock
            async_cm = AsyncMock()
            async_cm.__aenter__ = AsyncMock(return_value=mock_session)
            async_cm.__aexit__ = AsyncMock(return_value=None)
            mock_maker.return_value.return_value = async_cm

            with pytest.raises(ValueError):
                async with get_short_session() as session:
                    raise ValueError("Test error")

            # Should rollback on error (async call)
            mock_session.rollback.assert_awaited_once()
            mock_session.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.session_management
class TestRunUpdateHelpers:
    """Test run update helper functions"""

    @pytest.mark.asyncio
    async def test_update_run_in_db_status_only(self):
        """update_run_in_db should update status"""
        from src.agent_server.core.db_helpers import update_run_in_db

        with patch(
            "src.agent_server.core.db_helpers.get_short_session"
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            await update_run_in_db("test-run", status="running")

            # Should execute update and commit
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_run_in_db_with_output(self):
        """update_run_in_db should update output"""
        from src.agent_server.core.db_helpers import update_run_in_db

        with patch(
            "src.agent_server.core.db_helpers.get_short_session"
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            output = {"result": "success"}
            await update_run_in_db("test-run", status="success", output=output)

            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_run_in_db_with_error(self):
        """update_run_in_db should update error message"""
        from src.agent_server.core.db_helpers import update_run_in_db

        with patch(
            "src.agent_server.core.db_helpers.get_short_session"
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            await update_run_in_db(
                "test-run", status="error", error_message="Test error"
            )

            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()


@pytest.mark.unit
@pytest.mark.session_management
class TestThreadUpdateHelpers:
    """Test thread update helper functions"""

    @pytest.mark.asyncio
    async def test_update_thread_in_db_status_only(self):
        """update_thread_in_db should update status"""
        from src.agent_server.core.db_helpers import update_thread_in_db

        with patch(
            "src.agent_server.core.db_helpers.get_short_session"
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            await update_thread_in_db("test-thread", status="busy")

            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_thread_in_db_with_metadata(self):
        """update_thread_in_db should merge metadata"""
        from src.agent_server.core.db_helpers import update_thread_in_db

        with patch(
            "src.agent_server.core.db_helpers.get_short_session"
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_thread = MagicMock()
            mock_thread.metadata_json = {"existing": "data"}

            mock_session.scalar = AsyncMock(return_value=mock_thread)
            mock_session.execute = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            new_metadata = {"new_key": "new_value"}
            await update_thread_in_db("test-thread", metadata=new_metadata)

            # Should read existing metadata and merge
            mock_session.scalar.assert_called_once()
            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()


@pytest.mark.unit
@pytest.mark.session_management
class TestGetHelpers:
    """Test get helper functions"""

    @pytest.mark.asyncio
    async def test_get_run_from_db_found(self):
        """get_run_from_db should return run if found"""
        from src.agent_server.core.db_helpers import get_run_from_db

        with patch(
            "src.agent_server.core.db_helpers.get_short_session"
        ) as mock_session_ctx:
            mock_run = MagicMock()
            mock_run.run_id = "test-run"

            mock_session = AsyncMock()
            mock_session.scalar = AsyncMock(return_value=mock_run)
            mock_session.refresh = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            result = await get_run_from_db("test-run")

            assert result is not None
            assert result.run_id == "test-run"
            mock_session.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_run_from_db_not_found(self):
        """get_run_from_db should return None if not found"""
        from src.agent_server.core.db_helpers import get_run_from_db

        with patch(
            "src.agent_server.core.db_helpers.get_short_session"
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.scalar = AsyncMock(return_value=None)
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            result = await get_run_from_db("nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_thread_from_db_found(self):
        """get_thread_from_db should return thread if found"""
        from src.agent_server.core.db_helpers import get_thread_from_db

        with patch(
            "src.agent_server.core.db_helpers.get_short_session"
        ) as mock_session_ctx:
            mock_thread = MagicMock()
            mock_thread.thread_id = "test-thread"

            mock_session = AsyncMock()
            mock_session.scalar = AsyncMock(return_value=mock_thread)
            mock_session.refresh = AsyncMock()
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            result = await get_thread_from_db("test-thread")

            assert result is not None
            assert result.thread_id == "test-thread"
            mock_session.refresh.assert_called_once()
