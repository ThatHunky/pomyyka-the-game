"""
Handlers for the new Turn-Based Battle System.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData

from services.turn_battle import (
    BattleState, BattlePhase, 
    execute_attack, switch_active_card, next_turn, resolve_initiative, resolve_status_effects
)
from services.session_manager import SessionManager
from logging_config import get_logger
from utils.telegram_utils import safe_callback_answer

logger = get_logger(__name__)
router = Router(name="turn_battle")
session_manager = SessionManager()

# --- Callbacks ---

class BattleActionCallback(CallbackData, prefix="tb"):
    session_id: str
    action: str  # attack, switch, pass, refresh
    index: int = 0  # attack index or deck index

# --- UI Rendering ---

def render_battle_ui(state: BattleState, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Render the battle UI for a specific user."""
    
    # Determine perspective
    is_p1 = (user_id == state.player1.user_id)
    me = state.player1 if is_p1 else state.player2
    opp = state.player2 if is_p1 else state.player1
    
    is_my_turn = (state.active_player_idx == (1 if is_p1 else 2)) and (state.phase == BattlePhase.ACTION)
    
    # --- Text Generation ---
    text = f"⚔️ **РАУНД {state.turn_number}**\n\n"
    
    # Opponent Status
    opp_active = opp.active_card
    if opp_active:
        hp_bar = _make_bar(opp_active.current_hp, opp_active.max_hp, 10)
        text += f"👤 **{opp.name}** (🔋 {opp.current_energy}/{opp.max_energy})\n"
        text += f"👾 **{opp_active.name}** {hp_bar} ({opp_active.current_hp}/{opp_active.max_hp})\n"
        status_icons = "".join([s.value for s in opp_active.status_effects])
        if status_icons:
            text += f"   {status_icons}\n"
        text += f"   🛡️ AC: {opp_active.ac}\n"
    else:
        text += f"👤 **{opp.name}** має обрати картку!\n"
    
    text += "\n🆚\n\n"
    
    # My Status
    my_active = me.active_card
    if my_active:
        hp_bar = _make_bar(my_active.current_hp, my_active.max_hp, 10)
        text += f"👤 **Я** (🔋 {me.current_energy}/{me.max_energy})\n"
        text += f"👾 **{my_active.name}** {hp_bar} ({my_active.current_hp}/{my_active.max_hp})\n"
        status_icons = "".join([s.value for s in my_active.status_effects])
        if status_icons:
            text += f"   {status_icons}\n"
        text += f"   🛡️ AC: {my_active.ac}\n"
    else:
        text += f"👤 **Я** маю обрати картку!\n"
        
    text += "\n📜 **Хід бою:**\n"
    for log in state.info_logs[-3:]:
        text += f"• {log}\n"
        
    if state.phase == BattlePhase.FINISHED:
        text += "\n🏁 **БІЙ ЗАВЕРШЕНО!**"
        
    # --- Keyboard Generation ---
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    
    if state.phase == BattlePhase.FINISHED:
        return text, kb
        
    if is_my_turn:
        # Attack Buttons
        if my_active and not my_active.is_fainted:
            row = []
            for idx, atk in enumerate(my_active.attacks):
                name = atk.get("name", "Hit")
                cost = atk.get("energy_cost", 1)
                # Mark affordable
                prefix = "✅" if me.current_energy >= cost else "❌"
                
                row.append(InlineKeyboardButton(
                    text=f"{prefix} {name} ({cost}⚡)",
                    callback_data=BattleActionCallback(
                        session_id=state.session_id,
                        action="attack",
                        index=idx
                    ).pack()
                ))
                if len(row) == 2:
                    kb.inline_keyboard.append(row)
                    row = []
            if row:
                kb.inline_keyboard.append(row)
        
        # Action Buttons
        actions_row = []
        
        # Switch Button (opens switch menu? simplified: just cycle next for now or show list?)
        # Let's show "Switch" button only if we have bench
        bench_count = len([c for c in me.deck if not c.is_fainted]) - 1
        if bench_count > 0:
             actions_row.append(InlineKeyboardButton(
                text=f"🔄 Заміна ({bench_count})",
                callback_data=BattleActionCallback(
                    session_id=state.session_id, # We'll need a submenu for this ideally
                    action="switch_menu",
                    index=0
                ).pack()
            ))
            
        actions_row.append(InlineKeyboardButton(
            text="⏭️ Завершити хід",
            callback_data=BattleActionCallback(
                session_id=state.session_id,
                action="pass"
            ).pack()
        ))
        kb.inline_keyboard.append(actions_row)
        
    else:
        # Refresh button for opponent
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text="🔄 Оновити статус",
                callback_data=BattleActionCallback(
                    session_id=state.session_id,
                    action="refresh"
                ).pack()
            )
        ])

    return text, kb

def _make_bar(current, maximum, length=10) -> str:
    """Generate ASCII progress bar."""
    pct = max(0, min(1, current / maximum)) if maximum > 0 else 0
    filled = int(length * pct)
    return "█" * filled + "░" * (length - filled)


# --- Handlers ---

@router.callback_query(BattleActionCallback.filter())
async def handle_battle_action(callback: CallbackQuery, callback_data: BattleActionCallback):
    """Handle battle actions."""
    if not callback.message:
        return
        
    session_id = callback_data.session_id
    state = await session_manager.get_turn_battle_state(session_id)
    
    if not state:
        await safe_callback_answer(callback, "Session expired", show_alert=True)
        return
        
    user_id = callback.from_user.id
    is_p1 = (user_id == state.player1.user_id)
    player_num = 1 if is_p1 else 2
    
    # Handle Refresh
    if callback_data.action == "refresh":
        text, markup = render_battle_ui(state, user_id)
        # Check if content changed to avoid errors
        try:
            await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
        except:
            pass
        await safe_callback_answer(callback)
        return

    # Check Turn
    if state.active_player_idx != player_num:
        await safe_callback_answer(callback, "Not your turn!", show_alert=True)
        return
        
    # Execute Action
    action = callback_data.action
    
    if action == "attack":
        execute_attack(state, callback_data.index)
        
    elif action == "pass":
        next_turn(state)
        resolve_status_effects(state)
        
    elif action == "switch_menu":
        # Show switch options (Special view)
        await show_switch_menu(callback, state, user_id)
        return
        
    elif action == "switch":
        switch_active_card(state, callback_data.index)
        # End turn after switch? Or just cost energy?
        # Current engine: costs 1 energy.
        
    # Check Game Over
    if state.phase == BattlePhase.FINISHED:
        # TODO: Process rewards here (call existing logic from battles.py?)
        pass

    # Save State
    await session_manager.save_turn_battle_state(state)
    
    # Update UI
    text, markup = render_battle_ui(state, user_id)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await safe_callback_answer(callback)


async def show_switch_menu(callback: CallbackQuery, state: BattleState, user_id: int):
    """Show list of bench cards to switch to."""
    is_p1 = (user_id == state.player1.user_id)
    me = state.player1 if is_p1 else state.player2
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for idx, card in enumerate(me.deck):
        if idx == me.active_card_index:
            continue
            
        status = "💀" if card.is_fainted else "❤️"
        text = f"{card.name} ({status} {card.current_hp}/{card.max_hp})"
        
        if not card.is_fainted:
            kb.inline_keyboard.append([
                InlineKeyboardButton(
                    text=text,
                    callback_data=BattleActionCallback(
                        session_id=state.session_id,
                        action="switch",
                        index=idx
                    ).pack()
                )
            ])
            
    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text="🔙 В бій",
            callback_data=BattleActionCallback(
                session_id=state.session_id,
                action="refresh"
            ).pack()
        )
    ])
    
    await callback.message.edit_text("🔄 **Виберіть картку для заміни (1⚡):**", reply_markup=kb, parse_mode="Markdown")
    await safe_callback_answer(callback)
