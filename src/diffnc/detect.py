"""Vendor auto-detection.

The detector inspects a configuration's signal-bearing lines and returns the vendor name.
Heuristics are intentionally conservative: when in doubt, raise :class:`ParseError` so the
caller can ask the user to disambiguate via ``--vendor``.
"""

from __future__ import annotations

import re

from diffnc.errors import ParseError

_JUNOS_TOP_KEYWORDS = (
    "interfaces",
    "system",
    "routing-options",
    "routing-instances",
    "protocols",
    "policy-options",
    "firewall",
    "security",
    "groups",
    "chassis",
    "snmp",
    "services",
    "applications",
    "forwarding-options",
)

_NXOS_INTERFACE_RE = re.compile(r"^interface Ethernet\d+/\d+")

_IOS_INTERFACE_PREFIXES = (
    "interface FastEthernet",
    "interface GigabitEthernet",
    "interface TenGigabitEthernet",
    "interface Serial",
)

# Cisco "speed-named" interface prefixes shared by IOS / IOS-XE / IOS-XR. The classic
# bare ``Ethernet`` prefix is excluded because it belongs to NX-OS and Arista EOS.
_CISCO_NAMED_IFACES = (
    "FastEthernet",
    "GigabitEthernet",
    "TenGigabitEthernet",
    "TenGigE",
    "TwentyFiveGigE",
    "FortyGigE",
    "HundredGigE",
)
_CISCO_NAMED_GROUP = "|".join(_CISCO_NAMED_IFACES)

# IOS-XE distinguishes itself with a 3-tuple slot/subslot/port (e.g.
# ``GigabitEthernet0/0/0``) — distinct from classic IOS's 2-tuple form.
_IOSXE_INTERFACE_RE = re.compile(rf"^interface (?:{_CISCO_NAMED_GROUP})\d+/\d+/\d+(?:\.\d+)?$")

# IOS-XR uses a 4-tuple slot/subslot/instance/port for physical interfaces.
_IOSXR_INTERFACE_RE = re.compile(rf"^interface (?:{_CISCO_NAMED_GROUP})\d+/\d+/\d+/\d+")


def _has_nxos_marker(lines: list[str]) -> bool:
    for s in lines:
        if s.startswith(("feature ", "vrf context ", "vdc ")):
            return True
        if _NXOS_INTERFACE_RE.match(s):
            return True
    return False


def _has_ios_marker(lines: list[str]) -> bool:
    for s in lines:
        if s.startswith(("service password-encryption", "service timestamps")):
            return True
        if s in ("boot-start-marker", "boot-end-marker"):
            return True
        if s.startswith(_IOS_INTERFACE_PREFIXES):
            return True
        if s.startswith(("line con ", "line vty ")):
            return True
    return False


def _has_iosxe_marker(lines: list[str]) -> bool:
    for s in lines:
        if s.startswith(("platform ", "license boot level")):
            return True
        if s.startswith(("boot system bootflash:", "boot system flash")):
            return True
        if _IOSXE_INTERFACE_RE.match(s):
            return True
    return False


def _has_iosxr_marker(lines: list[str]) -> bool:
    for s in lines:
        if s.startswith(("interface Bundle-Ether", "interface MgmtEth")):
            return True
        if s.startswith("RP/0/"):
            return True
        if _IOSXR_INTERFACE_RE.match(s):
            return True
    return False


def _has_eos_marker(lines: list[str]) -> bool:
    for s in lines:
        if s.startswith(
            (
                "vrf instance ",
                "daemon TerminAttr",
                "management api http-commands",
                "service routing protocols model",
                "transceiver qsfp default-mode",
            )
        ):
            return True
    return False


def _significant_lines(text: str) -> list[str]:
    significant: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("!") or s.startswith("#") or s.startswith("/*"):
            continue
        significant.append(s)
    return significant


def is_empty_config(text: str) -> bool:
    """True if *text* has no significant (non-comment) lines."""

    return not _significant_lines(text)


def detect_vendor(text: str) -> str:
    """Return the vendor name for *text*.

    Raises:
        ParseError: if no supported vendor can be confidently identified.
    """

    significant = _significant_lines(text)
    if not significant:
        raise ParseError("configuration is empty or comment-only")

    # Junos set form: most lines start with `set ` (or `deactivate `/`activate `/`delete `).
    set_like = sum(
        1 for s in significant if s.startswith(("set ", "deactivate ", "activate ", "delete "))
    )
    if set_like / len(significant) >= 0.8:
        return "junos_set"

    # Junos hierarchical: presence of braces and at least one Junos top-level keyword.
    has_brace = any(s.endswith("{") or s == "}" for s in significant)
    has_junos_kw = any(
        s.split(" ", 1)[0] in _JUNOS_TOP_KEYWORDS or s.startswith(kw + " {")
        for s in significant
        for kw in _JUNOS_TOP_KEYWORDS
    )
    if has_brace and has_junos_kw:
        return "junos"

    # Brace-less indent-based vendors: NX-OS, IOS, IOS-XE, IOS-XR, EOS. Checks are
    # ordered by marker specificity so a mixed config (e.g. EOS with copied IOS-style
    # lines) stays on the more specific vendor.
    if not has_brace:
        if _has_eos_marker(significant):
            return "eos"
        if _has_iosxr_marker(significant):
            return "iosxr"
        if _has_nxos_marker(significant):
            return "nxos"
        if _has_iosxe_marker(significant):
            return "iosxe"
        if _has_ios_marker(significant):
            return "ios"
        return "nxos"

    raise ParseError("could not detect vendor from configuration text")
