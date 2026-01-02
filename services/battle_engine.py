"""Battle engine for calculating battle outcomes with Pokemon TCG-inspired mechanics."""

import random
from typing import TYPE_CHECKING

from database.enums import AttackType, BiomeType, StatusEffect
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

# Status effect damage per turn
STATUS_DAMAGE = {
    StatusEffect.BURNED: 10,
    StatusEffect.POISONED: 10,
    StatusEffect.FROZEN: 0,  # Skip turn instead
    StatusEffect.PARALYZED: 0,  # 50% chance to skip turn
    StatusEffect.CONFUSED: 0,  # 30% chance to hurt self
    StatusEffect.ASLEEP: 0,  # Skip turn until wakes up
    StatusEffect.NONE: 0,
}

# Type effectiveness chart (like Pokemon)
TYPE_EFFECTIVENESS = {
    AttackType.FIRE: {AttackType.GRASS: 2.0, AttackType.WATER: 0.5, AttackType.TECHNO: 1.5},
    AttackType.WATER: {AttackType.FIRE: 2.0, AttackType.GRASS: 0.5, AttackType.TECHNO: 1.5},
    AttackType.GRASS: {AttackType.WATER: 2.0, AttackType.FIRE: 0.5, AttackType.DARK: 1.5},
    AttackType.PSYCHIC: {AttackType.DARK: 2.0, AttackType.TECHNO: 0.5},
    AttackType.TECHNO: {AttackType.PSYCHIC: 2.0, AttackType.DARK: 1.5, AttackType.WATER: 0.5},
    AttackType.DARK: {AttackType.PSYCHIC: 2.0, AttackType.GRASS: 0.5},
    AttackType.MEME: {AttackType.PSYCHIC: 1.5, AttackType.DARK: 1.5},  # Meme is effective against mental types
    AttackType.PHYSICAL: {},  # No special effectiveness
}


def calculate_type_effectiveness(attack_type: AttackType, defender_biome: BiomeType, defender_weakness: dict | None, defender_resistance: dict | None) -> float:
    """
    Calculate type effectiveness multiplier for an attack.
    
    Args:
        attack_type: Type of the attack being used.
        defender_biome: Biome of the defending card.
        defender_weakness: Weakness dict from defender card.
        defender_resistance: Resistance dict from defender card.
    
    Returns:
        Multiplier for damage (e.g., 2.0 for super effective, 0.5 for not very effective).
    """
    multiplier = 1.0
    
    # Check weakness (typically 2x damage)
    if defender_weakness:
        weak_type = AttackType(defender_weakness.get("type", ""))
        if attack_type == weak_type:
            multiplier *= defender_weakness.get("multiplier", 2.0)
            logger.debug(f"Weakness triggered: {attack_type.value} -> {multiplier}x")
    
    # Check resistance (typically -20 damage or 0.5x)
    if defender_resistance:
        resist_type = AttackType(defender_resistance.get("type", ""))
        if attack_type == resist_type:
            reduction = defender_resistance.get("reduction", 0)
            if reduction > 0:
                # Flat reduction (will be applied later)
                multiplier = 1.0  # Don't multiply, apply flat reduction
            else:
                # Percentage reduction
                multiplier *= 0.5
            logger.debug(f"Resistance triggered: {attack_type.value} -> {multiplier}x")
    
    # Check type effectiveness chart
    if attack_type in TYPE_EFFECTIVENESS:
        effectiveness = TYPE_EFFECTIVENESS[attack_type]
        # Map biome to attack type for effectiveness
        biome_to_type = {
            BiomeType.FIRE: AttackType.FIRE,
            BiomeType.WATER: AttackType.WATER,
            BiomeType.GRASS: AttackType.GRASS,
            BiomeType.PSYCHIC: AttackType.PSYCHIC,
            BiomeType.TECHNO: AttackType.TECHNO,
            BiomeType.DARK: AttackType.DARK,
        }
        defender_type = biome_to_type.get(defender_biome)
        if defender_type and defender_type in effectiveness:
            multiplier *= effectiveness[defender_type]
            logger.debug(f"Type effectiveness: {attack_type.value} vs {defender_type.value} -> {multiplier}x")
    
    return multiplier


def apply_status_effect(status: StatusEffect, card_name: str) -> tuple[int, str]:
    """
    Apply status effect damage/effects for a turn.
    
    Args:
        status: Status effect to apply.
        card_name: Name of affected card.
    
    Returns:
        Tuple of (damage_dealt, status_message).
    """
    if status == StatusEffect.NONE:
        return 0, ""
    
    damage = STATUS_DAMAGE.get(status, 0)
    messages = {
        StatusEffect.BURNED: f"🔥 {card_name} отримує {damage} шкоди від опіку!",
        StatusEffect.POISONED: f"☠️ {card_name} отримує {damage} шкоди від отрути!",
        StatusEffect.FROZEN: f"❄️ {card_name} заморожено і пропускає хід!",
        StatusEffect.PARALYZED: f"⚡ {card_name} паралізовано!" if random.random() < 0.5 else "",
        StatusEffect.CONFUSED: f"🌀 {card_name} плутається!" if random.random() < 0.3 else "",
        StatusEffect.ASLEEP: f"😴 {card_name} спить і не може атакувати!",
    }
    
    message = messages.get(status, "")
    
    # Special handling for PARALYZED and ASLEEP (skip turn)
    if status == StatusEffect.PARALYZED and random.random() < 0.5:
        return 0, f"⚡ {card_name} паралізовано і пропускає хід!"
    if status == StatusEffect.ASLEEP:
        return 0, f"😴 {card_name} спить і не може атакувати!"
    if status == StatusEffect.FROZEN:
        return 0, f"❄️ {card_name} заморожено і пропускає хід!"
    
    return damage, message


def select_attack(card_template: "CardTemplate", available_energy: int = 3) -> dict | None:
    """
    Select an attack from a card that can be used with available energy.
    
    Args:
        card_template: Card to select attack from.
        available_energy: Available energy (default 3, simplified system).
    
    Returns:
        Attack dict or None if no usable attack.
    """
    attacks = card_template.attacks or []
    if not attacks:
        # Fallback to basic attack using atk stat
        return {
            "name": "Базова атака",
            "type": AttackType.PHYSICAL,
            "damage": card_template.stats.get("atk", 0),
            "energy_cost": 1,
            "effect": "",
            "status_effect": StatusEffect.NONE,
        }
    
    # Filter attacks by energy cost
    usable_attacks = [a for a in attacks if a.get("energy_cost", 1) <= available_energy]
    
    if not usable_attacks:
        # Use cheapest attack if none are usable (shouldn't happen with energy=3)
        usable_attacks = attacks
    
    # Select random attack from usable ones (or highest damage if multiple)
    if len(usable_attacks) > 1:
        # Prefer higher damage attacks
        usable_attacks.sort(key=lambda x: x.get("damage", 0), reverse=True)
        # 70% chance to use best attack, 30% random
        if random.random() < 0.7:
            return usable_attacks[0]
        return random.choice(usable_attacks)
    
    return usable_attacks[0] if usable_attacks else None


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
    Execute a battle between two decks with Pokemon TCG-inspired mechanics.

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

    # Track status effects for each card
    status_effects1 = [StatusEffect.NONE] * 3
    status_effects2 = [StatusEffect.NONE] * 3
    
    # Track total damage
    total_damage1 = 0
    total_damage2 = 0

    # Simulate battle rounds (3 rounds, each card attacks)
    for round_num in range(3):
        battle_log.append(f"**Раунд {round_num + 1}:**\n")
        
        card1 = power1["card_powers"][round_num]["card"]
        card2 = power2["card_powers"][round_num]["card"]
        
        # Apply status effects before attacks
        status1 = status_effects1[round_num]
        status2 = status_effects2[round_num]
        
        if status1 != StatusEffect.NONE:
            dmg, msg = apply_status_effect(status1, card1.name)
            if msg:
                battle_log.append(msg)
            total_damage1 += dmg
        
        if status2 != StatusEffect.NONE:
            dmg, msg = apply_status_effect(status2, card2.name)
            if msg:
                battle_log.append(msg)
            total_damage2 += dmg
        
        # Player 1 attacks (if not skipped by status)
        if status1 not in [StatusEffect.ASLEEP, StatusEffect.FROZEN] and (status1 != StatusEffect.PARALYZED or random.random() >= 0.5):
            attack1 = select_attack(card1, available_energy=3)
            if attack1:
                attack_type = AttackType(attack1.get("type", AttackType.PHYSICAL))
                base_damage = attack1.get("damage", 0)
                def2 = power2["card_powers"][round_num]["def"]
                
                # Calculate type effectiveness
                effectiveness = calculate_type_effectiveness(
                    attack_type,
                    card2.biome_affinity,
                    card2.weakness,
                    card2.resistance,
                )
                
                # Apply effectiveness
                effective_damage = int(base_damage * effectiveness)
                
                # Apply resistance flat reduction if applicable
                if card2.resistance and AttackType(card2.resistance.get("type", "")) == attack_type:
                    reduction = card2.resistance.get("reduction", 0)
                    if reduction > 0:
                        effective_damage = max(0, effective_damage - reduction)
                
                # Calculate final damage (attack - defense)
                dmg = max(0, effective_damage - def2)
                
                # Check for MEME crit
                if roll_meme_crit(power1["card_powers"][round_num]["meme"]):
                    dmg = int(dmg * MEME_CRIT_DAMAGE_MULTIPLIER)
                    battle_log.append(f"🎭 **КРИТИЧНИЙ КРІНЖ!**")
                
                total_damage2 += dmg
                
                attack_name = attack1.get("name", "Атака")
                battle_log.append(
                    f"⚔️ {card1.name} ({player1_name}) використовує **{attack_name}** ({attack_type.value}) проти {card2.name} ({player2_name})"
                )
                
                if effectiveness > 1.0:
                    battle_log.append(f"✨ Суперефективна атака! ({effectiveness:.1f}x)")
                elif effectiveness < 1.0:
                    battle_log.append(f"⚠️ Не дуже ефективна атака ({effectiveness:.1f}x)")
                
                if dmg > 0:
                    battle_log.append(f"💥 Завдано {dmg} шкоди!")
                else:
                    battle_log.append(f"🛡️ Атака заблокована!")
                
                # Apply status effect from attack
                status_effect = StatusEffect(attack1.get("status_effect", StatusEffect.NONE))
                if status_effect != StatusEffect.NONE:
                    status_effects2[round_num] = status_effect
                    battle_log.append(f"🔮 {card2.name} отримав статус: {status_effect.value}")
        
        battle_log.append("")
        
        # Player 2 attacks (if not skipped by status)
        if status2 not in [StatusEffect.ASLEEP, StatusEffect.FROZEN] and (status2 != StatusEffect.PARALYZED or random.random() >= 0.5):
            attack2 = select_attack(card2, available_energy=3)
            if attack2:
                attack_type = AttackType(attack2.get("type", AttackType.PHYSICAL))
                base_damage = attack2.get("damage", 0)
                def1 = power1["card_powers"][round_num]["def"]
                
                # Calculate type effectiveness
                effectiveness = calculate_type_effectiveness(
                    attack_type,
                    card1.biome_affinity,
                    card1.weakness,
                    card1.resistance,
                )
                
                # Apply effectiveness
                effective_damage = int(base_damage * effectiveness)
                
                # Apply resistance flat reduction if applicable
                if card1.resistance and AttackType(card1.resistance.get("type", "")) == attack_type:
                    reduction = card1.resistance.get("reduction", 0)
                    if reduction > 0:
                        effective_damage = max(0, effective_damage - reduction)
                
                # Calculate final damage (attack - defense)
                dmg = max(0, effective_damage - def1)
                
                # Check for MEME crit
                if roll_meme_crit(power2["card_powers"][round_num]["meme"]):
                    dmg = int(dmg * MEME_CRIT_DAMAGE_MULTIPLIER)
                    battle_log.append(f"🎭 **КРИТИЧНИЙ КРІНЖ!**")
                
                total_damage1 += dmg
                
                attack_name = attack2.get("name", "Атака")
                battle_log.append(
                    f"⚔️ {card2.name} ({player2_name}) використовує **{attack_name}** ({attack_type.value}) проти {card1.name} ({player1_name})"
                )
                
                if effectiveness > 1.0:
                    battle_log.append(f"✨ Суперефективна атака! ({effectiveness:.1f}x)")
                elif effectiveness < 1.0:
                    battle_log.append(f"⚠️ Не дуже ефективна атака ({effectiveness:.1f}x)")
                
                if dmg > 0:
                    battle_log.append(f"💥 Завдано {dmg} шкоди!")
                else:
                    battle_log.append(f"🛡️ Атака заблокована!")
                
                # Apply status effect from attack
                status_effect = StatusEffect(attack2.get("status_effect", StatusEffect.NONE))
                if status_effect != StatusEffect.NONE:
                    status_effects1[round_num] = status_effect
                    battle_log.append(f"🔮 {card1.name} отримав статус: {status_effect.value}")
        
        battle_log.append("")

    # Determine winner based on total damage dealt
    final_power1 = power1["total_power"] - total_damage1
    final_power2 = power2["total_power"] - total_damage2

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
    battle_log.append(f"💥 Загальна шкода: {player1_name} отримав {total_damage1}, {player2_name} отримав {total_damage2}")

    return {
        "winner": winner,
        "winner_name": winner_name,
        "battle_log": "\n".join(battle_log),
        "final_power1": final_power1,
        "final_power2": final_power2,
        "damage1": total_damage1,
        "damage2": total_damage2,
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
