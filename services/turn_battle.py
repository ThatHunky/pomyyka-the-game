"""
Turn-based battle engine for Pomyyka.

Combines mechanics from:
- D&D (d20 rolls, AC, Initiative)
- Hearthstone (Energy/Mana ramp)
- Pokemon (Active/Bench cards, Types)
"""
import random
from enum import Enum
from typing import List, Optional, Dict
from uuid import UUID

from pydantic import BaseModel, Field

from database.enums import AttackType, BiomeType, StatusEffect
from logging_config import get_logger

logger = get_logger(__name__)

class BattlePhase(str, Enum):
    INITIATIVE = "initiative"
    ACTION = "action"
    END_TURN = "end_turn"
    FINISHED = "finished"

class CardState(BaseModel):
    """Runtime state of a card in battle."""
    id: str  # UserCard UUID string
    template_id: str
    name: str
    rarity: str
    biome: BiomeType
    
    # Stats
    current_hp: int
    max_hp: int
    ac: int  # Armor Class
    initiative_bonus: int
    crit_chance: int  # Base stats.meme
    
    # Status
    is_fainted: bool = False
    status_effects: List[StatusEffect] = Field(default_factory=list)
    
    # Attacks (Snapshot from template)
    attacks: List[Dict] = Field(default_factory=list)
    weakness: Optional[Dict] = None
    resistance: Optional[Dict] = None

class PlayerState(BaseModel):
    """Runtime state of a player."""
    user_id: int
    name: str
    
    # Resources
    current_energy: int = 1
    max_energy: int = 1  # Increases each turn, max 10
    
    # Cards
    deck: List[CardState]
    active_card_index: int = 0  # Index in deck list
    
    @property
    def active_card(self) -> Optional[CardState]:
        if 0 <= self.active_card_index < len(self.deck):
            return self.deck[self.active_card_index]
        return None
        
    @property
    def alive_cards(self) -> List[CardState]:
        return [c for c in self.deck if not c.is_fainted]

class BattleState(BaseModel):
    """Complete state of a battle session."""
    session_id: str
    chat_id: int
    message_id: int = 0
    phase: BattlePhase = BattlePhase.INITIATIVE
    
    # Players
    player1: PlayerState
    player2: PlayerState
    active_player_idx: int = 0 # 1 or 2 (0 means not decided yet or p1)
    
    # State tracking
    turn_number: int = 1
    info_logs: List[str] = Field(default_factory=list) # Rolling log of last N actions

    turn_order: List[int] = Field(default_factory=list) # Queue of player IDs for the current round

    def get_player(self, idx: int) -> PlayerState:
        return self.player1 if idx == 1 else self.player2
    
    def get_opponent(self, idx: int) -> PlayerState:
        return self.player2 if idx == 1 else self.player1
    
    def add_log(self, message: str):
        self.info_logs.append(message)
        if len(self.info_logs) > 5:
            self.info_logs.pop(0)

# --- D&D Mechanics ---

def roll_d20(advantage: bool = False, disadvantage: bool = False) -> int:
    """Roll a 20-sided die."""
    r1 = random.randint(1, 20)
    if advantage and not disadvantage:
        r2 = random.randint(1, 20)
        return max(r1, r2)
    if disadvantage and not advantage:
        r2 = random.randint(1, 20)
        return min(r1, r2)
    return r1

def roll_damage(expression: str) -> int:
    """
    Parses a dice expression like '2d6+3' or '1d8'.
    Simplified parser.
    """
    import re
    match = re.match(r"(\d+)d(\d+)([+-]\d+)?", expression)
    if not match:
        # Fallback for simple integers
        try:
            return int(expression)
        except ValueError:
            return 1
            
    num_dice = int(match.group(1))
    die_type = int(match.group(2))
    modifier = int(match.group(3) or "0")
    
    total = sum(random.randint(1, die_type) for _ in range(num_dice))
    return max(1, total + modifier)

# --- Engine Logic ---

def create_initial_state(
    session_id: str,
    chat_id: int,
    p1_data: Dict,  # {id, name, cards: [UserCard]}
    p2_data: Dict
) -> BattleState:
    """Initialize a new battle state from database objects."""
    
    def _create_deck(cards) -> List[CardState]:
        deck = []
        for card in cards:
            template = card.template
            stats = template.stats
            
            # Calculate HP (Def * 5 + 20) as a baseline
            # In this system, Def acts like Constitution
            hp = stats.get("def", 0) * 5 + 20
            
            # Calculate AC (10 + Agility/2 implied, but we use Def/2 for now)
            ac = 10 + (stats.get("def", 0) // 2)
            
            # Init bonus: Try 'speed', fallback to 'meme' // 2
            init = stats.get("speed", stats.get("meme", 0) // 2)
            
            cs = CardState(
                id=str(card.id),
                template_id=str(template.id),
                name=template.name,
                rarity=template.rarity.value,
                biome=template.biome_affinity,
                current_hp=hp,
                max_hp=hp,
                ac=ac,
                initiative_bonus=init,
                crit_chance=stats.get("meme", 0),
                attacks=template.attacks or [],
                weakness=template.weakness,
                resistance=template.resistance
            )
            deck.append(cs)
        return deck

    p1 = PlayerState(
        user_id=p1_data["id"],
        name=p1_data["name"],
        deck=_create_deck(p1_data["cards"])
    )
    
    p2 = PlayerState(
        user_id=p2_data["id"],
        name=p2_data["name"],
        deck=_create_deck(p2_data["cards"])
    )
    
    return BattleState(
        session_id=session_id,
        chat_id=chat_id,
        player1=p1,
        player2=p2
    )

def resolve_initiative(state: BattleState):
    """Roll initiative for active cards and determine round order."""
    p1_card = state.player1.active_card
    p2_card = state.player2.active_card
    
    if not p1_card or not p2_card:
        return
        
    roll1 = roll_d20() + p1_card.initiative_bonus
    roll2 = roll_d20() + p2_card.initiative_bonus
    
    state.add_log(f"🎲 Ініціатива (Раунд {state.turn_number}): {state.player1.name} ({roll1}) vs {state.player2.name} ({roll2})")
    
    if roll1 >= roll2:
        state.turn_order = [1, 2]
        state.add_log(f"👉 Першим ходить **{state.player1.name}**!")
    else:
        state.turn_order = [2, 1]
        state.add_log(f"👉 Першим ходить **{state.player2.name}**!")
        
    # Start the first turn of the round
    state.active_player_idx = state.turn_order.pop(0)
    _start_turn(state)
    state.phase = BattlePhase.ACTION

def next_turn(state: BattleState):
    """Proceed to next turn in the round, or start new round."""
    if not state.turn_order:
        # End of Round -> New Round
        state.turn_number += 1
        resolve_initiative(state)
    else:
        # Next player in current round
        state.active_player_idx = state.turn_order.pop(0)
        _start_turn(state)

def _start_turn(state: BattleState):
    """Handle start-of-turn logic (mana, status)."""
    player = state.get_player(state.active_player_idx)
    
    # Mana Ramp (Hearthstone style)
    if player.max_energy < 10:
        player.max_energy += 1
    player.current_energy = player.max_energy
    
    state.add_log(f"🔄 Хід {player.name} (🔋 {player.current_energy}/{player.max_energy})")
    
    # Resolve status effects at start of turn
    resolve_status_effects(state)


def execute_attack(state: BattleState, attack_idx: int):
    """Active player attacks opponent's active card."""
    attacker = state.get_player(state.active_player_idx)
    defender = state.get_opponent(state.active_player_idx)
    
    card_atk = attacker.active_card
    card_def = defender.active_card
    
    if not card_atk or not card_def:
        return
    
    if attack_idx >= len(card_atk.attacks):
        return
        
    attack = card_atk.attacks[attack_idx]
    cost = attack.get("energy_cost", 1)
    
    if attacker.current_energy < cost:
        state.add_log(f"⚠️ Недостатньо енергії! Треба {cost}, є {attacker.current_energy}.")
        return

    if card_atk.is_fainted:
        state.add_log(f"⚠️ {card_atk.name} не може атакувати, він знепритомнів.")
        return

    # Check Status Effects that trigger on Attack
    if StatusEffect.CONFUSED in card_atk.status_effects:
        if random.random() < 0.33:
            self_dmg = 5
            card_atk.current_hp -= self_dmg
            attacker.current_energy -= cost # Consume energy on fail?
            state.add_log(f"🌀 {card_atk.name} збентежений і вдарив себе! (-{self_dmg} HP)")
            if card_atk.current_hp <= 0:
                 card_atk.is_fainted = True
                 card_atk.current_hp = 0
                 state.add_log(f"💀 **{card_atk.name}** знепритомнів!")
            return
        
    if StatusEffect.PARALYZED in card_atk.status_effects:
        if random.random() < 0.25:
            attacker.current_energy -= cost
            state.add_log(f"⚡ {card_atk.name} паралізований і не може рухатись!")
            return

    # Check hit (D&D AC)
    attacker.current_energy -= cost
    
    # Determine Status Effect 'hit' logic (simplified: physical attacks check AC, status moves might not?)
    # For now, all attacks check AC.
    
    # Attack Roll
    d20 = roll_d20()
    # Use ATK stat as hit bonus roughly (e.g. ATK / 2)
    # We don't store raw ATK in card state, need to fetch from somewhere or assume it's roughly correlated to damage?
    # Let's assume hitting is based on d20 vs AC flat for now, maybe add small bonus.
    hit_roll = d20 + 2 # Start with small proficiency bonus
    
    is_crit = (d20 == 20)
    is_hit = (hit_roll >= card_def.ac) or is_crit
    
    attack_name = attack.get("name", "Атака")
    
    if is_hit:
        # Damage Roll
        dmg = attack.get("damage", 0) 
        # If string expression (e.g. 2d6)
        if isinstance(dmg, str):
            dmg_val = roll_damage(dmg)
        else:
            dmg_val = int(dmg)
            
        if is_crit:
            dmg_val *= 2
            state.add_log(f"💥 **CRITICAL HIT!** ({d20})")
        else:
            state.add_log(f"⚔️ {attacker.name} атакує: **{hit_roll}** (AC {card_def.ac}) -> Влучив!")
            
        # Weakness/Resistance
        atk_type = AttackType(attack.get("type", "PHYSICAL"))
        multiplier = 1.0
        
        if card_def.weakness and card_def.weakness.get("type") == atk_type:
            multiplier *= 2.0
            state.add_log(f"✨ Ефективно! (x2)")
            
        if card_def.resistance and card_def.resistance.get("type") == atk_type:
             reduction = int(card_def.resistance.get("reduction", 0))
             if reduction > 0:
                 dmg_val = max(0, dmg_val - reduction)
                 state.add_log(f"🛡️ Стійкість! (-{reduction})")
             else:
                 multiplier *= 0.5
                 state.add_log(f"🛡️ Стійкість! (x0.5)")

        final_dmg = int(dmg_val * multiplier)
        
        card_def.current_hp -= final_dmg
        state.add_log(f"🩸 {card_def.name} отримав **{final_dmg}** шкоди. (HP: {card_def.current_hp}/{card_def.max_hp})")
        
        if card_def.current_hp <= 0:
            card_def.is_fainted = True
            card_def.current_hp = 0
            state.add_log(f"💀 **{card_def.name}** знепритомнів!")
            
            # Check win condition
            if not defender.alive_cards:
                state.phase = BattlePhase.FINISHED
                state.add_log(f"🏆 **ПЕРЕМОГА {attacker.name}!**")
            else:
                # Force switch? Or wait for player input?
                # For now, auto-switch to first alive card (simplified)
                for idx, c in enumerate(defender.deck):
                    if not c.is_fainted:
                        defender.active_card_index = idx
                        state.add_log(f"🔄 {defender.name} випускає **{c.name}**!")
                        break
    else:
        state.add_log(f"💨 {attacker.name} атакує: **{hit_roll}** (AC {card_def.ac}) -> Промах!")

def switch_active_card(state: BattleState, deck_index: int):
    """Active player switches their active card. Costs 1 Energy."""
    player = state.get_player(state.active_player_idx)
    
    if player.current_energy < 1:
        state.add_log("⚠️ Недостатньо енергії для заміни (треба 1).")
        return

    if deck_index < 0 or deck_index >= len(player.deck):
        return
        
    target_card = player.deck[deck_index]
    if target_card.is_fainted:
        state.add_log("⚠️ Ця картка знепритомніла.")
        return
        
    if deck_index == player.active_card_index:
        return
        
    player.current_energy -= 1
    player.active_card_index = deck_index
    state.add_log(f"🔄 {player.name} змінює картку на **{target_card.name}**!")

def resolve_status_effects(state: BattleState):
    """Apply start-of-turn status effects (Burn, Poison, etc)."""
    player = state.get_player(state.active_player_idx)
    card = player.active_card
    
    if not card or card.is_fainted:
        return
        
    new_statuses = []
    can_act = True
    
    for status in card.status_effects:
        if status == StatusEffect.BURNED:
            dmg = 10
            card.current_hp -= dmg
            state.add_log(f"🔥 {card.name} горить: -{dmg} HP")
            new_statuses.append(status)
        elif status == StatusEffect.POISONED:
            dmg = 10 
            card.current_hp -= dmg
            state.add_log(f"☠️ {card.name} отруєний: -{dmg} HP")
            new_statuses.append(status)
        elif status == StatusEffect.FROZEN:
            if random.random() < 0.2:
                state.add_log(f"❄️ {card.name} розтанув!")
                # Thawed, so don't add back Frozen
            else:
                state.add_log(f"❄️ {card.name} заморожений!")
                new_statuses.append(status)
                # Frozen prevents action? Usually yes.
                # But implementation might just limit attacks.
                # For now let's just keep the status.
        elif status == StatusEffect.ASLEEP:
            if random.random() < 0.33: # 33% chance to wake
                 state.add_log(f"💤 {card.name} прокинувся!")
            else:
                 state.add_log(f"💤 {card.name} спить...")
                 new_statuses.append(status)
                 can_act = False # Skip turn
        elif status == StatusEffect.PARALYZED:
             new_statuses.append(status)
             # Paralyzed check happens on attack
        elif status == StatusEffect.CONFUSED:
             new_statuses.append(status)
             # Confused check happens on attack

    card.status_effects = new_statuses
    if card.current_hp <= 0:
        card.current_hp = 0
        card.is_fainted = True
        state.add_log(f"💀 **{card.name}** загинув від статусів!")
        
    if not can_act:
        state.add_log(f"🛑 {card.name} пропускає хід через статус.")
        player.current_energy = 0 # Prevent actions
