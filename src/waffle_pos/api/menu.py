from fastapi import APIRouter

from waffle_pos.api.deps import DB, bad_request
from waffle_pos.schemas import CategoryIn, DeleteItemOut, IdOut, ItemIn, MenuOut, OkOut
from waffle_pos.services import menu

router = APIRouter(prefix="/api", tags=["menu"])


@router.get("/menu")
def get_menu(db: DB) -> MenuOut:
    return menu.get_menu(db)


@router.post("/categories")
def add_category(body: CategoryIn, db: DB) -> IdOut:
    try:
        return IdOut(id=menu.add_category(db, body.name).id)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e


@router.post("/items")
def create_item(body: ItemIn, db: DB) -> IdOut:
    try:
        return IdOut(id=menu.create_item(db, body).id)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemIn, db: DB) -> OkOut:
    try:
        item = menu.update_item(db, item_id, body)
    except menu.MenuError as e:
        raise bad_request(str(e)) from e
    if item is None:
        raise bad_request("Item not found", 404)
    return OkOut()


@router.delete("/items/{item_id}")
def delete_item(item_id: int, db: DB) -> DeleteItemOut:
    return DeleteItemOut(hidden=menu.remove_item(db, item_id))
