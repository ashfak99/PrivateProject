
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def solved_skip_kb(question_id: int) -> InlineKeyboardMarkup:
   
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Solved", callback_data=f"q:done:{question_id}")
    kb.button(text="⏭️ Skip",   callback_data=f"q:skip:{question_id}")
    kb.adjust(2)  
    return kb.as_markup()