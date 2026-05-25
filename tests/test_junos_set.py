from __future__ import annotations

import pytest

from diffnc.errors import ParseError
from diffnc.vendors.junos_set import PARSER


def test_set_parse_basic() -> None:
    text = (
        "set system host-name foo\nset interfaces ge-0/0/0 unit 0 family inet address 1.1.1.1/24\n"
    )
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        "set system host-name foo",
        "set interfaces ge-0/0/0 unit 0 family inet address 1.1.1.1/24",
    ]


def test_set_dedup_identical_lines() -> None:
    text = "set system host-name foo\nset system host-name foo\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["set system host-name foo"]


def test_set_rejects_non_set_line() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("set system host-name foo\nthis is not a set line\n")


def test_set_accepts_activate_deactivate() -> None:
    text = "set system host-name foo\ndeactivate interfaces ge-0/0/0\n"
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 2


def test_set_format_round_trip() -> None:
    text = "set system host-name foo\nset interfaces ge-0/0/0 unit 0\n"
    tree = PARSER.parse(text)
    assert PARSER.format(tree) == [
        "set system host-name foo",
        "set interfaces ge-0/0/0 unit 0",
    ]


def test_set_delete_removes_matching_prefix() -> None:
    text = (
        "set interfaces ge-0/0/0 unit 0 family inet address 192.168.1.1/24\n"
        "delete interfaces ge-0/0/0\n"
        "set interfaces ge-0/0/0 unit 0 family mpls\n"
    )
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        "set interfaces ge-0/0/0 unit 0 family mpls",
    ]


def test_set_delete_does_not_match_partial_token() -> None:
    text = (
        "set interfaces ge-0/0/0 unit 0\n"
        "set interfaces ge-0/0/01 unit 0\n"
        "delete interfaces ge-0/0/0\n"
    )
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        "set interfaces ge-0/0/01 unit 0",
    ]


def test_set_delete_also_removes_deactivate_activate() -> None:
    text = (
        "set interfaces ge-0/0/0 unit 0\n"
        "deactivate interfaces ge-0/0/0\n"
        "activate interfaces ge-0/0/0 unit 0\n"
        "delete interfaces ge-0/0/0\n"
    )
    tree = PARSER.parse(text)
    assert tree.root.children == []


def test_set_delete_then_re_add_keeps_re_added() -> None:
    text = "set system host-name foo\ndelete system\nset system host-name bar\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["set system host-name bar"]


def test_set_delete_empty_path_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("delete \n")


def test_set_delete_unmatched_is_noop() -> None:
    text = "set system host-name foo\ndelete interfaces ge-0/0/0\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["set system host-name foo"]


def test_set_activate_deactivate_toggle_collapses() -> None:
    text = (
        "set interfaces ge-0/0/0 unit 0\n"
        "deactivate interfaces ge-0/0/0\n"
        "activate interfaces ge-0/0/0\n"
    )
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        "set interfaces ge-0/0/0 unit 0",
        "activate interfaces ge-0/0/0",
    ]


def test_set_activate_state_is_per_path() -> None:
    text = (
        "deactivate interfaces ge-0/0/0\n"
        "deactivate interfaces ge-0/0/1\n"
        "activate interfaces ge-0/0/0\n"
    )
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        "activate interfaces ge-0/0/0",
        "deactivate interfaces ge-0/0/1",
    ]


def test_set_activate_position_at_first_occurrence() -> None:
    text = (
        "set system host-name foo\n"
        "deactivate interfaces ge-0/0/0\n"
        "set interfaces ge-0/0/1 unit 0\n"
        "activate interfaces ge-0/0/0\n"
    )
    tree = PARSER.parse(text)
    # The state node for ge-0/0/0 stays at its first-occurrence position (between the
    # two `set` lines), even after the toggle to `activate`.
    assert [c.line for c in tree.root.children] == [
        "set system host-name foo",
        "activate interfaces ge-0/0/0",
        "set interfaces ge-0/0/1 unit 0",
    ]


def test_set_activate_empty_path_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("activate \n")


def test_set_deactivate_empty_path_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("deactivate \n")


def test_set_strips_unquoted_hash_comment() -> None:
    text = "set system host-name foo  # trailing comment\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["set system host-name foo"]


def test_set_strips_unquoted_double_slash_comment() -> None:
    text = "set system host-name foo  // trailing comment\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["set system host-name foo"]


def test_set_skips_full_hash_comment_line() -> None:
    text = "# leading comment\nset system host-name foo\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == ["set system host-name foo"]


def test_set_preserves_hash_inside_double_quotes() -> None:
    """``#`` inside ``"..."`` is data, not a comment — must survive parsing."""

    text = 'set interfaces ge-0/0/0 description "aaa # bbb ccc"\n'
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        'set interfaces ge-0/0/0 description "aaa # bbb ccc"',
    ]


def test_set_preserves_double_slash_inside_double_quotes() -> None:
    text = 'set interfaces ge-0/0/0 description "https://example.com"\n'
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        'set interfaces ge-0/0/0 description "https://example.com"',
    ]


def test_set_user_example_three_state_toggle() -> None:
    text = (
        "set interface ge-0/0/0 unit 0 family inet address 192.168.1.1/24\n"
        "deactivate interface ge-0/0/0\n"
        "activate interface ge-0/0/0\n"
        "set interface ge-0/0/1 unit 0 family inet address 192.168.2.1/24\n"
        "activate interface ge-0/0/1\n"
    )
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children] == [
        "set interface ge-0/0/0 unit 0 family inet address 192.168.1.1/24",
        "activate interface ge-0/0/0",
        "set interface ge-0/0/1 unit 0 family inet address 192.168.2.1/24",
        "activate interface ge-0/0/1",
    ]
