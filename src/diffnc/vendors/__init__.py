"""Vendor plugin registry.

Importing this package automatically registers the built-in vendors (Junos, Junos set,
NXOS, IOS, IOS-XE, IOS-XR, EOS). Third-party code can register additional vendors via
:func:`register`.
"""

from __future__ import annotations

from diffnc.vendors.base import VendorParser

_REGISTRY: dict[str, VendorParser] = {}


def register(parser: VendorParser) -> None:
    """Register *parser* under its :attr:`~VendorParser.name`."""

    _REGISTRY[parser.name] = parser


def get(name: str) -> VendorParser:
    """Look up the parser registered for *name*.

    Raises:
        KeyError: if no vendor with that name has been registered.
    """

    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown vendor: {name!r}") from exc


def names() -> list[str]:
    """Return all registered vendor names, sorted alphabetically."""

    return sorted(_REGISTRY)


# Register built-in vendors. Imports are placed after the registry is defined to avoid
# circular-import surprises when sub-modules call back into this package at import time.
from diffnc.vendors import eos as _eos  # noqa: E402
from diffnc.vendors import ios as _ios  # noqa: E402
from diffnc.vendors import iosxe as _iosxe  # noqa: E402
from diffnc.vendors import iosxr as _iosxr  # noqa: E402
from diffnc.vendors import junos as _junos  # noqa: E402
from diffnc.vendors import junos_set as _junos_set  # noqa: E402
from diffnc.vendors import nxos as _nxos  # noqa: E402

register(_junos.PARSER)
register(_junos_set.PARSER)
register(_nxos.PARSER)
register(_ios.PARSER)
register(_iosxe.PARSER)
register(_iosxr.PARSER)
register(_eos.PARSER)

__all__ = ["VendorParser", "get", "names", "register"]
