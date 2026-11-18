"""Small text formatters for owner-facing messages (Indian rupee amounts, JS-style numbers)."""

from waffle_pos.services.targets import js_round


def group_indian(n: int) -> str:
    """12345678 -> '1,23,45,678' (last three digits, then pairs: lakh / crore grouping)."""
    sign = "-" if n < 0 else ""
    digits = str(abs(n))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return sign + ",".join([head, *pairs, tail])


def inr(amount: float) -> str:
    """Whole rupees with Indian grouping, like the Node ``'₹' + Math.round(n).toLocaleString('en-IN')``."""
    rounded = js_round(amount)
    return ("\u2212₹" if rounded < 0 else "₹") + group_indian(abs(rounded))


def num(x: float) -> str:
    """A number the way JavaScript prints it in a template string: 12.0 -> '12', 12.5 -> '12.5'."""
    if float(x).is_integer():
        return str(int(x))
    return repr(float(x))
