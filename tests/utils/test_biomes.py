"""Tests for biome utility functions."""

import pytest

from database.enums import BiomeType
from utils.biomes import get_chat_biome


@pytest.mark.unit
class TestBiomes:
    """Test biome calculation logic."""

    def test_get_chat_biome_positive_id(self):
        """Test biome assignment for positive chat IDs."""
        # Test deterministic assignment
        biome1 = get_chat_biome(12345)
        biome2 = get_chat_biome(12345)
        assert biome1 == biome2, "Biome should be deterministic for same chat ID"

    def test_get_chat_biome_negative_id(self):
        """Test biome assignment for negative chat IDs (groups)."""
        biome1 = get_chat_biome(-12345)
        biome2 = get_chat_biome(-12345)
        assert biome1 == biome2, "Biome should be deterministic for same chat ID"

    def test_get_chat_biome_abs_handling(self):
        """Test that negative and positive IDs with same absolute value get same biome."""
        positive_biome = get_chat_biome(12345)
        negative_biome = get_chat_biome(-12345)
        assert positive_biome == negative_biome, "Same absolute value should yield same biome"

    def test_get_chat_biome_all_biomes_covered(self):
        """Test that all biome types can be assigned."""
        all_biomes = set()
        # Test a range of IDs to ensure all biomes are possible
        for chat_id in range(1000, 10000, 100):
            biome = get_chat_biome(chat_id)
            all_biomes.add(biome)
        
        # Should have at least most biomes covered
        assert len(all_biomes) >= len(BiomeType) - 1, "Most biomes should be assignable"

    def test_get_chat_biome_zero_id(self):
        """Test biome assignment for zero ID."""
        biome = get_chat_biome(0)
        assert isinstance(biome, BiomeType), "Should return a valid BiomeType"

    def test_get_chat_biome_large_id(self):
        """Test biome assignment for very large IDs."""
        biome = get_chat_biome(999999999999)
        assert isinstance(biome, BiomeType), "Should handle large IDs"

    @pytest.mark.parametrize("chat_id", [1, 100, 1000, -100, -1000, 999999, -999999])
    def test_get_chat_biome_returns_valid_biome(self, chat_id):
        """Test that get_chat_biome always returns a valid BiomeType."""
        biome = get_chat_biome(chat_id)
        assert biome in BiomeType, f"Biome {biome} should be a valid BiomeType"
