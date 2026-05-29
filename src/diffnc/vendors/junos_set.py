"""Junos set-form vendor parser.

Handles the flat ``set ...`` form produced by ``display set``. Documents are modelled as a
flat list of leaves (one per logical ``set`` statement); duplicate statements collapse to
one. ``activate <path>`` and ``deactivate <path>`` are treated as a tri-state per path
(activated / deactivated / unspecified), applied in input order — the last toggle wins and
only one state node per path remains in the tree. ``delete <path>`` is applied in-order:
it removes any earlier ``set``/``activate``/``deactivate`` whose path equals or starts
with ``<path>`` at a token boundary, mirroring the Junos CLI semantics. Subsequent ``set``
statements may re-add state.

Line comments (``#``, ``//`` to end of line) are stripped during parsing.

The hierarchical (``show configuration``) form is handled by a separate vendor, see
:mod:`diffnc.vendors.junos`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from diffnc.errors import ParseError
from diffnc.ir import ConfigNode, ConfigTree
from diffnc.vendors.base import VendorParser

if TYPE_CHECKING:
    from diffnc.reconcile import ReconcileEvent

_SET_PREFIXES = ("set ", "deactivate ", "activate ")
_DELETE_PREFIX = "delete "
_TOGGLE_PREFIXES = ("activate ", "deactivate ")
_VALID_SET_PREFIXES = (*_SET_PREFIXES, _DELETE_PREFIX)


@dataclass
class _JunosSetParser:
    name: str = "junos_set"

    def parse(self, text: str) -> ConfigTree:
        tree = ConfigTree.empty(vendor=self.name)
        for lineno, raw in enumerate(text.splitlines(), start=1):
            stripped = _strip_line_comment(raw).strip()
            if not stripped:
                continue
            if not stripped.startswith(_VALID_SET_PREFIXES):
                raise ParseError(
                    f"line {lineno}: expected 'set'/'activate'/'deactivate'/'delete' line, "
                    f"got {stripped!r}"
                )
            if stripped.startswith(_DELETE_PREFIX):
                path = stripped[len(_DELETE_PREFIX) :].strip()
                if not path:
                    raise ParseError(f"line {lineno}: 'delete' requires a path")
                _apply_delete(tree.root, path)
                continue
            if stripped.startswith(_TOGGLE_PREFIXES):
                op, _, path = stripped.partition(" ")
                path = path.strip()
                if not path:
                    raise ParseError(f"line {lineno}: {op!r} requires a path")
                _apply_state_toggle(tree.root, path, stripped)
                continue
            tree.root.add_child(ConfigNode(line=stripped))
        return tree

    def format(self, tree: ConfigTree) -> list[str]:
        return [child.line for child in tree.root.children]

    def render_open(self, node: ConfigNode, depth: int) -> str:
        # Set form has no sections, so this should never be invoked by the diff engine.
        raise ParseError("render_open is not applicable to Junos set form")

    def render_close(self, node: ConfigNode, depth: int) -> str | None:
        return None

    def render_leaf(self, node: ConfigNode, depth: int) -> str:
        return node.line

    def is_order_sensitive(self, path: tuple[str, ...]) -> bool:
        """Set form has no semantically ordered children.

        :meth:`parse` already replays the activate/deactivate/delete operations to a
        canonical final state, so the IR's residual order is just whatever the input
        happened to leave behind — never load-bearing.
        """

        return False

    def render_reconcile(self, events: Iterable[ReconcileEvent]) -> Iterator[str]:
        from diffnc.reconcile import ReconcileAdd, ReconcileDelete

        for ev in events:
            if isinstance(ev, ReconcileAdd):
                yield ev.node.line
            elif isinstance(ev, ReconcileDelete):
                yield f"delete {_strip_set_prefix(ev.node.line)}"


def _apply_state_toggle(root: ConfigNode, path: str, new_line: str) -> None:
    """Toggle the activate/deactivate state for ``path``.

    Replaces any existing ``activate <path>`` / ``deactivate <path>`` child line in place
    (preserving first-occurrence position), or appends a new state node when none exists.
    """

    activate_line = f"activate {path}"
    deactivate_line = f"deactivate {path}"
    for child in root.children:
        if child.line == activate_line or child.line == deactivate_line:
            child.line = new_line
            return
    root.children.append(ConfigNode(line=new_line))


def _strip_set_prefix(line: str) -> str:
    for prefix in _SET_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix) :]
    return line


def _apply_delete(root: ConfigNode, delete_path: str) -> None:
    """Drop children whose set-form path equals or token-prefix-matches ``delete_path``."""

    boundary = delete_path + " "
    surviving: list[ConfigNode] = []
    for child in root.children:
        path = _strip_set_prefix(child.line)
        if path == delete_path or path.startswith(boundary):
            continue
        surviving.append(child)
    root.children = surviving


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


PARSER: VendorParser = _JunosSetParser()
