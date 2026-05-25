"""Arista EOS vendor parser.

EOS configurations look very Cisco-ish — significant indentation, ``!`` comments,
``end`` / ``exit`` terminators — but use a 3-space indent unit and a distinct top-level
vocabulary (``vrf instance MGMT`` rather than NX-OS's ``vrf context``, ``daemon
TerminAttr``, ``management api http-commands``, ...). The grammar itself is shared with
the other Cisco-style vendors via :mod:`diffnc.vendors._cisco_like`.
"""

from __future__ import annotations

from diffnc.vendors._cisco_like import CiscoLikeParser
from diffnc.vendors.base import VendorParser

PARSER: VendorParser = CiscoLikeParser(
    name="eos",
    indent_unit=3,
    terminators=frozenset({"end", "exit"}),
)
