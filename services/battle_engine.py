"""Battle engine for calculating battle outcomes."""

import random
from typing import TYPE_CHECKING

from database.enums import BiomeType
from logging_config import get_logger

if TYPE_CHECKING:
    from database.models import CardTemplate

logger = get_logger(__name__)

# Battle constants
BIOME_BONUS_MULTIPLIER = 1.2  # +20% bonus if card's biome matches chat biome
RNG_MIN = 0.9  # Minimum RNG multiplier
RNG_MAX = 1.1  # Maximum RNG multiplier
MEME_CRIT_CHANCE_BASE = 0.1  # 10% base crit chance per MEME point
MEME_CRIT_DAMAGE_MULTIPLIER = 2.0  # 2x damage on crit


def calculate_card_power(card_template: "CardTemplate", chat_biome: BiomeType) -> dict:
    """
    Calculate card's battle power with biome bonuses.

    Args:
        card_template: Card template to calculate power for.
        chat_biome: Biome of the chat where battle is happening.

    Returns:
        Dict with 'atk', 'def', 'total' power values.
    """
    stats = card_template.stats
    atk = stats.get("atk", 0)
    def_stat = stats.get("def", 0)

    # Apply biome bonus if card's biome matches chat biome
    if card_template.biome_affinity == chat_biome:
        atk = int(atk * BIOME_BONUS_MULTIPLIER)
        def_stat = int(def_stat * BIOME_BONUS_MULTIPLIER)
        logger.debug(
            "Biome bonus applied",
            card_name=card_template.name,
            biome=chat_biome.value,
        )

    total = atk + def_stat

    return {
        "atk": atk,
        "def": def_stat,
        "total": total,
        "meme": stats.get("meme", 0),
    }


def calculate_deck_power(cards: list["CardTemplate"], chat_biome: BiomeType) -> dict:
    """
    Calculate total power of a deck (3 cards).

    Args:
        cards: List of 3 card templates.
        chat_biome: Biome of the chat where battle is happening.

    Returns:
        Dict with total stats and individual card powers.
    """
    total_atk = 0
    total_def = 0
    total_meme = 0
    card_powers = []

    for card in cards:
        power = calculate_card_power(card, chat_biome)
        total_atk += power["atk"]
        total_def += power["def"]
        total_meme += power["meme"]
        card_powers.append(
            {
                "card": card,
                "atk": power["atk"],
                "def": power["def"],
                "meme": power["meme"],
            }
        )

    return {
        "total_atk": total_atk,
        "total_def": total_def,
        "total_meme": total_meme,
        "total_power": total_atk + total_def,
        "card_powers": card_powers,
    }


def roll_meme_crit(meme_stat: int) -> bool:
    """
    Check if MEME stat triggers a critical hit.

    Args:
        meme_stat: Total MEME stat value.

    Returns:
        True if crit triggered, False otherwise.
    """
    if meme_stat <= 0:
        return False

    crit_chance = min(meme_stat * MEME_CRIT_CHANCE_BASE, 0.9)  # Max 90% crit chance
    return random.random() < crit_chance


def execute_battle(
    deck1: list["CardTemplate"],
    deck2: list["CardTemplate"],
    chat_biome: BiomeType,
    player1_name: str = "Гравець 1",
    player2_name: str = "Гравець 2",
) -> dict:
    """
    Execute a battle between two decks.

    Args:
        deck1: First player's deck (3 cards).
        deck2: Second player's deck (3 cards).
        chat_biome: Biome of the chat where battle is happening.
        player1_name: Name of first player.
        player2_name: Name of second player.

    Returns:
        Dict with battle results:
        - winner: 1 or 2 (player number)
        - winner_name: Name of winner
        - battle_log: List of battle action strings
        - final_power1: Final power of player 1
        - final_power2: Final power of player 2
    """
    if len(deck1) != 3 or len(deck2) != 3:
        raise ValueError("Each deck must contain exactly 3 cards")

    # Calculate base powers
    power1 = calculate_deck_power(deck1, chat_biome)
    power2 = calculate_deck_power(deck2, chat_biome)

    battle_log = []
    battle_log.append("⚔️ **Бій розпочато!**\n")
    battle_log.append(
        f"👤 **{player1_name}:** ⚔️ {power1['total_atk']} / 🛡️ {power1['total_def']} "
        f"(🎭 MEME: {power1['total_meme']})\n"
    )
    battle_log.append(
        f"👤 **{player2_name}:** ⚔️ {power2['total_atk']} / 🛡️ {power2['total_def']} "
        f"(🎭 MEME: {power2['total_meme']})\n"
    )
    battle_log.append("")

    # Apply RNG multiplier
    rng1 = random.uniform(RNG_MIN, RNG_MAX)
    rng2 = random.uniform(RNG_MIN, RNG_MAX)

    final_power1 = int(power1["total_power"] * rng1)
    final_power2 = int(power2["total_power"] * rng2)

    battle_log.append(f"🎲 Випадковий множник: {rng1:.2f}x vs {rng2:.2f}x\n")

    # Check for MEME crits
    crit1 = roll_meme_crit(power1["total_meme"])
    crit2 = roll_meme_crit(power2["total_meme"])

    if crit1:
        final_power1 = int(final_power1 * MEME_CRIT_DAMAGE_MULTIPLIER)
        battle_log.append(f"🎭 **КРИТИЧНИЙ КРІНЖ!** {player1_name} отримав x2 до сили!\n")
    if crit2:
        final_power2 = int(final_power2 * MEME_CRIT_DAMAGE_MULTIPLIER)
        battle_log.append(f"🎭 **КРИТИЧНИЙ КРІНЖ!** {player2_name} отримав x2 до сили!\n")

    if crit1 or crit2:
        battle_log.append("")

    # Simulate battle rounds (3 rounds, each card attacks)
    damage1 = 0
    damage2 = 0

    for round_num in range(3):
        # Player 1 attacks
        atk1 = power1["card_powers"][round_num]["atk"]
        def2 = power2["card_powers"][round_num]["def"]
        dmg = max(0, atk1 - def2)
        damage2 += dmg

        card1_name = power1["card_powers"][round_num]["card"].name
        card2_name = power2["card_powers"][round_num]["card"].name

        battle_log.append(
            f"**Раунд {round_num + 1}:**\n"
            f"⚔️ {card1_name} ({player1_name}) атакує {card2_name} ({player2_name})"
        )
        if dmg > 0:
            battle_log.append(f"💥 Завдано {dmg} шкоди!")
        else:
            battle_log.append(f"🛡️ Атака заблокована!")
        battle_log.append("")

        # Player 2 attacks
        atk2 = power2["card_powers"][round_num]["atk"]
        def1 = power1["card_powers"][round_num]["def"]
        dmg = max(0, atk2 - def1)
        damage1 += dmg

        battle_log.append(
            f"⚔️ {card2_name} ({player2_name}) атакує {card1_name} ({player1_name})"
        )
        if dmg > 0:
            battle_log.append(f"💥 Завдано {dmg} шкоди!")
        else:
            battle_log.append(f"🛡️ Атака заблокована!")
        battle_log.append("")

    # Determine winner based on final power
    if final_power1 > final_power2:
        winner = 1
        winner_name = player1_name
    elif final_power2 > final_power1:
        winner = 2
        winner_name = player2_name
    else:
        # Tie - random winner
        winner = random.choice([1, 2])
        winner_name = player1_name if winner == 1 else player2_name
        battle_log.append("🤝 Нічия! Переможець визначений випадково.\n")

    battle_log.append(f"🏆 **Переможець: {winner_name}!**")
    battle_log.append(f"💪 Фінальна сила: {final_power1} vs {final_power2}")

    return {
        "winner": winner,
        "winner_name": winner_name,
        "battle_log": "\n".join(battle_log),
        "final_power1": final_power1,
        "final_power2": final_power2,
        "damage1": damage1,
        "damage2": damage2,
    }


def generate_battle_summary(battle_result: dict, stake: int) -> str:
    """
    Generate a formatted battle summary message.

    Args:
        battle_result: Result dict from execute_battle().
        stake: Stake amount in scraps.

    Returns:
        Formatted battle summary string.
    """
    summary = battle_result["battle_log"]
    summary += f"\n\n💰 **Ставка:** {stake} Решток"
    summary += f"\n🎁 **Нагорода переможця:** {stake * 2} Решток"

    return summary
