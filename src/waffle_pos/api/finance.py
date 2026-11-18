"""Monthly targets and expenses."""

import re
from typing import Any

from fastapi import APIRouter

from waffle_pos import clock
from waffle_pos.api.deps import DB, bad_request
from waffle_pos.db.models import Expense, Target
from waffle_pos.schemas import ExpenseIn, IdOut, OkOut, TargetIn
from waffle_pos.services import analytics
from waffle_pos.services.settings import set_settings

router = APIRouter(prefix="/api", tags=["finance"])
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@router.put("/targets/{month}")
def set_target(month: str, body: TargetIn, db: DB) -> OkOut:
    if not MONTH_RE.match(month):
        raise bad_request("Enter a valid month (YYYY-MM)")
    row = db.get(Target, month)
    if row is None:
        db.add(Target(month=month, amount=body.amount))
    else:
        row.amount = body.amount
    if body.makeDefault:
        set_settings(db, {"default_target": f"{body.amount:g}"})
    return OkOut()


@router.get("/expenses")
def list_expenses(db: DB, month: str | None = None) -> dict[str, Any]:
    if month is not None and not MONTH_RE.match(month):
        raise bad_request("Enter a valid month (YYYY-MM)")
    return analytics.month_expenses(db, month or clock.month_key(clock.today()))


@router.post("/expenses")
def add_expense(body: ExpenseIn, db: DB) -> IdOut:
    exp = Expense(
        date=body.date or clock.today(),
        category=body.category,
        amount=body.amount,
        note=body.note or None,
        recurring=body.recurring,
    )
    db.add(exp)
    db.flush()
    return IdOut(id=exp.id)


@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int, db: DB) -> OkOut:
    exp = db.get(Expense, expense_id)
    if exp is not None:
        db.delete(exp)
    return OkOut()
