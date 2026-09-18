import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.keyboards.onboarding_kb import year_kb

kb = year_kb()
print("Type:", type(kb).__name__)
print("Rows:", len(kb.inline_keyboard))
for i, row in enumerate(kb.inline_keyboard):
    print(f"Row {i}:")
    for btn in row:
        print(f"   text={btn.text!r}  cb={btn.callback_data!r}")