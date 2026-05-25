"""Cisco IOS vendor parser.

IOS configurations use significant indentation under section heads such as
``interface GigabitEthernet0/0`` or ``router ospf 1`` with a 1-space indent unit, and
end with ``end`` / ``exit`` terminator lines that we drop. Everything else (shutdown
toggling, ``default`` semantics, ``!``/``#`` comment handling) is shared with the other
Cisco-style vendors and lives in :mod:`diffnc.vendors._cisco_like`.
"""

from __future__ import annotations

from diffnc.vendors._cisco_like import CiscoLikeParser
from diffnc.vendors.base import VendorParser

PARSER: VendorParser = CiscoLikeParser(
    name="ios",
    indent_unit=1,
    terminators=frozenset({"end", "exit"}),
)
