"""NX-OS vendor parser.

NX-OS uses significant indentation (2-space unit) under section heads such as
``interface Ethernet1/1`` or ``vrf context FOO``. Shutdown toggling, ``default``
semantics, and ``!``/``#`` comment handling are shared with the other Cisco-style
vendors via :mod:`diffnc.vendors._cisco_like`.

Unlike IOS, saved NX-OS configurations do not typically include ``end`` / ``exit``
terminator lines, so we leave the ``terminators`` set empty here to keep the existing
behaviour where such lines would be parsed as ordinary config statements if present.

Beyond the shared Cisco order-sensitive sections (ACLs, ``policy-map`` class blocks),
NX-OS also treats ``configure maintenance profile`` blocks (GIR normal-mode /
maintenance-mode profiles) as order-sensitive: the device applies their child commands
top-to-bottom in the order written.
"""

from __future__ import annotations

from diffnc.vendors._cisco_like import CiscoLikeParser, cisco_default_order_sensitive
from diffnc.vendors.base import VendorParser


def _nxos_order_sensitive(path: tuple[str, ...]) -> bool:
    if cisco_default_order_sensitive(path):
        return True
    return bool(path) and path[-1].startswith("configure maintenance profile ")


PARSER: VendorParser = CiscoLikeParser(
    name="nxos",
    indent_unit=2,
    terminators=frozenset(),
    order_sensitive_predicate=_nxos_order_sensitive,
)
