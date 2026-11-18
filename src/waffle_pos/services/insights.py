"""Plain-English tips for the owner, ported from the Node ``insights()``.

Each tip is ``{tone, title, text}`` with tone ``good`` | ``warn`` | ``info``.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from waffle_pos.modules.builtin import TargetSettings
from waffle_pos.modules.registry import settings_of
from waffle_pos.services.analytics import charts, item_stats, target_summary
from waffle_pos.services.fmt import inr, num
from waffle_pos.services.targets import js_round

Add = Callable[[str, str, str], None]  # add(tone, title, text)


def insights(session: Session, now: datetime) -> list[dict[str, str]]:
    t = target_summary(session, now)
    out: list[dict[str, str]] = []

    def add(tone: str, title: str, text: str) -> None:
        out.append({"tone": tone, "title": title, "text": text})

    if t["revenue"] == 0 and t["orders"] == 0:
        add(
            "info",
            "No sales yet this month",
            f"Your target is {inr(t['target'])}. That is {inr(t['evenDailyTarget'])} a day at an even pace. "
            "Bill your first order to start tracking.",
        )
        return out

    c = charts(session, now)
    it = item_stats(session, "30d", now)

    _pace(t, add)
    _today(t, add)
    _average_bill(t, add)
    _expenses(t, add)
    _hours(c["hourly"], add)
    _weekdays(c["weekday"], add)
    _menu(it, add, settings_of(session, "targets", TargetSettings))
    return out


def _pace(t: dict[str, Any], add: Add) -> None:
    gap = t["projected"] - t["target"]
    if gap >= 0:
        add(
            "good",
            "On track for the monthly target",
            f"At your current average of {inr(t['avgDaily'])}/day you'll finish around "
            f"{inr(t['projected'])}, {inr(gap)} above the {inr(t['target'])} target.",
        )
    else:
        add(
            "warn",
            "Behind the monthly target",
            f"At {inr(t['avgDaily'])}/day you'll finish around {inr(t['projected'])}, {inr(-gap)} short. "
            f"You need {inr(t['requiredDailyFromTomorrow'])}/day from tomorrow "
            f"(vs {inr(t['evenDailyTarget'])} at an even pace).",
        )


def _today(t: dict[str, Any], add: Add) -> None:
    if t["remaining"] <= 0:
        suggested = js_round(t["projected"] / 5000) * 5000
        add(
            "good",
            "Monthly target reached",
            f"{inr(t['revenue'])} so far against {inr(t['target'])}. "
            f"Consider raising next month's target to around {inr(suggested)}.",
        )
    elif t["todayRemaining"] > 0:
        more = (
            f", about {t['ordersNeededToday']} more orders at your average bill of {inr(t['aov'])}"
            if t["ordersNeededToday"]
            else ""
        )
        add(
            "info",
            "Today's goal",
            f"{inr(t['todayRevenue'])} of {inr(t['todayTarget'])} done. "
            f"{inr(t['todayRemaining'])} to go{more}.",
        )
    else:
        add(
            "good",
            "Today's goal reached",
            f"{inr(t['todayRevenue'])} today against a goal of {inr(t['todayTarget'])}. "
            "Every extra rupee lowers tomorrow's target.",
        )


def _average_bill(t: dict[str, Any], add: Add) -> None:
    if t["aov"] > 0:
        plus20 = t["orders"] * 20 * (t["daysInMonth"] / t["dayOfMonth"])
        add(
            "info",
            f"Average bill {inr(t['aov'])}",
            "Adding ₹20 to the average bill (an add-on topping, a drink in a combo) would bring in "
            f"roughly {inr(plus20)} more this month without any new customers.",
        )


def _expenses(t: dict[str, Any], add: Add) -> None:
    exp = t["expenses"]
    if exp["total"] <= 0:
        add(
            "info",
            "Add your expenses",
            "Enter rent, salaries, ingredients and bills on the Dashboard so profit and break-even "
            "can be worked out.",
        )
        return
    pct = exp["total"] / t["revenue"] * 100 if t["revenue"] else 0.0
    if t["netProfit"] < 0:
        add(
            "warn",
            "Not covering expenses yet",
            f"Expenses this month are {inr(exp['total'])} against {inr(t['revenue'])} in sales. "
            f"Break-even needs {inr(t['breakEvenRemainingDaily'])}/day for the rest of the month.",
        )
    else:
        add(
            "warn" if pct > 70 else "good",
            f"Net so far {inr(t['netProfit'])}",
            f"Expenses are {js_round(pct)}% of sales ({inr(exp['total'])}). "
            f"Your daily break-even is {inr(t['breakEvenDaily'])}.",
        )
    if exp["byCategory"]:
        top = exp["byCategory"][0]
        name = top["category"][:1].upper() + top["category"][1:]
        add(
            "info",
            f"Biggest cost: {name}",
            f"{inr(top['amount'])} this month, "
            f"{js_round(top['amount'] / exp['total'] * 100)}% of all expenses.",
        )


def _hours(hourly: list[dict[str, Any]], add: Add) -> None:
    hrs = [h for h in hourly if h["average"] > 0]
    if len(hrs) >= 3:
        peak = max(hrs, key=lambda h: h["average"])
        quiet = min(hrs, key=lambda h: h["average"])
        add(
            "info",
            f"Busiest hour: {peak['label']}",
            f"Averages {inr(peak['average'])}. Keep batter and toppings prepped before then. "
            f"Quietest is {quiet['label']} ({inr(quiet['average'])}), a good slot for a happy-hour offer "
            "or mini-waffle deal.",
        )


def _weekdays(weekday: list[dict[str, Any]], add: Add) -> None:
    wds = [w for w in weekday if w["average"] > 0]
    if len(wds) >= 4:
        best = max(wds, key=lambda w: w["average"])
        worst = min(wds, key=lambda w: w["average"])
        add(
            "info",
            f"{best['day']} is your strongest day",
            f"Averages {inr(best['average'])} vs {inr(worst['average'])} on {worst['day']}. "
            f"Try a {worst['day']}-only offer for the apartment residents.",
        )


def _menu(it: dict[str, Any], add: Add, cfg: TargetSettings) -> None:
    best = it["bestSeller"]
    if best:
        add(
            "good",
            f"Best seller: {best['name']}",
            f"{inr(best['revenue'])} from {best['qty']} sold in the last 30 days "
            f"({num(best['share'])}% of item sales). Keep it front and centre on the menu board.",
        )
    popular_qty = it["mostPopular"]["qty"] if it["mostPopular"] else 0
    dead = [s for s in it["slowMovers"] if s["qty"] <= max(2, popular_qty * cfg.slow_mover_pct / 100)]
    if dead:
        names = ", ".join(f"{d['name']} ({d['qty']})" for d in dead)
        add(
            "warn",
            "Slow movers",
            f"{names} sold the least in 30 days. Consider dropping them, folding them into a combo, "
            "or renaming them.",
        )
    thin = sorted(
        (
            i
            for i in it["items"]
            if i["qty"] > 0 and i["margin"] is not None and i["margin"] < cfg.low_margin_pct
        ),
        key=lambda i: -i["qty"],
    )
    if thin:
        low = thin[0]
        add(
            "warn",
            f"Thin margin on {low['name']}",
            f"Only {num(low['margin'])}% margin on a popular item. "
            "A ₹10–20 price change or smaller topping portion would help.",  # noqa: RUF001 - en dash as in the original
        )
