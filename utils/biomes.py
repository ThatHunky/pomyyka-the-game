from database.enums import BiomeType


def get_chat_biome(chat_id: int) -> BiomeType:
    """
    Deterministically assigns a biome to a Telegram chat based on its ID.

    This function uses modulo arithmetic to ensure each chat always gets
    the same biome without needing database lookups or updates.

    Args:
        chat_id: Telegram chat ID (can be negative for groups)

    Returns:
        BiomeType: The biome assigned to this chat
    """
    biome_list = list(BiomeType)
    index = abs(chat_id) % len(biome_list)
    return biome_list[index]
