"""Menu: categories and items. Prices and costs are in rupees."""

from typing import Annotated, Any

from fastapi import APIRouter, Path

from waffle_pos.api.deps import ADMIN_401, DB, INVALID, AdminOnly, bad_request, errors
from waffle_pos.schemas import CategoryIn, DeleteItemOut, IdOut, ItemIn, MenuOut, OkOut, ReorderIn
from waffle_pos.services import menu

router = APIRouter(prefix="/api", tags=["menu"])
# Every write below needs the admin PIN token; reading the menu is public (the billing screen needs it).
ADMIN: dict[str, Any] = {"dependencies": [AdminOnly]}

ItemId = Annotated[int, Path(description="The item's numeric `id` (not its short code like `W01`).")]


@router.get("/menu", summary="Get the full menu")
def get_menu(db: DB) -> MenuOut:
    """All categories (in display order) and all items, including hidden ones (`active: false`).

    The billing screen shows only active items; hidden items stay so old bills still make sense.
    """
    return menu.get_menu(db)


@router.post(
    "/categories",
    **ADMIN,
    summary="Add a menu category",
    responses=errors({401: ADMIN_401, 400: "That category already exists (case-insensitive).", 422: INVALID}),
)
def add_category(body: CategoryIn, db: DB) -> IdOut:
    """Create a category at the end of the list. Returns the new category's `id`."""
    try:
        return IdOut(id=menu.add_category(db, body.name).id)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e


@router.post(
    "/items",
    **ADMIN,
    summary="Add a menu item",
    responses=errors(
        {401: ADMIN_401, 400: "The `code` is already used, or `category_id` does not exist.", 422: INVALID}
    ),
)
def create_item(body: ItemIn, db: DB) -> IdOut:
    """Create an item. `code` is upper-cased; `price` and `cost` are rupees (cost is optional and
    only feeds the margin numbers). Returns the new item's `id`.

    GST is not an item field: it's the `gst` module (`PUT /api/admin/modules/gst`).
    """
    try:
        return IdOut(id=menu.create_item(db, body).id)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e


@router.put(
    "/items/{item_id}",
    **ADMIN,
    summary="Update a menu item",
    responses=errors(
        {
            401: ADMIN_401,
            400: "The `code` is already used by another item, or `category_id` does not exist.",
            404: "No item with that id.",
            422: INVALID,
        }
    ),
)
def update_item(item_id: ItemId, body: ItemIn, db: DB) -> OkOut:
    """Replace every field of an item (send the whole item, as for create).

    A price change applies to new bills only; past bills keep the price they were billed at.
    Set `active: false` to hide an item from the billing screen, `true` to bring it back.
    """
    try:
        item = menu.update_item(db, item_id, body)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e
    if item is None:
        raise bad_request("Item not found", 404)
    return OkOut()


@router.delete(
    "/items/{item_id}",
    **ADMIN,
    summary="Delete or hide a menu item",
    responses=errors({401: ADMIN_401, 422: INVALID}),
)
def delete_item(item_id: ItemId, db: DB) -> DeleteItemOut:
    """Delete an item that has never been billed. An item that appears on past bills is hidden
    instead (`active` set to false) and the response says `hidden: true`.

    An unknown id is not an error: the response is `{"ok": true, "hidden": false}`.
    """
    return DeleteItemOut(hidden=menu.remove_item(db, item_id))


CategoryId = Annotated[int, Path(description="The category's numeric `id`.")]


@router.put(
    "/categories/{category_id}",
    **ADMIN,
    summary="Rename a menu category",
    responses=errors(
        {401: ADMIN_401, 400: "Another category has that name.", 404: "No such category.", 422: INVALID}
    ),
)
def rename_category(category_id: CategoryId, body: CategoryIn, db: DB) -> OkOut:
    """Rename a category. Past bills keep the category name they were billed under."""
    try:
        cat = menu.rename_category(db, category_id, body.name)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e
    if cat is None:
        raise bad_request("Category not found", 404)
    return OkOut()


@router.delete(
    "/categories/{category_id}",
    **ADMIN,
    summary="Delete an empty menu category",
    responses=errors({401: ADMIN_401, 400: "The category still has items.", 404: "No such category."}),
)
def delete_category(category_id: CategoryId, db: DB) -> OkOut:
    """Delete a category that has no items (hidden items count). Move or remove its items first."""
    try:
        found = menu.delete_category(db, category_id)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e
    if not found:
        raise bad_request("Category not found", 404)
    return OkOut()


@router.post(
    "/categories/reorder",
    **ADMIN,
    summary="Set the order of menu categories",
    responses=errors({401: ADMIN_401, 400: "An id doesn't exist.", 422: INVALID}),
)
def reorder_categories(body: ReorderIn, db: DB) -> OkOut:
    """Categories in `ids` come first, in that order (the billing sidebar order); any not listed follow."""
    try:
        menu.reorder_categories(db, body.ids)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e
    return OkOut()


@router.post(
    "/items/reorder",
    **ADMIN,
    summary="Set the order of menu items",
    responses=errors({401: ADMIN_401, 400: "An id doesn't exist.", 422: INVALID}),
)
def reorder_items(body: ReorderIn, db: DB) -> OkOut:
    """Items in `ids` are placed first, in that order. Send one category's items to reorder that category."""
    try:
        menu.reorder_items(db, body.ids)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e
    return OkOut()
