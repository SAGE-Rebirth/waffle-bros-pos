"""Monthly targets and expenses. Amounts are in rupees."""

import re
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query

from waffle_pos import clock
from waffle_pos.api.deps import ADMIN_401, ADMIN_403, DB, INVALID, AdminOnly, bad_request, errors
from waffle_pos.db.models import Expense, Target
from waffle_pos.modules.registry import save_settings
from waffle_pos.schemas import ExpenseIn, IdOut, MonthExpensesOut, OkOut, TargetIn
from waffle_pos.services import analytics

router = APIRouter(prefix="/api", tags=["finance"])
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
BAD_MONTH = 'The month is not `YYYY-MM` ("Enter a valid month (YYYY-MM)").'


@router.put(
    "/targets/{month}",
    summary="Set a month's revenue target (Admin)",
    dependencies=[AdminOnly],
    responses=errors({400: BAD_MONTH, 401: ADMIN_401, 403: ADMIN_403, 422: INVALID}),
)
def set_target(
    month: Annotated[str, Path(description="The month, `YYYY-MM`, e.g. `2026-11`.")],
    body: TargetIn,
    db: DB,
) -> OkOut:
    """Set (or replace) the revenue target for one month, in rupees. With `makeDefault: true` the
    amount also becomes the `default_target` setting, used for every month without its own target.
    """
    if not MONTH_RE.match(month):
        raise bad_request("Enter a valid month (YYYY-MM)")
    row = db.get(Target, month)
    if row is None:
        db.add(Target(month=month, amount=body.amount))
    else:
        row.amount = body.amount
    if body.makeDefault:
        save_settings(db, "targets", {"default_target": body.amount})
    return OkOut()


@router.get(
    "/expenses",
    summary="List a month's expenses",
    response_model=None,  # documented by MonthExpensesOut below; the dict is returned as-is
    responses={
        200: {"model": MonthExpensesOut, "description": "The month's expenses and totals."},
        **errors({400: BAD_MONTH, 422: INVALID}),
    },
)
def list_expenses(
    db: DB,
    month: Annotated[
        str | None, Query(description="The month, `YYYY-MM`. Defaults to the current month.")
    ] = None,
) -> dict[str, Any]:
    """Expenses counted against a month, with totals in rupees. One-off expenses count in the
    month of their `date`; recurring (monthly) ones count in every month from the month of their
    `date` onwards. `byCategory` is sorted biggest first; lists are newest first.
    """
    if month is not None and not MONTH_RE.match(month):
        raise bad_request("Enter a valid month (YYYY-MM)")
    return analytics.month_expenses(db, month or clock.month_key(clock.today()))


@router.post(
    "/expenses",
    summary="Add an expense (Admin)",
    dependencies=[AdminOnly],
    responses=errors({401: ADMIN_401, 403: ADMIN_403, 422: INVALID}),
)
def add_expense(body: ExpenseIn, db: DB) -> IdOut:
    """Log an expense in rupees. `category` is free text, stored lower-case (the app suggests rent,
    salary, ingredients, electricity, packaging, marketing, maintenance, other). `date` defaults to today.
    Set `recurring: true` for a monthly cost such as rent or salaries: it then counts in every
    month from `date` on. Returns the new expense's `id`; queued for the next Google Sheet sync.
    """
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


@router.delete(
    "/expenses/{expense_id}",
    summary="Delete an expense (Admin)",
    dependencies=[AdminOnly],
    responses=errors({401: ADMIN_401, 403: ADMIN_403, 422: INVALID}),
)
def delete_expense(expense_id: Annotated[int, Path(description="The expense's `id`.")], db: DB) -> OkOut:
    """Delete an expense for good (a recurring one stops counting in every month). An unknown id is
    not an error. Rows already pushed to the Google Sheet stay there.
    """
    exp = db.get(Expense, expense_id)
    if exp is not None:
        db.delete(exp)
    return OkOut()
