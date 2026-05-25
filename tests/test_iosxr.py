from __future__ import annotations

import pytest

from diffnc.errors import ParseError
from diffnc.vendors.iosxr import PARSER


def test_parse_top_level() -> None:
    tree = PARSER.parse("hostname ASR9K\n")
    assert [c.line for c in tree.root.children] == ["hostname ASR9K"]


def test_parse_four_tuple_interface() -> None:
    text = (
        "interface GigabitEthernet0/0/0/0\n"
        " description to-spine\n"
        " ipv4 address 10.0.0.1 255.255.255.252\n"
        " no shutdown\n"
    )
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert iface.line == "interface GigabitEthernet0/0/0/0"
    assert [c.line for c in iface.children] == [
        "description to-spine",
        "ipv4 address 10.0.0.1 255.255.255.252",
        "no shutdown",
    ]


def test_parse_bundle_ether() -> None:
    text = "interface Bundle-Ether1\n ipv4 address 10.0.0.1/30\n no shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert iface.line == "interface Bundle-Ether1"


def test_parse_skips_commit_and_root_terminators() -> None:
    # IOS-XR's session terminators should be silently dropped on parse.
    tree = PARSER.parse("hostname foo\ncommit\nroot\nend\nexit\n")
    assert [c.line for c in tree.root.children] == ["hostname foo"]


def test_parse_nested_address_family() -> None:
    text = "router static\n address-family ipv4 unicast\n  0.0.0.0/0 192.168.1.254\n"
    tree = PARSER.parse(text)
    rs = tree.root.children[0]
    assert rs.line == "router static"
    af = rs.children[0]
    assert af.line == "address-family ipv4 unicast"
    assert [c.line for c in af.children] == ["0.0.0.0/0 192.168.1.254"]


def test_parse_skips_bang_comments() -> None:
    tree = PARSER.parse("! banner\nhostname foo\n!\n")
    assert [c.line for c in tree.root.children] == ["hostname foo"]


def test_shutdown_toggle_collapses() -> None:
    text = "interface GigabitEthernet0/0/0/0\n shutdown\n no shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["no shutdown"]


def test_default_removes_matching_subtree() -> None:
    text = (
        "interface GigabitEthernet0/0/0/0\n"
        " description old\n"
        "default interface GigabitEthernet0/0/0/0\n"
        "interface GigabitEthernet0/0/0/0\n"
        " description new\n"
    )
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["description new"]


def test_format_round_trip_one_space_indent() -> None:
    text = "hostname ASR9K\ninterface Bundle-Ether1\n no shutdown\n description x\n"
    tree = PARSER.parse(text)
    lines = PARSER.format(tree)
    assert lines == [
        "hostname ASR9K",
        "interface Bundle-Ether1",
        " no shutdown",
        " description x",
    ]


def test_parse_merges_duplicate_blocks() -> None:
    text = (
        "interface Bundle-Ether1\n"
        " description foo\n"
        "interface Bundle-Ether1\n"
        " ipv4 address 1.1.1.1 255.255.255.0\n"
    )
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == [
        "description foo",
        "ipv4 address 1.1.1.1 255.255.255.0",
    ]


def test_default_empty_path_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("default \n")
