"""Tests for battle engine service."""

import pytest
from unittest.mock import patch

from database.enums import AttackType, BiomeType, Rarity, StatusEffect
from database.models import CardTemplate
from services.battle_engine import (
    apply_status_effect,
    calculate_card_power,
    calculate_deck_power,
    calculate_type_effectiveness,
    execute_battle,
    generate_battle_summary,
    roll_meme_crit,
    select_attack,
)


@pytest.mark.unit
class TestTypeEffectiveness:
    """Test type effectiveness calculations."""

    def test_calculate_type_effectiveness_no_weakness_or_resistance(self):
        """Test type effectiveness with no weakness or resistance."""
        multiplier = calculate_type_effectiveness(
            AttackType.FIRE,
            BiomeType.NORMAL,
            None,
            None,
        )
        assert multiplier == 1.0, "Should return 1.0 when no special interactions"

    def test_calculate_type_effectiveness_weakness_triggered(self):
        """Test that weakness multiplies damage correctly."""
        weakness = {"type": AttackType.FIRE.value, "multiplier": 2.0}
        multiplier = calculate_type_effectiveness(
            AttackType.FIRE,
            BiomeType.NORMAL,
            weakness,
            None,
        )
        assert multiplier == 2.0, "Weakness should double damage"

    def test_calculate_type_effectiveness_resistance_flat_reduction(self):
        """Test that resistance with flat reduction works."""
        resistance = {"type": AttackType.FIRE.value, "reduction": 20}
        multiplier = calculate_type_effectiveness(
            AttackType.FIRE,
            BiomeType.NORMAL,
            None,
            resistance,
        )
        assert multiplier == 1.0, "Flat reduction should return 1.0 (applied later)"

    def test_calculate_type_effectiveness_resistance_percentage(self):
        """Test that resistance with percentage reduction works."""
        resistance = {"type": AttackType.FIRE.value, "reduction": 0}
        multiplier = calculate_type_effectiveness(
            AttackType.FIRE,
            BiomeType.NORMAL,
            None,
            resistance,
        )
        assert multiplier == 0.5, "Percentage resistance should halve damage"

    def test_calculate_type_effectiveness_fire_vs_grass(self):
        """Test fire attack against grass biome."""
        multiplier = calculate_type_effectiveness(
            AttackType.FIRE,
            BiomeType.GRASS,
            None,
            None,
        )
        assert multiplier == 2.0, "Fire should be super effective against Grass"

    def test_calculate_type_effectiveness_water_vs_fire(self):
        """Test water attack against fire biome."""
        multiplier = calculate_type_effectiveness(
            AttackType.WATER,
            BiomeType.FIRE,
            None,
            None,
        )
        assert multiplier == 2.0, "Water should be super effective against Fire"

    def test_calculate_type_effectiveness_fire_vs_water(self):
        """Test fire attack against water biome."""
        multiplier = calculate_type_effectiveness(
            AttackType.FIRE,
            BiomeType.WATER,
            None,
            None,
        )
        assert multiplier == 0.5, "Fire should be not very effective against Water"


@pytest.mark.unit
class TestStatusEffects:
    """Test status effect application."""

    def test_apply_status_effect_none(self):
        """Test applying no status effect."""
        damage, message = apply_status_effect(StatusEffect.NONE, "Test Card")
        assert damage == 0, "No status should deal no damage"
        assert message == "", "No status should have no message"

    def test_apply_status_effect_burned(self):
        """Test burned status effect."""
        damage, message = apply_status_effect(StatusEffect.BURNED, "Test Card")
        assert damage == 10, "Burned should deal 10 damage"
        assert "опіку" in message, "Message should mention burn"

    def test_apply_status_effect_poisoned(self):
        """Test poisoned status effect."""
        damage, message = apply_status_effect(StatusEffect.POISONED, "Test Card")
        assert damage == 10, "Poisoned should deal 10 damage"
        assert "отрути" in message, "Message should mention poison"

    def test_apply_status_effect_frozen(self):
        """Test frozen status effect."""
        damage, message = apply_status_effect(StatusEffect.FROZEN, "Test Card")
        assert damage == 0, "Frozen should deal no damage"
        assert "заморожено" in message, "Message should mention frozen"

    def test_apply_status_effect_asleep(self):
        """Test asleep status effect."""
        damage, message = apply_status_effect(StatusEffect.ASLEEP, "Test Card")
        assert damage == 0, "Asleep should deal no damage"
        assert "спить" in message, "Message should mention sleep"


@pytest.mark.unit
class TestCardPower:
    """Test card power calculations."""

    def test_calculate_card_power_basic(self, sample_card_template):
        """Test basic card power calculation."""
        power = calculate_card_power(sample_card_template, BiomeType.NORMAL)
        assert power["atk"] == 50, "Attack should match card stats"
        assert power["def"] == 50, "Defense should match card stats"
        assert power["total"] == 100, "Total should be sum of atk and def"
        assert power["meme"] == 10, "Meme should match card stats"

    def test_calculate_card_power_biome_bonus(self, sample_card_template):
        """Test biome bonus application."""
        sample_card_template.biome_affinity = BiomeType.FIRE
        power = calculate_card_power(sample_card_template, BiomeType.FIRE)
        # With 1.2x bonus: 50 * 1.2 = 60
        assert power["atk"] == 60, "Attack should have biome bonus"
        assert power["def"] == 60, "Defense should have biome bonus"

    def test_calculate_card_power_no_biome_bonus(self, sample_card_template):
        """Test that biome bonus doesn't apply when biomes don't match."""
        sample_card_template.biome_affinity = BiomeType.FIRE
        power = calculate_card_power(sample_card_template, BiomeType.WATER)
        assert power["atk"] == 50, "Attack should not have bonus"
        assert power["def"] == 50, "Defense should not have bonus"


@pytest.mark.unit
class TestDeckPower:
    """Test deck power calculations."""

    def test_calculate_deck_power_three_cards(self, sample_card_template):
        """Test calculating power for a deck of 3 cards."""
        deck = [sample_card_template, sample_card_template, sample_card_template]
        power = calculate_deck_power(deck, BiomeType.NORMAL)
        assert power["total_atk"] == 150, "Total attack should be sum of all cards"
        assert power["total_def"] == 150, "Total defense should be sum of all cards"
        assert len(power["card_powers"]) == 3, "Should have power for each card"

    def test_calculate_deck_power_biome_bonus(self, sample_card_template):
        """Test deck power with biome bonus."""
        sample_card_template.biome_affinity = BiomeType.FIRE
        deck = [sample_card_template, sample_card_template, sample_card_template]
        power = calculate_deck_power(deck, BiomeType.FIRE)
        # Each card gets 1.2x bonus: 50 * 1.2 * 3 = 180
        assert power["total_atk"] == 180, "Total attack should include biome bonuses"


@pytest.mark.unit
class TestSelectAttack:
    """Test attack selection logic."""

    def test_select_attack_with_attacks(self, sample_card_template):
        """Test selecting attack from card with attacks."""
        attack = select_attack(sample_card_template, available_energy=3)
        assert attack is not None, "Should return an attack"
        assert "name" in attack, "Attack should have name"
        assert "damage" in attack, "Attack should have damage"

    def test_select_attack_fallback_basic_attack(self):
        """Test fallback to basic attack when no attacks defined."""
        card = CardTemplate(
            id=None,
            name="Test",
            rarity=Rarity.COMMON,
            biome_affinity=BiomeType.NORMAL,
            stats={"atk": 50, "def": 50, "meme": 10},
            attacks=None,
        )
        attack = select_attack(card, available_energy=3)
        assert attack is not None, "Should return fallback attack"
        assert attack["name"] == "Базова атака", "Should use basic attack name"
        assert attack["damage"] == 50, "Damage should match ATK stat"

    def test_select_attack_energy_filtering(self, sample_card_template):
        """Test that attacks are filtered by energy cost."""
        # Add expensive attack
        sample_card_template.attacks.append({
            "name": "Expensive",
            "type": AttackType.FIRE.value,
            "damage": 100,
            "energy_cost": 5,  # Too expensive
            "effect": "",
            "status_effect": StatusEffect.NONE.value,
        })
        attack = select_attack(sample_card_template, available_energy=3)
        # Should not select the expensive attack
        assert attack["energy_cost"] <= 3, "Should only select affordable attacks"


@pytest.mark.unit
class TestMemeCrit:
    """Test MEME critical hit logic."""

    def test_roll_meme_crit_zero_meme(self):
        """Test that zero MEME stat never crits."""
        with patch("services.battle_engine.random.random", return_value=0.0):
            result = roll_meme_crit(0)
            assert result is False, "Zero MEME should never crit"

    def test_roll_meme_crit_negative_meme(self):
        """Test that negative MEME stat never crits."""
        result = roll_meme_crit(-10)
        assert result is False, "Negative MEME should never crit"

    def test_roll_meme_crit_high_meme(self):
        """Test that high MEME stat has high crit chance."""
        with patch("services.battle_engine.random.random", return_value=0.05):
            result = roll_meme_crit(10)  # 10 * 0.1 = 100% chance, capped at 90%
            assert result is True, "High MEME should crit with low random"

    def test_roll_meme_crit_capped_at_90_percent(self):
        """Test that crit chance is capped at 90%."""
        with patch("services.battle_engine.random.random", return_value=0.95):
            result = roll_meme_crit(100)  # Would be 1000% but capped at 90%
            assert result is False, "Even high MEME shouldn't always crit"


@pytest.mark.unit
class TestExecuteBattle:
    """Test battle execution."""

    def test_execute_battle_requires_three_cards(self, sample_card_template):
        """Test that battle requires exactly 3 cards per deck."""
        deck1 = [sample_card_template]
        deck2 = [sample_card_template, sample_card_template, sample_card_template]
        
        with pytest.raises(ValueError, match="exactly 3 cards"):
            execute_battle(deck1, deck2, BiomeType.NORMAL)

    def test_execute_battle_returns_winner(self, sample_card_template):
        """Test that battle returns a winner."""
        deck = [sample_card_template, sample_card_template, sample_card_template]
        result = execute_battle(deck, deck, BiomeType.NORMAL)
        
        assert "winner" in result, "Should return winner"
        assert result["winner"] in [1, 2], "Winner should be player 1 or 2"
        assert "winner_name" in result, "Should return winner name"

    def test_execute_battle_returns_battle_log(self, sample_card_template):
        """Test that battle returns a battle log."""
        deck = [sample_card_template, sample_card_template, sample_card_template]
        result = execute_battle(deck, deck, BiomeType.NORMAL)
        
        assert "battle_log" in result, "Should return battle log"
        assert isinstance(result["battle_log"], str), "Battle log should be string"
        assert "Бій розпочато" in result["battle_log"], "Log should contain battle start"

    def test_execute_battle_returns_power_stats(self, sample_card_template):
        """Test that battle returns power statistics."""
        deck = [sample_card_template, sample_card_template, sample_card_template]
        result = execute_battle(deck, deck, BiomeType.NORMAL)
        
        assert "final_power1" in result, "Should return final power for player 1"
        assert "final_power2" in result, "Should return final power for player 2"
        assert "damage1" in result, "Should return damage for player 1"
        assert "damage2" in result, "Should return damage for player 2"

    def test_execute_battle_stronger_deck_wins(self):
        """Test that stronger deck typically wins."""
        strong_card = CardTemplate(
            id=None,
            name="Strong",
            rarity=Rarity.LEGENDARY,
            biome_affinity=BiomeType.NORMAL,
            stats={"atk": 200, "def": 200, "meme": 50},
            attacks=[{
                "name": "Power Attack",
                "type": AttackType.PHYSICAL.value,
                "damage": 150,
                "energy_cost": 1,
                "effect": "",
                "status_effect": StatusEffect.NONE.value,
            }],
        )
        weak_card = CardTemplate(
            id=None,
            name="Weak",
            rarity=Rarity.COMMON,
            biome_affinity=BiomeType.NORMAL,
            stats={"atk": 10, "def": 10, "meme": 1},
            attacks=[{
                "name": "Weak Attack",
                "type": AttackType.PHYSICAL.value,
                "damage": 5,
                "energy_cost": 1,
                "effect": "",
                "status_effect": StatusEffect.NONE.value,
            }],
        )
        
        strong_deck = [strong_card, strong_card, strong_card]
        weak_deck = [weak_card, weak_card, weak_card]
        
        # Run multiple battles to account for RNG
        wins = 0
        for _ in range(10):
            result = execute_battle(strong_deck, weak_deck, BiomeType.NORMAL)
            if result["winner"] == 1:
                wins += 1
        
        # Strong deck should win most of the time
        assert wins >= 7, "Stronger deck should win most battles"


@pytest.mark.unit
class TestBattleSummary:
    """Test battle summary generation."""

    def test_generate_battle_summary_includes_stake(self, sample_card_template):
        """Test that summary includes stake information."""
        deck = [sample_card_template, sample_card_template, sample_card_template]
        battle_result = execute_battle(deck, deck, BiomeType.NORMAL)
        
        summary = generate_battle_summary(battle_result, stake=100)
        assert "Ставка" in summary, "Should include stake"
        assert "100" in summary, "Should show stake amount"
        assert "Нагорода" in summary, "Should include reward"
        assert "200" in summary, "Should show reward (stake * 2)"
