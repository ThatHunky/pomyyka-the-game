"""Integration tests for battle flow."""

import pytest
from uuid import uuid4

from database.enums import AttackType, BiomeType, Rarity, StatusEffect
from database.models import CardTemplate
from services.battle_engine import execute_battle


@pytest.mark.integration
class TestBattleFlow:
    """Test end-to-end battle flow."""

    @pytest.mark.asyncio
    async def test_complete_battle_execution(self):
        """Test complete battle execution with real cards."""
        # Create deck 1
        card1 = CardTemplate(
            id=uuid4(),
            name="Fire Card",
            rarity=Rarity.EPIC,
            biome_affinity=BiomeType.FIRE,
            stats={"atk": 100, "def": 80, "meme": 20},
            attacks=[{
                "name": "Fire Blast",
                "type": AttackType.FIRE.value,
                "damage": 80,
                "energy_cost": 2,
                "effect": "",
                "status_effect": StatusEffect.BURNED.value,
            }],
        )
        
        card2 = CardTemplate(
            id=uuid4(),
            name="Water Card",
            rarity=Rarity.RARE,
            biome_affinity=BiomeType.WATER,
            stats={"atk": 70, "def": 90, "meme": 15},
            attacks=[{
                "name": "Water Blast",
                "type": AttackType.WATER.value,
                "damage": 60,
                "energy_cost": 1,
                "effect": "",
                "status_effect": StatusEffect.NONE.value,
            }],
        )
        
        card3 = CardTemplate(
            id=uuid4(),
            name="Grass Card",
            rarity=Rarity.COMMON,
            biome_affinity=BiomeType.GRASS,
            stats={"atk": 50, "def": 50, "meme": 10},
            attacks=[{
                "name": "Basic Attack",
                "type": AttackType.PHYSICAL.value,
                "damage": 40,
                "energy_cost": 1,
                "effect": "",
                "status_effect": StatusEffect.NONE.value,
            }],
        )
        
        deck1 = [card1, card2, card3]
        deck2 = [card1, card2, card3]  # Same deck for testing
        
        # Execute battle
        result = execute_battle(deck1, deck2, BiomeType.NORMAL, "Player 1", "Player 2")
        
        # Verify results
        assert "winner" in result
        assert result["winner"] in [1, 2]
        assert "battle_log" in result
        assert "final_power1" in result
        assert "final_power2" in result
        assert len(result["battle_log"]) > 0
