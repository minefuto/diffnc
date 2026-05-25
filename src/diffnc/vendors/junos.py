"""Junos hierarchical-form vendor parser.

Handles the curly-brace form produced by ``show configuration``. Documents are modelled as
a nested tree matching their brace structure, with same-named sibling blocks merged. The
``inactive:`` prefix is preserved verbatim on the node line (mirroring how NX-OS keeps
``no`` as part of its command line).

Block comments (``/* ... */``) and line comments (``#``, ``//`` to end of line) are
stripped during parsing.

The set form (``display set`` output) is handled by a separate vendor, see
:mod:`diffnc.vendors.junos_set`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from diffnc.errors import ParseError
from diffnc.ir import ConfigNode, ConfigTree
from diffnc.vendors.base import VendorParser, render_subtree

INDENT_UNIT = 4

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


@dataclass
class _JunosParser:
    name: str = "junos"

    def parse(self, text: str) -> ConfigTree:
        cleaned = _BLOCK_COMMENT.sub("", text)
        tree = ConfigTree.empty(vendor=self.name)
        stack: list[ConfigNode] = [tree.root]

        for lineno, raw in enumerate(cleaned.splitlines(), start=1):
            stripped = _strip_line_comment(raw).strip()
            if not stripped:
                continue

            if stripped == "}":
                if len(stack) <= 1:
                    raise ParseError(f"line {lineno}: unmatched '}}'")
                stack.pop()
                continue

            if stripped.endswith("{"):
                name = stripped[:-1].strip()
                if not name:
                    raise ParseError(f"line {lineno}: anonymous block")
                actual = stack[-1].add_child(ConfigNode(line=name))
                stack.append(actual)
            elif stripped.endswith(";"):
                name = stripped[:-1].strip()
                if name:
                    stack[-1].add_child(ConfigNode(line=name))
            else:
                raise ParseError(
                    f"line {lineno}: unterminated statement (expected ';' or '{{'): {stripped!r}"
                )

        if len(stack) != 1:
            raise ParseError("unclosed block at end of Junos hierarchical config")

        return tree

    def format(self, tree: ConfigTree) -> list[str]:
        lines: list[str] = []
        for child in tree.root.children:
            lines.extend(render_subtree(self, child, depth=0))
        return lines

    def render_open(self, node: ConfigNode, depth: int) -> str:
        return f"{_pad(depth)}{node.line} {{"

    def render_close(self, node: ConfigNode, depth: int) -> str | None:
        return f"{_pad(depth)}}}"

    def render_leaf(self, node: ConfigNode, depth: int) -> str:
        return f"{_pad(depth)}{node.line};"

    def is_order_sensitive(self, path: tuple[str, ...]) -> bool:
        """Term order matters inside firewall filters and policy-statements.

        Junos evaluates ``term`` entries top-to-bottom, so a reorder changes behaviour
        even when the term bodies are identical. Everything else in a Junos config is
        a (named) container where ordering is purely cosmetic.
        """

        # firewall { filter <name> { term ... } }
        if len(path) == 2 and path[0] == "firewall" and path[1].startswith("filter "):
            return True
        # firewall { family <fam> { filter <name> { term ... } } }
        if (
            len(path) == 3
            and path[0] == "firewall"
            and path[1].startswith("family ")
            and path[2].startswith("filter ")
        ):
            return True
        # policy-options { policy-statement <name> { term ... } }
        return (
            len(path) == 2
            and path[0] == "policy-options"
            and path[1].startswith("policy-statement ")
        )


def _strip_line_comment(line: str) -> str:
    """Truncate at the first ``#`` or ``//`` that lies outside a double-quoted string."""

    in_quote = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == '"':
            in_quote = not in_quote
            i += 1
            continue
        if not in_quote:
            if ch == "#":
                return line[:i]
            if ch == "/" and i + 1 < n and line[i + 1] == "/":
                return line[:i]
        i += 1
    return line


def _pad(depth: int) -> str:
    return " " * (INDENT_UNIT * depth)


PARSER: VendorParser = _JunosParser()
