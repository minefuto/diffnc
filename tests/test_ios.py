from __future__ import annotations

import pytest

from diffnc.errors import ParseError
from diffnc.vendors.ios import PARSER


def test_parse_top_level() -> None:
    tree = PARSER.parse("hostname Router1\nip cef\n")
    assert [c.line for c in tree.root.children] == ["hostname Router1", "ip cef"]
    assert all(c.is_leaf for c in tree.root.children)


def test_parse_indented_section() -> None:
    text = (
        "interface GigabitEthernet0/0\n"
        " description uplink\n"
        " ip address 192.168.1.1 255.255.255.0\n"
        " no shutdown\n"
    )
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert iface.line == "interface GigabitEthernet0/0"
    assert [c.line for c in iface.children] == [
        "description uplink",
        "ip address 192.168.1.1 255.255.255.0",
        "no shutdown",
    ]


def test_parse_skips_end_and_exit() -> None:
    tree = PARSER.parse("hostname foo\nend\nexit\n")
    assert [c.line for c in tree.root.children] == ["hostname foo"]


def test_parse_skips_bang_comments() -> None:
    tree = PARSER.parse("! banner line\nhostname foo\n!\n")
    assert [c.line for c in tree.root.children] == ["hostname foo"]


def test_shutdown_toggle_collapses() -> None:
    text = "interface GigabitEthernet0/0\n shutdown\n no shutdown\n"
    tree = PARSER.parse(text)
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == ["no shutdown"]


def test_default_removes_matching_subtree() -> None:
    text = (
        "interface GigabitEthernet0/0\n"
        " description old\n"
        " no shutdown\n"
        "default interface GigabitEthernet0/0\n"
        "interface GigabitEthernet0/0\n"
        " description new\n"
    )
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert iface.line == "interface GigabitEthernet0/0"
    assert [c.line for c in iface.children] == ["description new"]


def test_format_round_trip_one_space_indent() -> None:
    text = "hostname Router1\ninterface GigabitEthernet0/0\n no shutdown\n description x\n"
    tree = PARSER.parse(text)
    lines = PARSER.format(tree)
    assert lines == [
        "hostname Router1",
        "interface GigabitEthernet0/0",
        " no shutdown",
        " description x",
    ]


def test_default_empty_path_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("default \n")


def test_parse_merges_duplicate_blocks() -> None:
    text = (
        "interface GigabitEthernet0/0\n"
        " description foo\n"
        "interface GigabitEthernet0/0\n"
        " ip address 1.1.1.1 255.255.255.0\n"
    )
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    iface = tree.root.children[0]
    assert [c.line for c in iface.children] == [
        "description foo",
        "ip address 1.1.1.1 255.255.255.0",
    ]
