"""Menu: categories and items."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from waffle_pos.db.models import Category, Item, OrderItem
from waffle_pos.schemas import CategoryOut, ItemIn, ItemOut, MenuOut


class MenuError(ValueError):
    pass


def item_out(item: Item) -> ItemOut:
    return ItemOut(
        id=item.id,
        code=item.code,
        name=item.name,
        category_id=item.category_id,
        category=item.category.name,
        price=item.price,
        cost=item.cost,
        image=item.image,
        veg=item.veg,
        active=item.active,
        sort=item.sort,
    )


def get_menu(session: Session) -> MenuOut:
    cats = list(session.scalars(select(Category).order_by(Category.sort, Category.id)))
    items = session.scalars(
        select(Item)
        .join(Item.category)
        .options(selectinload(Item.category))
        .order_by(Category.sort, Item.sort, Item.code)
    )
    return MenuOut(
        categories=[CategoryOut.model_validate(c) for c in cats], items=[item_out(i) for i in items]
    )


def add_category(session: Session, name: str) -> Category:
    if session.scalar(select(Category).where(func.lower(Category.name) == name.lower())):
        raise MenuError("That category already exists")
    sort = (session.scalar(select(func.max(Category.sort))) or 0) + 1
    cat = Category(name=name, sort=sort)
    session.add(cat)
    session.flush()
    return cat


def _apply(session: Session, item: Item, data: ItemIn) -> None:
    if session.get(Category, data.category_id) is None:
        raise MenuError("Pick a valid category")
    clash = session.scalar(select(Item).where(Item.code == data.code, Item.id != (item.id or -1)))
    if clash is not None:
        raise MenuError("That item ID is already used")
    for field, value in data.model_dump().items():
        setattr(item, field, value)


def create_item(session: Session, data: ItemIn) -> Item:
    item = Item()
    _apply(session, item, data)
    session.add(item)
    try:
        session.flush()
    except IntegrityError as e:  # pragma: no cover - guarded above, kept for races
        raise MenuError("That item ID is already used") from e
    return item


def update_item(session: Session, item_id: int, data: ItemIn) -> Item | None:
    item = session.get(Item, item_id)
    if item is None:
        return None
    _apply(session, item, data)
    session.flush()
    return item


def remove_item(session: Session, item_id: int) -> bool:
    """Delete an item, or hide it if past bills reference it. Returns True when hidden."""
    item = session.get(Item, item_id)
    if item is None:
        return False
    used = session.scalar(select(OrderItem.id).where(OrderItem.item_id == item_id).limit(1))
    if used is not None:
        item.active = False
    else:
        session.delete(item)
    session.flush()
    return used is not None


def rename_category(session: Session, category_id: int, name: str) -> Category | None:
    cat = session.get(Category, category_id)
    if cat is None:
        return None
    clash = session.scalar(
        select(Category).where(func.lower(Category.name) == name.lower(), Category.id != category_id)
    )
    if clash is not None:
        raise MenuError("That category already exists")
    cat.name = name
    session.flush()
    return cat


def delete_category(session: Session, category_id: int) -> bool:
    """Delete an empty category. Returns False if it doesn't exist."""
    cat = session.get(Category, category_id)
    if cat is None:
        return False
    if session.scalar(select(Item.id).where(Item.category_id == category_id).limit(1)) is not None:
        raise MenuError("Move or remove this category's items first")
    session.delete(cat)
    session.flush()
    return True


def reorder_categories(session: Session, ids: list[int]) -> None:
    """Set display order: categories listed first, in the given order; any others keep their order after."""
    _reorder(session, Category, ids)


def reorder_items(session: Session, ids: list[int]) -> None:
    """Set the display order of the given items (usually one category's items)."""
    _reorder(session, Item, ids)


def _reorder[M: (Category, Item)](session: Session, model: type[M], ids: list[int]) -> None:
    rows = {r.id: r for r in session.scalars(select(model).order_by(model.sort, model.id))}
    unknown = [i for i in ids if i not in rows]
    if unknown:
        raise MenuError(f"Unknown id {unknown[0]}")
    wanted = set(ids)
    ordered: list[M] = [rows[i] for i in dict.fromkeys(ids)]
    rest: list[M] = [r for r in rows.values() if r.id not in wanted]
    for position, row in enumerate([*ordered, *rest]):
        row.sort = position
    session.flush()
