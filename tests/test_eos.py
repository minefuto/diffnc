from __future__ import annotations

import pytest

from diffnc.errors import ParseError
from diffnc.vendors.eos import PARSER


def test_parse_top_level() -> None:
    tree = PARSER.parse("hostname leaf-a\nservice routing protocols model multi-agent\n")
    assert [c.line for c in tree.root.children] == [
        "hostname leaf-a",
        "service routing protocols model multi-agent",
    ]


def test_parse_three_space_indent_section() -> None:
    text = (
        "interface Ethernet1\n"
        "   description to-spine\n"
        "   no switchport\n"
        "   ip address 10.0.0.1/31\n"
    )
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert iface.line == "interface Ethernet1"
    assert [c.line for c in iface.children] == [
        "description to-spine",
        "no switchport",
        "ip address 10.0.0.1/31",
    ]


def test_parse_vrf_instance_block() -> None:
    text = "vrf instance MGMT\n"
    tree = PARSER.parse(text)
    assert tree.root.children[0].line == "vrf instance MGMT"


def test_parse_nested_block() -> None:
    text = "management api http-commands\n   no shutdown\n   vrf MGMT\n      no shutdown\n"
    tree = PARSER.parse(text)
    mgmt = tree.root.children[0]
    assert mgmt.line == "management api http-commands"
    assert [c.line for c in mgmt.children] == ["no shutdown", "vrf MGMT"]
    vrf = mgmt.children[1]
    assert [c.line for c in vrf.children] == ["no shutdown"]


def test_parse_skips_end_and_exit() -> None:
    tree = PARSER.parse("hostname foo\nend\nexit\n")
    assert [c.line for c in tree.root.children] == ["hostname foo"]


def test_parse_skips_bang_comments() -> None:
    tree = PARSER.parse("! banner\nhostname foo\n!\n")
    assert [c.line for c in tree.root.children] == ["hostname foo"]


def test_shutdown_toggle_collapses() -> None:
    text = "interface Ethernet1\n   shutdown\n   no shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["no shutdown"]


def test_default_removes_matching_subtree() -> None:
    text = (
        "interface Ethernet1\n"
        "   description old\n"
        "default interface Ethernet1\n"
        "interface Ethernet1\n"
        "   description new\n"
    )
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["description new"]


def test_format_round_trip_three_space_indent() -> None:
    text = "hostname leaf-a\ninterface Ethernet1\n   no shutdown\n   description x\n"
    tree = PARSER.parse(text)
    lines = PARSER.format(tree)
    assert lines == [
        "hostname leaf-a",
        "interface Ethernet1",
        "   no shutdown",
        "   description x",
    ]


def test_parse_merges_duplicate_blocks() -> None:
    text = (
        "interface Ethernet1\n   description foo\ninterface Ethernet1\n   ip address 1.1.1.1/24\n"
    )
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == [
        "description foo",
        "ip address 1.1.1.1/24",
    ]


def test_default_empty_path_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("default \n")
