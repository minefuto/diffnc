from __future__ import annotations

import pytest

from diffnc.errors import ParseError
from diffnc.vendors.junos import PARSER


def test_hier_parse_nested() -> None:
    text = "system {\n    host-name foo;\n    services {\n        ssh;\n    }\n}\n"
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    system = tree.root.children[0]
    assert system.line == "system"
    names = [c.line for c in system.children]
    assert names == ["host-name foo", "services"]
    services = system.children[1]
    assert [c.line for c in services.children] == ["ssh"]


def test_hier_merges_duplicate_sections() -> None:
    text = "system {\n    host-name foo;\n}\nsystem {\n    domain-name example.com;\n}\n"
    tree = PARSER.parse(text)
    assert len(tree.root.children) == 1
    system = tree.root.children[0]
    assert [c.line for c in system.children] == [
        "host-name foo",
        "domain-name example.com",
    ]


def test_hier_strips_block_comments() -> None:
    text = "system {\n    /* a comment */\n    host-name foo;\n}\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children[0].children] == ["host-name foo"]


def test_hier_strips_unquoted_hash_comment() -> None:
    text = "system {\n    host-name foo;  # trailing comment\n}\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children[0].children] == ["host-name foo"]


def test_hier_strips_unquoted_double_slash_comment() -> None:
    text = "system {\n    host-name foo;  // trailing comment\n}\n"
    tree = PARSER.parse(text)
    assert [c.line for c in tree.root.children[0].children] == ["host-name foo"]


def test_hier_preserves_hash_inside_double_quotes() -> None:
    """A ``#`` inside ``"..."`` is data, not a comment — must survive parsing."""

    text = 'interfaces {\n    ge-0/0/0 {\n        description "aaa # bbb ccc";\n    }\n}\n'
    tree = PARSER.parse(text)
    ge = tree.root.children[0].children[0]
    assert [c.line for c in ge.children] == ['description "aaa # bbb ccc"']


def test_hier_preserves_double_slash_inside_double_quotes() -> None:
    text = 'interfaces {\n    ge-0/0/0 {\n        description "https://example.com";\n    }\n}\n'
    tree = PARSER.parse(text)
    ge = tree.root.children[0].children[0]
    assert [c.line for c in ge.children] == ['description "https://example.com"']


def test_hier_unmatched_brace_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("}\n")


def test_hier_unterminated_statement_raises() -> None:
    with pytest.raises(ParseError):
        PARSER.parse("system {\n    host-name foo\n}\n")


def test_hier_format_round_trip() -> None:
    text = "system {\n    host-name foo;\n    services {\n        ssh;\n    }\n}\n"
    tree = PARSER.parse(text)
    assert PARSER.format(tree) == [
        "system {",
        "    host-name foo;",
        "    services {",
        "        ssh;",
        "    }",
        "}",
    ]


def test_hier_inactive_section_preserved() -> None:
    text = "interfaces {\n    inactive: ge-0/0/0 {\n        unit 0;\n    }\n}\n"
    tree = PARSER.parse(text)
    interfaces = tree.root.children[0]
    assert interfaces.line == "interfaces"
    assert [c.line for c in interfaces.children] == ["inactive: ge-0/0/0"]
    assert [c.line for c in interfaces.children[0].children] == ["unit 0"]


def test_hier_inactive_leaf_preserved() -> None:
    text = "system {\n    inactive: host-name foo;\n}\n"
    tree = PARSER.parse(text)
    system = tree.root.children[0]
    assert [c.line for c in system.children] == ["inactive: host-name foo"]
