"""Cisco IOS-XR vendor parser.

IOS-XR uses the same indent-based section grammar as IOS (1-space unit) but has its own
configuration session terminators — ``commit`` (and the less common ``root`` /
``abort``) — that we treat the same way IOS treats ``end`` / ``exit``: drop them on
parse. Interface naming conventions (``Bundle-Ether1``, 4-tuple ``GigabitEthernet0/0/0/0``)
matter only for auto-detection and are handled in :mod:`diffnc.detect`.
"""

from __future__ import annotations

from diffnc.vendors._cisco_like import CiscoLikeParser
from diffnc.vendors.base import VendorParser

PARSER: VendorParser = CiscoLikeParser(
    name="iosxr",
    indent_unit=1,
    terminators=frozenset({"end", "exit", "commit", "root"}),
    # IOS-XR has no `default <cmd>`; removed toggles reset by inverting the `no`.
    supports_default=False,
)
