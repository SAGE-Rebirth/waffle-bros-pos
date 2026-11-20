"""The modules that ship with the POS."""

from __future__ import annotations

import re
from typing import Annotated, Literal, get_args

from pydantic import Field, field_validator

from waffle_pos.modules.base import Module, ModuleSettings
from waffle_pos.schemas import MAX_MONEY, _image

# The only address the Google Sheet sync will post to (integrations/sheets.py checks it again).
WEB_APP_URL_RE = re.compile(r"^https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec$")

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$", json_schema_extra={"format": "color"})]
PaymentMethod = Literal["upi", "cash", "card"]
OrderType = Literal["dine-in", "takeaway", "delivery"]


# ---------- core ----------
class ShopSettings(ModuleSettings):
    shop_name: str = Field("Waffle Bros", title="Shop name", max_length=60)
    shop_address: str = Field("Bhopal", title="Address (printed on bills)", max_length=200)
    shop_phone: str = Field("", title="Phone (printed on bills)", max_length=20)
    receipt_footer: str = Field(
        "Thank you! Come back for more waffles", title="Bill footer message", max_length=120
    )
    logo: str | None = Field(
        None,
        title="Logo",
        description="Square image; shown in the top bar.",
        max_length=200_000,
        json_schema_extra={"format": "image"},
    )
    open_hour: int = Field(10, ge=0, le=23, title="Opens at (hour, 0-23)")
    close_hour: int = Field(23, ge=0, le=23, title="Closes at (hour, 0-23)")

    @field_validator("logo")
    @classmethod
    def _logo(cls, v: str | None) -> str | None:
        return _image(v)


class ThemeSettings(ModuleSettings):
    primary: Color = Field("#F6B92B", title="Primary (buttons, highlights)")
    dark: Color = Field("#4A2C1A", title="Dark (top bar, text accents)")
    accent: Color = Field("#B97A10", title="Accent (prices, charts)")
    background: Color = Field("#FFFDF6", title="Page background")


class BillingSettings(ModuleSettings):
    payment_methods: list[PaymentMethod] = Field(
        default_factory=lambda: list(get_args(PaymentMethod)), title="Payment methods", min_length=1
    )
    default_payment: PaymentMethod = Field("upi", title="Selected by default")
    order_types: list[OrderType] = Field(
        default_factory=lambda: list(get_args(OrderType)), title="Order types", min_length=1
    )
    customer_capture: bool = Field(True, title="Show '+ Customer' (name and phone) on bills")
    print_on_save: bool = Field(False, title="Always print the bill when saving")

    @field_validator("payment_methods", "order_types")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class TargetSettings(ModuleSettings):
    default_target: float = Field(100000, gt=0, le=MAX_MONEY * 10, title="Default monthly target (₹)")
    slow_mover_pct: float = Field(
        5,
        ge=0,
        le=100,
        title="Slow mover threshold (%)",
        description="An item is a slow mover if it sold less than this % of the best item's units (30 days).",
    )
    low_margin_pct: float = Field(55, ge=0, le=100, title="Warn when a popular item's margin is below (%)")
    expense_categories: list[Annotated[str, Field(max_length=30)]] = Field(
        default_factory=lambda: [
            "rent",
            "salary",
            "ingredients",
            "electricity",
            "packaging",
            "marketing",
            "maintenance",
            "other",
        ],
        title="Expense categories",
        min_length=1,
        max_length=30,
    )

    @field_validator("expense_categories")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(x.strip().lower() for x in v if x.strip()))


class AdminSettings(ModuleSettings):
    pin_hash: str = Field("", title="PIN hash", json_schema_extra={"hidden": True})
    pin_salt: str = Field("", title="PIN salt", json_schema_extra={"hidden": True})
    token_secret: str = Field("", title="Session secret", json_schema_extra={"hidden": True})
    session_hours: int = Field(12, ge=1, le=168, title="Stay signed in for (hours)")


# ---------- optional ----------
class GstSettings(ModuleSettings):
    rate: float = Field(5, ge=0, le=28, title="GST rate (%)")
    gstin: str = Field("", title="GSTIN (printed on bills)", max_length=15)


class DiscountSettings(ModuleSettings):
    max_discount_pct: float = Field(20, ge=0, le=100, title="Largest discount allowed (% of the bill)")


class GoogleSheetsSettings(ModuleSettings):
    web_app_url: str = Field(
        "",
        title="Web app URL",
        description="From the sheet's Apps Script: Deploy -> Web app. Looks like "
        "https://script.google.com/macros/s/.../exec",
        max_length=300,
    )
    secret: str = Field(
        "",
        title="Secret",
        description="Any long random text (16+ characters). Paste the same text into SECRET in the script.",
        max_length=200,
    )
    interval_minutes: int = Field(5, ge=1, le=1440, title="Sync every (minutes)")
    last_sync: str = Field("", title="Last synced", json_schema_extra={"readOnly": True})

    @field_validator("web_app_url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip()
        if v and not WEB_APP_URL_RE.match(v):
            raise ValueError(
                "must be the Apps Script web app URL, https://script.google.com/macros/s/.../exec"
            )
        return v

    @field_validator("secret")
    @classmethod
    def _check_secret(cls, v: str) -> str:
        v = v.strip()
        if v and len(v) < 16:
            raise ValueError("use at least 16 characters")
        return v


class WhatsAppSettings(ModuleSettings):
    business_number: str = Field("", title="WhatsApp Business number", max_length=20)
    delivery_buildings: list[Annotated[str, Field(max_length=60)]] = Field(
        default_factory=list,
        max_length=50,
        title="Buildings we deliver to",
        description="Tower / building names in the apartment complex.",
    )
    min_order: float = Field(0, ge=0, le=MAX_MONEY, title="Minimum order for delivery (₹)")


SHOP = Module(
    "shop", "Shop details", "Name, address and bill text.", ShopSettings, core=True, icon="🏪", order=1
)
THEME = Module("theme", "Look", "Colours used across the POS.", ThemeSettings, core=True, icon="🎨", order=2)
BILLING = Module(
    "billing",
    "Billing",
    "Payment methods, order types and bill options.",
    BillingSettings,
    core=True,
    icon="🧾",
    order=3,
)
TARGETS = Module(
    "targets",
    "Targets & insights",
    "Monthly target, insight thresholds, expense categories.",
    TargetSettings,
    core=True,
    icon="🎯",
    order=4,
)
ADMIN = Module(
    "admin",
    "Admin access",
    "PIN for the admin dashboard.",
    AdminSettings,
    core=True,
    icon="🔐",
    order=99,
    secret_fields=frozenset({"pin_hash", "pin_salt", "token_secret"}),
    internal_fields=frozenset({"pin_hash", "pin_salt", "token_secret"}),
)
GST = Module(
    "gst",
    "GST",
    "Add GST to bills and print the GSTIN.",
    GstSettings,
    default_enabled=False,
    icon="🧮",
    order=10,
)
DISCOUNTS = Module(
    "discounts", "Discounts", "Allow a rupee discount on bills.", DiscountSettings, icon="🏷️", order=11
)
GOOGLE_SHEETS = Module(
    "google_sheets",
    "Google Sheet sync",
    "Copy bills, items and expenses to a Google Sheet.",
    GoogleSheetsSettings,
    default_enabled=False,
    icon="📊",
    order=20,
    secret_fields=frozenset({"secret"}),
    internal_fields=frozenset({"last_sync"}),
)
WHATSAPP = Module(
    "whatsapp",
    "WhatsApp orders (phase 2)",
    "Home delivery orders from the apartment residents over WhatsApp.",
    WhatsAppSettings,
    default_enabled=False,
    icon="💬",
    order=30,
)
