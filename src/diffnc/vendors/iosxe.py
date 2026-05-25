"""Cisco IOS-XE vendor parser.

IOS-XE shares its CLI grammar with classic IOS — 1-space indentation, ``end`` / ``exit``
terminators, ``!`` comments — but ships with a richer top-level vocabulary
(``platform ...``, ``license boot level ...``, 3-tuple interface names like
``GigabitEthernet0/0/0``). All of these structural rules are handled by the shared
:class:`~diffnc.vendors._cisco_like.CiscoLikeParser`; only the auto-detection layer
needs to know about the IOS-XE-specific markers.
"""

from __future__ import annotations

from diffnc.vendors._cisco_like import CiscoLikeParser
from diffnc.vendors.base import VendorParser

PARSER: VendorParser = CiscoLikeParser(
    name="iosxe",
    indent_unit=1,
    terminators=frozenset({"end", "exit"}),
)
