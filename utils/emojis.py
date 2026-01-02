"""Emoji utilities for cards and game elements."""

from database.enums import BiomeType, Rarity


def get_biome_emoji(biome: BiomeType) -> str:
    """Get emoji for biome type."""
    emoji_map = {
        BiomeType.NORMAL: "🌍",
        BiomeType.FIRE: "🔥",
        BiomeType.WATER: "💧",
        BiomeType.GRASS: "🌿",
        BiomeType.PSYCHIC: "🔮",
        BiomeType.TECHNO: "⚙️",
        BiomeType.DARK: "🌑",
    }
    return emoji_map.get(biome, "🌍")


def get_rarity_emoji(rarity: Rarity) -> str:
    """Get emoji for rarity type."""
    emoji_map = {
        Rarity.COMMON: "⚪",
        Rarity.RARE: "🔵",
        Rarity.EPIC: "🟣",
        Rarity.LEGENDARY: "🟠",
        Rarity.MYTHIC: "🔴",
    }
    return emoji_map.get(rarity, "⚪")
