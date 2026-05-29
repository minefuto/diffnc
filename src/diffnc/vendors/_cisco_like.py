"""Shared parser for Cisco-style "indent + ``!`` comments" vendors.

IOS, NX-OS, IOS-XE, IOS-XR, and Arista EOS all share the same structural grammar:

* Section heads (e.g. ``interface ...``, ``router ospf 1``) introduce nested children at
  deeper indent. Indentation is significant; depth is determined by the stack of seen
  indents, not by a fixed unit.
* Lines starting with ``!`` or ``#`` are comments and discarded.
* Some vendors use trailing keywords like ``end`` / ``exit`` / ``commit`` / ``root`` as
  configuration terminators that should be ignored during parse.
* ``shutdown`` / ``no shutdown`` form a tri-state per parent — the last toggle in input
  order wins and only one of the two appears in the parent's children.
* ``default <args>`` drops siblings under the current parent whose line equals or
  token-prefix-matches ``<args>``.

Vendors differ only in:

* the rendered indent width (`indent_unit`)
* which standalone keywords act as terminators (`terminators`)
* the vendor name reported by :attr:`name`

so this module exposes :class:`CiscoLikeParser` parameterised on those three knobs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from diffnc.errors import ParseError
from diffnc.ir import ConfigNode, ConfigTree
from diffnc.vendors.base import VendorParser, render_subtree

if TYPE_CHECKING:
    from diffnc.reconcile import ReconcileEvent

_DEFAULT_PREFIX = "default "
_SHUT_STATES = ("shutdown", "no shutdown")


def cisco_default_order_sensitive(path: tuple[str, ...]) -> bool:
    """Path-based order-sensitivity shared by IOS / IOS-XE / IOS-XR / NX-OS / EOS.

    ACL entries (``ip``/``ipv6``/``mac access-list``) and ``policy-map`` class blocks
    are evaluated top-to-bottom in the order they appear; everything else (interfaces,
    VRFs, ``route-map FOO permit <seq>`` siblings at top level, …) is order-insensitive.
    """

    if not path:
        return False
    head = path[-1]
    if head.startswith(("ip access-list ", "ipv6 access-list ", "mac access-list ")):
        return True
    return head.startswith("policy-map ")


@dataclass
class CiscoLikeParser:
    name: str
    indent_unit: int
    terminators: frozenset[str] = field(default_factory=frozenset)
    order_sensitive_predicate: Callable[[tuple[str, ...]], bool] = field(
        default=cisco_default_order_sensitive
    )

    def parse(self, text: str) -> ConfigTree:
        tree = ConfigTree.empty(vendor=self.name)

        stack: list[tuple[int, ConfigNode]] = [(-1, tree.root)]

        for lineno, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("!") or stripped.startswith("#"):
                continue
            if stripped in self.terminators:
                continue

            indent = _leading_spaces(raw)

            while stack and indent <= stack[-1][0]:
                stack.pop()
            if not stack:
                raise ParseError(f"line {lineno}: unexpected indentation in {self.name} config")

            parent_node = stack[-1][1]

            if stripped == "default" or stripped.startswith(_DEFAULT_PREFIX):
                path = stripped[len(_DEFAULT_PREFIX) :].strip() if stripped != "default" else ""
                if not path:
                    raise ParseError(f"line {lineno}: 'default' requires a path")
                _apply_default(parent_node, path)
                continue

            if stripped in _SHUT_STATES:
                _apply_shut_toggle(parent_node, stripped)
                continue

            actual = parent_node.add_child(ConfigNode(line=stripped))
            stack.append((indent, actual))

        return tree

    def format(self, tree: ConfigTree) -> list[str]:
        lines: list[str] = []
        for child in tree.root.children:
            lines.extend(render_subtree(self, child, depth=0))
        return lines

    def render_open(self, node: ConfigNode, depth: int) -> str:
        return self._pad(depth) + node.line

    def render_close(self, node: ConfigNode, depth: int) -> str | None:
        return None

    def render_leaf(self, node: ConfigNode, depth: int) -> str:
        return self._pad(depth) + node.line

    def is_order_sensitive(self, path: tuple[str, ...]) -> bool:
        return self.order_sensitive_predicate(path)

    def render_reconcile(self, events: Iterable[ReconcileEvent]) -> Iterator[str]:
        from diffnc.reconcile import ReconcileAdd, ReconcileDelete, ReconcileRecreate

        last_path: tuple[str, ...] | None = None
        for ev in events:
            if isinstance(ev, ReconcileRecreate):
                parents = ev.section_path[:-1]
                section_header = ev.section_path[-1]
                yield from parents
                yield f"no {section_header}"
                yield from parents
                yield section_header
                for child in ev.new_node.children:
                    yield from _walk_lines(child)
                last_path = None
                continue

            if ev.parent_path != last_path:
                yield from ev.parent_path
                last_path = ev.parent_path

            if isinstance(ev, ReconcileAdd):
                yield from _walk_lines(ev.node)
            elif isinstance(ev, ReconcileDelete):
                yield _negate(ev.node.line)

    def _pad(self, depth: int) -> str:
        return " " * (self.indent_unit * depth)


def _walk_lines(node: ConfigNode) -> Iterator[str]:
    """Yield ``node.line`` followed by each descendant's line, pre-order."""

    yield node.line
    for child in node.children:
        yield from _walk_lines(child)


def _negate(line: str) -> str:
    """Return the negation of *line* under Cisco's ``no`` semantics.

    ``"description foo"`` → ``"no description foo"``; ``"no shutdown"`` → ``"shutdown"``.
    Avoids ``"no no <foo>"`` double negation.
    """

    if line.startswith("no "):
        return line[3:]
    return f"no {line}"


def _apply_shut_toggle(parent: ConfigNode, new_state: str) -> None:
    """Toggle the shutdown/no-shutdown state under ``parent``.

    Replaces any existing ``shutdown``/``no shutdown`` child line in place (preserving
    first-occurrence position), or appends a new state node when none exists.
    """

    for child in parent.children:
        if child.line in _SHUT_STATES:
            child.line = new_state
            return
    parent.children.append(ConfigNode(line=new_state))


def _apply_default(parent: ConfigNode, default_path: str) -> None:
    """Drop ``parent``'s children whose line equals or token-prefix-matches ``default_path``."""

    boundary = default_path + " "
    surviving: list[ConfigNode] = []
    for child in parent.children:
        if child.line == default_path or child.line.startswith(boundary):
            continue
        surviving.append(child)
    parent.children = surviving


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


# Re-export for typing convenience.
__all__ = ["CiscoLikeParser", "VendorParser", "cisco_default_order_sensitive"]
