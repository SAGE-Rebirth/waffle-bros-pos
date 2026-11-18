"""First-run starter menu. Prices are placeholders; the owner edits them in Settings -> Menu."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waffle_pos.db.models import Category, Item

CATEGORIES = ["Waffle", "Sandwich", "Combo", "Mini Waffle"]

# code, name, category, price, ingredient cost
STARTER_MENU: list[tuple[str, str, str, float, float]] = [
    ("W01", "Classic Maple Butter", "Waffle", 129, 40),
    ("W02", "Dark Chocolate", "Waffle", 149, 48),
    ("W03", "Milk Chocolate", "Waffle", 149, 46),
    ("W04", "Triple Chocolate", "Waffle", 189, 62),
    ("W05", "Nutella", "Waffle", 199, 70),
    ("W06", "KitKat Crunch", "Waffle", 189, 60),
    ("W07", "Red Velvet Cream Cheese", "Waffle", 199, 66),
    ("W08", "Lotus Biscoff", "Waffle", 219, 78),
    ("W09", "Honey Banana", "Waffle", 159, 45),
    ("S01", "Veg Grilled Waffle Sandwich", "Sandwich", 139, 42),
    ("S02", "Paneer Tikka Waffle Sandwich", "Sandwich", 169, 55),
    ("S03", "Cheese Corn Waffle Sandwich", "Sandwich", 149, 45),
    ("C01", "Waffle + Cold Coffee", "Combo", 229, 75),
    ("C02", "Any 2 Waffles (Duo)", "Combo", 299, 100),
    ("C03", "Family Pack (4 Waffles)", "Combo", 549, 190),
    ("M01", "Mini Waffle Bites Chocolate (6 pc)", "Mini Waffle", 99, 30),
    ("M02", "Mini Waffle Bites Nutella (6 pc)", "Mini Waffle", 129, 42),
    ("M03", "Mini Pancake Bites (10 pc)", "Mini Waffle", 109, 32),
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
