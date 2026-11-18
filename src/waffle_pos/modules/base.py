"""Feature modules.

A module is one switchable feature of the POS (GST, discounts, Google Sheet sync, WhatsApp
orders, ...). Each module declares:

* a Pydantic ``settings`` model: its fields become the form in the admin dashboard
  automatically (title, description, defaults, enums, ``format: "color"``, lists);
* whether it can be switched off (``core`` modules can't) and its default state;
* which settings are ``secret`` (never sent to the POS screens) and which are ``internal``
  (written only by server code, e.g. the PIN hash or the last sync time).

To add a feature: create ``modules/<key>.py`` with a ``MODULE = Module(...)`` and add it to
``registry.BUILTIN``. No front-end change is needed for its settings form.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict


class ModuleSettings(BaseModel):
    """Base class for a module's settings. Unknown keys are ignored so old data never breaks."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)


@dataclass(frozen=True)
class Module:
    key: str
    name: str
    description: str
    settings: type[ModuleSettings]
    core: bool = False  # core modules are always on
    default_enabled: bool = True
    secret_fields: frozenset[str] = field(default_factory=frozenset)  # never sent to the POS screens
    internal_fields: frozenset[str] = field(default_factory=frozenset)  # written only by server code
    icon: str = "🧩"
    order: int = 100
