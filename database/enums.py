from enum import Enum


class BiomeType(str, Enum):
    """Biome types for card affinity (Ukrainian locale)."""

    NORMAL = "Звичайний"
    FIRE = "Вогняний"
    WATER = "Водний"
    GRASS = "Трав'яний"
    PSYCHIC = "Психічний"
    TECHNO = "Техно"
    DARK = "Темний"


class Rarity(str, Enum):
    """Card rarity levels."""

    COMMON = "Common"
    RARE = "Rare"
    EPIC = "Epic"
    LEGENDARY = "Legendary"
    MYTHIC = "Mythic"
