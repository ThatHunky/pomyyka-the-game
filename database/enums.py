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


class AttackType(str, Enum):
    """Attack types for Pokemon TCG-inspired system."""

    PHYSICAL = "Фізична"  # Physical damage
    FIRE = "Вогняна"  # Fire damage
    WATER = "Водна"  # Water damage
    GRASS = "Трав'яна"  # Grass/Nature damage
    PSYCHIC = "Психічна"  # Psychic/Mental damage
    TECHNO = "Техно"  # Technology/Cyber damage
    DARK = "Темна"  # Dark/Shadow damage
    MEME = "Мемна"  # Meme/Humor damage (unique to this game)


class StatusEffect(str, Enum):
    """Status effects that can be applied to cards (Pokemon TCG-inspired)."""

    NONE = "Немає"  # No status effect
    BURNED = "Опік"  # Takes damage each turn
    POISONED = "Отрута"  # Takes damage each turn
    PARALYZED = "Параліч"  # May skip turn
    CONFUSED = "Плутанина"  # May hurt self when attacking
    ASLEEP = "Сон"  # Cannot attack until wakes up
    FROZEN = "Замороження"  # Cannot attack for one turn