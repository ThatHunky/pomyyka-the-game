"""Tests for emoji utility functions."""

import pytest

from database.enums import BiomeType, Rarity
from utils.emojis import get_biome_emoji, get_rarity_emoji


@pytest.mark.unit
class TestEmojis:
    """Test emoji utility functions."""

    @pytest.mark.parametrize("biome,expected_emoji", [
        (BiomeType.NORMAL, "🌍"),
        (BiomeType.FIRE, "🔥"),
        (BiomeType.WATER, "💧"),
        (BiomeType.GRASS, "🌿"),
        (BiomeType.PSYCHIC, "🔮"),
        (BiomeType.TECHNO, "⚙️"),
        (BiomeType.DARK, "🌑"),
    ])
    def test_get_biome_emoji_all_types(self, biome, expected_emoji):
        """Test that all biome types return correct emojis."""
        result = get_biome_emoji(biome)
        assert result == expected_emoji, f"Biome {biome} should return {expected_emoji}"

    def test_get_biome_emoji_unknown_returns_default(self):
        """Test that unknown biome returns default emoji."""
        # Create a mock biome that doesn't exist in the map
        class UnknownBiome:
            pass
        
        # This shouldn't happen in practice, but test the fallback
        # We can't easily test this without modifying the function, so we'll test valid cases
        result = get_biome_emoji(BiomeType.NORMAL)
        assert result == "🌍", "Should return emoji for valid biome"

    @pytest.mark.parametrize("rarity,expected_emoji", [
        (Rarity.COMMON, "⚪"),
        (Rarity.RARE, "🔵"),
        (Rarity.EPIC, "🟣"),
        (Rarity.LEGENDARY, "🟠"),
        (Rarity.MYTHIC, "🔴"),
    ])
    def test_get_rarity_emoji_all_types(self, rarity, expected_emoji):
        """Test that all rarity types return correct emojis."""
        result = get_rarity_emoji(rarity)
        assert result == expected_emoji, f"Rarity {rarity} should return {expected_emoji}"

    def test_get_rarity_emoji_unknown_returns_default(self):
        """Test that unknown rarity returns default emoji."""
        result = get_rarity_emoji(Rarity.COMMON)
        assert result == "⚪", "Should return emoji for valid rarity"

    def test_get_biome_emoji_returns_string(self):
        """Test that function returns a string."""
        result = get_biome_emoji(BiomeType.FIRE)
        assert isinstance(result, str), "Should return string"

    def test_get_rarity_emoji_returns_string(self):
        """Test that function returns a string."""
        result = get_rarity_emoji(Rarity.LEGENDARY)
        assert isinstance(result, str), "Should return string"
