from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.model import Year, Level, Org_type

def year_kb()->InlineKeyboardMarkup:
    kb=InlineKeyboardBuilder()
    for y in Year:
        kb.button(text=y.value, callback_data=f"onboard:year:{y.name}")
    kb.adjust(3,2)
    return kb.as_markup()

def org_type_kb()->InlineKeyboardMarkup:
    kb=InlineKeyboardBuilder()
    for ot in Org_type:
        kb.button(text=ot.name, callback_data=f"onboard:org:{ot.name}")
    kb.adjust(3)
    return kb.as_markup()

def level_kb()->InlineKeyboardMarkup:
    kb=InlineKeyboardBuilder()
    for l in Level:
        kb.button(text=l.value, callback_data=f"onboard:level:{l.name}")
    kb.adjust(3)
    return kb.as_markup()