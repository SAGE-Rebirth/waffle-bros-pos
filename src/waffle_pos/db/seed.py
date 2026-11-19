"""First-run menu: the launch menu agreed in Nov 2026 (all veg and eggless).

Costs and prices come from the menu costing sheet (menu-costing/pos-menu-costs.csv).
This only fills an empty database; after that the owner edits the menu in Admin -> Menu.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waffle_pos.db.models import Category, Item

CATEGORIES = ["Waffle", "Mini Waffle", "Bowl", "Snacks", "Combo"]

# code, name, category, price, cost (ingredients + packaging), in menu order.
# Combos: C01 S01+M01, C02 W01+W02, C03 W04+B01, C04 M01+M02+M03, C05 W01+W03+M01+M02+2x S02.
STARTER_MENU: list[tuple[str, str, str, float, float]] = [
    ("W01", "Amul Dark Chocolate Waffle", "Waffle", 129, 46),
    ("W02", "White Chocolate Waffle", "Waffle", 129, 45),
    ("W03", "Nutella Waffle", "Waffle", 189, 67),
    ("W04", "Triple Chocolate Waffle", "Waffle", 159, 52),
    ("M01", "Amul Dark Chocolate Mini Waffle", "Mini Waffle", 89, 29),
    ("M02", "White Chocolate Mini Waffle", "Mini Waffle", 89, 29),
    ("M03", "Nutella Mini Waffle", "Mini Waffle", 119, 42),
    ("B01", "Amul Dark Chocolate Bowl", "Bowl", 129, 45),
    ("B02", "White Chocolate Bowl", "Bowl", 129, 44),
    ("B03", "Nutella Bowl", "Bowl", 179, 62),
    ("S01", "Veg Sandwich", "Snacks", 59, 22),
    ("S02", "Veg Cheese Sandwich", "Snacks", 79, 30),
    ("S03", "Corn Sandwich", "Snacks", 89, 34),
    ("S04", "Paneer Patties", "Snacks", 45, 21),
    ("S05", "Aaloo Patties", "Snacks", 29, 15),
    ("C01", "Snack Break", "Combo", 129, 51),
    ("C02", "Waffle Duo", "Combo", 229, 91),
    ("C03", "Chocolate Overload", "Combo", 259, 96),
    ("C04", "Mini Party", "Combo", 249, 98),
    ("C05", "Family Feast", "Combo", 569, 222),
]


def seed_if_empty(session: Session) -> bool:
    if session.scalar(select(func.count()).select_from(Category)):
        return False
    cats = {name: Category(name=name, sort=i) for i, name in enumerate(CATEGORIES)}
    session.add_all(cats.values())
    session.add_all(
        Item(code=code, name=name, category=cats[cat], price=price, cost=cost, sort=i)
        for i, (code, name, cat, price, cost) in enumerate(STARTER_MENU)
    )
    session.flush()
    return True
