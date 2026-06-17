"""Shared parser for Cisco-style "indent + ``!`` comments" vendors.

IOS, NX-OS, IOS-XE, IOS-XR, and Arista EOS all share the same structural grammar:

* Section heads (e.g. ``interface ...``, ``router ospf 1``) introduce nested children at
  deeper indent. Indentation is significant; depth is determined by the stack of seen
  indents, not by a fixed unit.
* Lines starting with ``!`` or ``#`` are comments and discarded.
* Some vendors use trailing keywords like ``end`` / ``exit`` / ``commit`` / ``root`` as
  configuration terminators that should be ignored during parse.
* ``X`` / ``no X`` form a tri-state per parent — the last toggle in input order wins and
  only one of the two appears in the parent's children (skipped inside order-sensitive
  sections such as ACLs, where every line is positional).
* ``default <args>`` drops siblings under the current parent whose line equals or
  token-prefix-matches ``<args>`` (including the ``no <args>`` toggle counterpart).

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
# Positive boolean commands that reset to default when removed (no value to negate). Their
# ``no`` form is handled generically via the ``no `` prefix; this set only lists the bare
# positive spellings that are likewise toggles rather than valued settings.
_POSITIVE_BOOLEANS = frozenset({"shutdown"})


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
    # Whether this OS supports the ``default <cmd>`` form. IOS / IOS-XE / NX-OS / EOS do;
    # IOS-XR does not (it resets state by inverting the ``no``). Controls how removed
    # toggles are rendered by :meth:`render_reconcile`.
    supports_default: bool = True

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

            # `X` / `no X` form a per-parent toggle whose last occurrence wins. Collapse
            # them to a single state node, except inside order-sensitive sections (ACLs,
            # policy-maps) where every line is positional and a `no` form is a literal entry.
            path = tuple(node.line for _, node in stack[1:])
            if not self.order_sensitive_predicate(path) and _apply_no_toggle(parent_node, stripped):
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

    def toggle_partners(self, a: str, b: str) -> bool:
        """``X`` and ``no X`` are the two faces of one toggle."""

        return a == f"no {b}" or b == f"no {a}"

    def toggle_partner_of(self, line: str) -> str | None:
        """The single toggle counterpart of *line*: ``no X`` for ``X`` and vice versa."""

        return line[3:] if line.startswith("no ") else f"no {line}"

    def is_toggle_state(self, line: str) -> bool:
        """A ``no``-prefixed line or a bare positive boolean (``shutdown``)."""

        return line.startswith("no ") or line in _POSITIVE_BOOLEANS

    def render_reconcile(self, events: Iterable[ReconcileEvent]) -> Iterator[str]:
        from diffnc.reconcile import (
            ReconcileAdd,
            ReconcileDelete,
            ReconcileRecreate,
            ReconcileToggle,
        )

        last_path: tuple[str, ...] | None = None
        for ev in events:
            if isinstance(ev, ReconcileToggle):
                # Cisco-like vendors have no ``inactive:``-style prefix (their base identity is
                # the line itself), so a toggle event is never produced for them. Guard anyway.
                continue
            if isinstance(ev, ReconcileRecreate):
                parents = ev.section_path[:-1]
                section_header = ev.section_path[-1]
                yield from self._emit_path(parents)
                depth = len(parents)
                yield self._pad(depth) + f"no {section_header}"
                yield self._pad(depth) + section_header
                for child in ev.new_node.children:
                    yield from render_subtree(self, child, depth + 1)
                last_path = None
                continue

            if ev.parent_path != last_path:
                yield from self._emit_path(ev.parent_path)
                last_path = ev.parent_path

            depth = len(ev.parent_path)
            if isinstance(ev, ReconcileAdd):
                yield from render_subtree(self, ev.node, depth)
            elif isinstance(ev, ReconcileDelete):
                if ev.node.is_leaf:
                    yield self._pad(depth) + self._render_removal(ev.node.line)
                else:
                    yield self._pad(depth) + _negate(ev.node.line)

    def _render_removal(self, line: str) -> str:
        """Render the removal of a leaf setting.

        Toggles (``no X`` / bare booleans) reset to default: ``default <base>`` on vendors
        that support it, otherwise the inverted ``no`` (IOS-XR). Valued settings
        (``description foo`` …) are negated with ``no`` as before.
        """

        if self.supports_default and self.is_toggle_state(line):
            base = line[3:] if line.startswith("no ") else line
            return f"default {base}"
        return _negate(line)

    def _emit_path(self, path: tuple[str, ...]) -> Iterator[str]:
        for depth, line in enumerate(path):
            yield self._pad(depth) + line

    def _pad(self, depth: int) -> str:
        return " " * (self.indent_unit * depth)


def _negate(line: str) -> str:
    """Return the negation of *line* under Cisco's ``no`` semantics.

    ``"description foo"`` → ``"no description foo"``; ``"no shutdown"`` → ``"shutdown"``.
    Avoids ``"no no <foo>"`` double negation.
    """

    if line.startswith("no "):
        return line[3:]
    return f"no {line}"


def _apply_no_toggle(parent: ConfigNode, line: str) -> bool:
    """Collapse ``line`` with its ``X`` / ``no X`` toggle partner under ``parent``.

    Looks only for the *opposite-polarity* partner (``no X`` pairs with ``X`` and vice
    versa); a sibling leaf partner is replaced in place so the last occurrence wins while
    keeping its position. A lone ``no X`` with no partner is recorded as a leaf. Returns
    ``True`` when ``line`` was handled as a toggle; ``False`` means the caller should add
    it as an ordinary node (which may turn out to be a section).

    A same-polarity duplicate (a re-declared ``X``, e.g. an ``interface`` block stated
    twice) is *not* a toggle: it returns ``False`` so the caller's :meth:`add_child` merges
    it and keeps it on the indent stack, letting the re-declared section adopt its children.
    """

    partner = line[3:] if line.startswith("no ") else f"no {line}"
    existing = parent.child_by_line(partner)
    if existing is not None and existing.is_leaf:
        parent.relabel_child(existing, line)  # last toggle wins; position preserved
        return True
    if line.startswith("no "):
        parent.add_child(ConfigNode(line=line))  # lone "no X" directive (always a leaf)
        return True
    return False


def _apply_default(parent: ConfigNode, default_path: str) -> None:
    """Drop ``parent``'s children whose line equals or token-prefix-matches ``default_path``.

    Both the positive form and its ``no <path>`` toggle counterpart are dropped, so
    ``default shutdown`` resets the interface whether it currently holds ``shutdown`` or
    ``no shutdown``.
    """

    no_path = f"no {default_path}"
    prefixes = (default_path + " ", no_path + " ")
    exact = (default_path, no_path)
    surviving: list[ConfigNode] = []
    for child in parent.children:
        if child.line in exact or child.line.startswith(prefixes):
            continue
        surviving.append(child)
    parent.retain_children(surviving)


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


# Re-export for typing convenience.
__all__ = ["CiscoLikeParser", "VendorParser", "cisco_default_order_sensitive"]
