from __future__ import annotations

import pytest

from diffnc.errors import ParseError
from diffnc.vendors.nxos import PARSER


def test_parse_top_level() -> None:
    tree = PARSER.parse("hostname foo\nfeature lldp\n")
    assert [c.line for c in tree.root.children] == ["hostname foo", "feature lldp"]
    assert all(c.is_leaf for c in tree.root.children)


def test_parse_indented_section() -> None:
    text = "interface Ethernet1/1\n  description uplink\n  no shutdown\n"
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert iface.line == "interface Ethernet1/1"
    assert [c.line for c in iface.children] == ["description uplink", "no shutdown"]


def test_parse_merges_duplicate_blocks() -> None:
    text = "interface eth1\n  shutdown\n\ninterface eth1\n  description x\n"
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["shutdown", "description x"]


def test_parse_merges_repeated_empty_section() -> None:
    # First occurrence is an empty section (a leaf at parse time); the second re-declares
    # it with children. The empty header must not be mistaken for a toggle and dropped.
    text = "interface Ethernet1/1\n\ninterface Ethernet1/1\n  no shutdown\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["interface Ethernet1/1"]
    iface = tree.root.children[0]
    assert not iface.is_leaf
    assert [c.line for c in iface.children] == ["no shutdown"]


def test_parse_deduplicates_repeated_leaf() -> None:
    text = "interface eth1\n  shutdown\n  shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["shutdown"]


def test_parse_ignores_comments_and_blank_lines() -> None:
    text = "! banner\n\nhostname foo\n# another comment\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["hostname foo"]


def test_format_round_trip() -> None:
    text = "hostname foo\ninterface eth1\n  no shutdown\n  description x\n"
    tree = PARSER.parse(text)
    lines = PARSER.format(tree)
    assert lines == [
        "hostname foo",
        "interface eth1",
        "  no shutdown",
        "  description x",
    ]


def test_default_removes_matching_subtree_at_top_level() -> None:
    text = (
        "interface Ethernet1/1\n"
        "  description uplink\n"
        "  no shutdown\n"
        "default interface Ethernet1/1\n"
        "interface Ethernet1/1\n"
        "  description new-uplink\n"
    )
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert iface.line == "interface Ethernet1/1"
    assert [c.line for c in iface.children] == ["description new-uplink"]


def test_default_inside_section_removes_sibling() -> None:
    text = "interface eth1\n  description foo\n  shutdown\n  default shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["description foo"]


def test_default_does_not_match_partial_token() -> None:
    text = (
        "ip route 10.0.0.0/8 192.168.1.1\n"
        "ip route 10.0.0.0/24 192.168.1.1\n"
        "default ip route 10.0.0.0/8\n"
    )
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        "ip route 10.0.0.0/24 192.168.1.1",
    ]


def test_default_information_originate_is_not_default_keyword() -> None:
    text = "router ospf 1\n  default-information originate\n"
    tree = PARSER.parse(text)
    router = tree.root.children[0]
    assert [c.line for c in router.children] == ["default-information originate"]


def test_default_unmatched_is_noop() -> None:
    text = "hostname foo\ndefault interface Ethernet1/1\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["hostname foo"]


def test_default_empty_path_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("default \n")


def test_shutdown_toggle_collapses() -> None:
    text = "interface eth1\n  shutdown\n  no shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["no shutdown"]


def test_shutdown_toggle_back_and_forth() -> None:
    text = "interface eth1\n  shutdown\n  no shutdown\n  shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["shutdown"]


def test_shutdown_state_is_per_parent() -> None:
    text = "interface eth1\n  shutdown\ninterface eth2\n  no shutdown\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["interface eth1", "interface eth2"]
    assert [c.line for c in tree.root.children[0].children] == ["shutdown"]
    assert [c.line for c in tree.root.children[1].children] == ["no shutdown"]


def test_shutdown_position_at_first_occurrence() -> None:
    text = "interface eth1\n  description foo\n  shutdown\n  ip address 1.1.1.1/24\n  no shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    # `shutdown` was the first occurrence at position 1; after toggle to `no shutdown`,
    # the state node stays at position 1.
    assert [c.line for c in iface.children] == [
        "description foo",
        "no shutdown",
        "ip address 1.1.1.1/24",
    ]


def test_generic_no_toggle_collapses_to_last_state() -> None:
    text = "interface eth1\n  ip redirects\n  no ip redirects\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["no ip redirects"]


def test_no_toggle_not_collapsed_in_order_sensitive_section() -> None:
    # ACL entries are positional; a `no` line is a literal entry, not a toggle to fold.
    text = "ip access-list extended FOO\n  10 permit ip any any\n  no 10 permit ip any any\n"
    tree = PARSER.parse(text)
    acl = tree.root.children[0]
    assert [c.line for c in acl.children] == [
        "10 permit ip any any",
        "no 10 permit ip any any",
    ]


def test_default_resets_both_toggle_faces() -> None:
    text = "interface eth1\n  no shutdown\n  default shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == []
