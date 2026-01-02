"""Tests for drop handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from aiogram.types import CallbackQuery
from handlers.drops import ClaimDropCallback, handle_claim_drop_structured
from services.redis_lock import DropManager


@pytest.mark.unit
class TestDropHandlers:
    """Test drop claim handlers."""

    @pytest.mark.asyncio
    async def test_claim_drop_callback_data(self):
        """Test ClaimDropCallback data structure."""
        template_id = str(uuid4())
        callback_data = ClaimDropCallback(template_id=template_id)
        assert callback_data.template_id == template_id

    @pytest.mark.asyncio
    async def test_handle_claim_drop_already_claimed(self, mock_callback_query, drop_manager, sample_card_template_db):
        """Test handling drop claim when already claimed."""
        # Claim drop first
        await drop_manager.try_claim_drop(mock_callback_query.message.message_id, 99999)
        
        callback_data = ClaimDropCallback(template_id=str(sample_card_template_db.id))
        
        # Mock callback.answer
        mock_callback_query.answer = AsyncMock()
        
        with patch("handlers.drops.get_session") as mock_get_session:
            mock_get_session.return_value.__aiter__ = lambda x: iter([MagicMock()])
            
            await handle_claim_drop_structured(
                mock_callback_query,
                callback_data,
                drop_manager,
            )
            
            # Should answer that drop is already claimed
            mock_callback_query.answer.assert_called()
