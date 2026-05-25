"""NX-OS vendor parser.

NX-OS uses significant indentation (2-space unit) under section heads such as
``interface Ethernet1/1`` or ``vrf context FOO``. Shutdown toggling, ``default``
semantics, and ``!``/``#`` comment handling are shared with the other Cisco-style
vendors via :mod:`diffnc.vendors._cisco_like`.

Unlike IOS, saved NX-OS configurations do not typically include ``end`` / ``exit``
terminator lines, so we leave the ``terminators`` set empty here to keep the existing
behaviour where such lines would be parsed as ordinary config statements if present.
"""

from __future__ import annotations

from diffnc.vendors._cisco_like import CiscoLikeParser
from diffnc.vendors.base import VendorParser

PARSER: VendorParser = CiscoLikeParser(
    name="nxos",
    indent_unit=2,
    terminators=frozenset(),
)
