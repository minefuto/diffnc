"""Order-sensitive vs order-insensitive diff behaviour.

Most configuration containers (Junos ``system``, NX-OS top-level, …) are evaluated as a
set: rearranging children does not change device behaviour, so a pure reorder must not
produce a diff. A small whitelist of paths *is* order-sensitive (Junos firewall filter
terms / policy-statement terms, Cisco ACL ACEs, Cisco ``policy-map`` class blocks); for
those, a pure reorder surfaces with the ``!`` marker; genuine content changes still
show as ``-``/``+`` pairs.
"""

from __future__ import annotations

from diffnc import unified_diff


def _has_minus_line(out: str) -> bool:
    return any(line.startswith("-") and not line.startswith("---") for line in out.splitlines())


def _has_plus_line(out: str) -> bool:
    return any(line.startswith("+") and not line.startswith("+++") for line in out.splitlines())


def _has_reorder_line(out: str) -> bool:
    return any(line.startswith("!") for line in out.splitlines())


# ---------------------------------------------------------------------------
# Junos hierarchical — order-insensitive containers
# ---------------------------------------------------------------------------


def test_junos_system_reorder_produces_no_diff() -> None:
    a = "system {\n    host-name foo;\n    domain-name example.com;\n}\n"
    b = "system {\n    domain-name example.com;\n    host-name foo;\n}\n"
    assert list(unified_diff(a, b)) == []


def test_junos_interfaces_reorder_produces_no_diff() -> None:
    a = (
        "interfaces {\n"
        "    ge-0/0/0 {\n        unit 0;\n    }\n"
        "    ge-0/0/1 {\n        unit 0;\n    }\n"
        "}\n"
    )
    b = (
        "interfaces {\n"
        "    ge-0/0/1 {\n        unit 0;\n    }\n"
        "    ge-0/0/0 {\n        unit 0;\n    }\n"
        "}\n"
    )
    assert list(unified_diff(a, b)) == []


# ---------------------------------------------------------------------------
# Junos hierarchical — order-sensitive: firewall filter terms
# ---------------------------------------------------------------------------


def test_junos_firewall_filter_term_reorder_is_a_diff() -> None:
    a = (
        "firewall {\n"
        "    filter F {\n"
        "        term A {\n            then accept;\n        }\n"
        "        term B {\n            then discard;\n        }\n"
        "    }\n"
        "}\n"
    )
    b = (
        "firewall {\n"
        "    filter F {\n"
        "        term B {\n            then discard;\n        }\n"
        "        term A {\n            then accept;\n        }\n"
        "    }\n"
        "}\n"
    )
    out = "".join(unified_diff(a, b, lineterm="\n"))
    # Pure swap: both terms render identically on both sides — surface as `!` only.
    assert _has_reorder_line(out)
    assert not _has_minus_line(out)
    assert not _has_plus_line(out)
    assert "term " in out


def test_junos_family_filter_term_reorder_is_a_diff() -> None:
    a = (
        "firewall {\n"
        "    family inet {\n"
        "        filter F {\n"
        "            term A {\n                then accept;\n            }\n"
        "            term B {\n                then discard;\n            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    b = (
        "firewall {\n"
        "    family inet {\n"
        "        filter F {\n"
        "            term B {\n                then discard;\n            }\n"
        "            term A {\n                then accept;\n            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert _has_reorder_line(out)
    assert not _has_minus_line(out)
    assert not _has_plus_line(out)


def test_junos_term_internal_reorder_is_not_a_diff() -> None:
    """Inside a single term, ``from`` / ``then`` ordering is cosmetic."""

    a = (
        "firewall {\n"
        "    filter F {\n"
        "        term T {\n"
        "            from {\n                protocol tcp;\n            }\n"
        "            then {\n                accept;\n            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    b = (
        "firewall {\n"
        "    filter F {\n"
        "        term T {\n"
        "            then {\n                accept;\n            }\n"
        "            from {\n                protocol tcp;\n            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert list(unified_diff(a, b)) == []


def test_junos_policy_statement_term_reorder_is_a_diff() -> None:
    a = (
        "policy-options {\n"
        "    policy-statement P {\n"
        "        term T1 {\n            then accept;\n        }\n"
        "        term T2 {\n            then reject;\n        }\n"
        "    }\n"
        "}\n"
    )
    b = (
        "policy-options {\n"
        "    policy-statement P {\n"
        "        term T2 {\n            then reject;\n        }\n"
        "        term T1 {\n            then accept;\n        }\n"
        "    }\n"
        "}\n"
    )
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert _has_reorder_line(out)
    assert not _has_minus_line(out)
    assert not _has_plus_line(out)


# ---------------------------------------------------------------------------
# Junos set form
# ---------------------------------------------------------------------------


def test_junos_set_reorder_produces_no_diff() -> None:
    a = (
        "set system host-name foo\n"
        "set system domain-name example.com\n"
        "set interfaces ge-0/0/0 unit 0\n"
    )
    b = (
        "set interfaces ge-0/0/0 unit 0\n"
        "set system domain-name example.com\n"
        "set system host-name foo\n"
    )
    assert list(unified_diff(a, b)) == []


# ---------------------------------------------------------------------------
# Cisco-style indent-based vendors — order-insensitive top level
# ---------------------------------------------------------------------------


def test_nxos_interface_reorder_produces_no_diff() -> None:
    a = "interface Ethernet1/1\n  description first\ninterface Ethernet1/2\n  description second\n"
    b = "interface Ethernet1/2\n  description second\ninterface Ethernet1/1\n  description first\n"
    assert list(unified_diff(a, b)) == []


def test_nxos_route_map_top_level_reorder_produces_no_diff() -> None:
    """Each ``route-map FOO permit <seq>`` is its own top-level section; the seq number
    is part of the line, so order across them is purely cosmetic."""

    a = (
        "route-map FOO permit 10\n"
        "  match ip address prefix-list P1\n"
        "route-map FOO permit 20\n"
        "  match ip address prefix-list P2\n"
    )
    b = (
        "route-map FOO permit 20\n"
        "  match ip address prefix-list P2\n"
        "route-map FOO permit 10\n"
        "  match ip address prefix-list P1\n"
    )
    assert list(unified_diff(a, b)) == []


# ---------------------------------------------------------------------------
# Cisco-style — order-sensitive: ACL ACEs, policy-map class blocks
# ---------------------------------------------------------------------------


def test_nxos_ip_access_list_ace_reorder_is_a_diff() -> None:
    a = "ip access-list FOO\n  10 permit ip any any\n  20 deny ip any any\n"
    b = "ip access-list FOO\n  20 deny ip any any\n  10 permit ip any any\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert _has_reorder_line(out)
    assert not _has_minus_line(out)
    assert not _has_plus_line(out)
    assert "ip access-list FOO" in out


def test_ios_policy_map_class_reorder_is_a_diff() -> None:
    a = (
        "policy-map QOS\n"
        " class VOICE\n"
        "  priority 100\n"
        " class DATA\n"
        "  bandwidth 200\n"
        "interface GigabitEthernet0/0\n"
    )
    b = (
        "policy-map QOS\n"
        " class DATA\n"
        "  bandwidth 200\n"
        " class VOICE\n"
        "  priority 100\n"
        "interface GigabitEthernet0/0\n"
    )
    out = "".join(unified_diff(a, b, lineterm="\n", vendor="ios"))
    assert _has_reorder_line(out)
    assert not _has_minus_line(out)
    assert not _has_plus_line(out)
    assert "policy-map QOS" in out


def test_nxos_acl_ace_value_change_still_diffs() -> None:
    """Order-sensitive parents still show real content changes."""

    a = "ip access-list FOO\n  10 permit ip 10.0.0.0/24 any\n"
    b = "ip access-list FOO\n  10 permit ip 10.0.1.0/24 any\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "-  10 permit ip 10.0.0.0/24 any\n" in out
    assert "+  10 permit ip 10.0.1.0/24 any\n" in out
    assert not _has_reorder_line(out)


def test_junos_firewall_filter_reorder_plus_removal_mixes_markers() -> None:
    """A reordered, byte-identical term shows as ``!`` alongside an unrelated
    removal that surfaces as ``-``."""

    a = (
        "firewall {\n"
        "    filter F {\n"
        "        term A {\n            then accept;\n        }\n"
        "        term B {\n            then discard;\n        }\n"
        "        term C {\n            then count;\n        }\n"
        "    }\n"
        "}\n"
    )
    b = (
        "firewall {\n"
        "    filter F {\n"
        "        term C {\n            then count;\n        }\n"
        "        term A {\n            then accept;\n        }\n"
        "    }\n"
        "}\n"
    )
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert _has_reorder_line(out)
    assert _has_minus_line(out)
    assert not _has_plus_line(out)
