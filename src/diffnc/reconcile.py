"""Generate config-mode commands that transform config *A* into config *B*.

Walks two :class:`~diffnc.ir.ConfigTree`'s in parallel and emits a stream of
:class:`ReconcileEvent`'s — one per added subtree, deleted subtree, or order-sensitive
section that needs to be recreated wholesale. Each vendor's :meth:`render_reconcile` then
translates those events into its own CLI syntax (``no`` / ``set`` / ``delete`` ...).

Output is intentionally bare config-mode commands: no ``configure terminal`` / ``end`` /
``commit`` wrappers, no indentation. The caller is expected to pipe the result into a
session that's already in config mode (e.g. ``... | ssh device 'configure terminal; ...'``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from diffnc.diff import _prepare
from diffnc.ir import ConfigNode
from diffnc.vendors.base import VendorParser, is_order_sensitive_for, render_subtree


@dataclass(frozen=True)
class ReconcileAdd:
    """A subtree present in *B* but not in *A* at ``parent_path``."""

    parent_path: tuple[str, ...]
    node: ConfigNode


@dataclass(frozen=True)
class ReconcileDelete:
    """A subtree present in *A* but not in *B* at ``parent_path``."""

    parent_path: tuple[str, ...]
    node: ConfigNode


@dataclass(frozen=True)
class ReconcileRecreate:
    """An order-sensitive section whose children differ — wipe and recreate.

    ``section_path`` is the full path *including* the section to recreate (its last
    element is the section header). ``new_node`` is the B-side parent node, whose
    children become the new contents of the section.
    """

    section_path: tuple[str, ...]
    new_node: ConfigNode


ReconcileEvent = ReconcileAdd | ReconcileDelete | ReconcileRecreate


def reconcile(
    a: str | Iterable[str],
    b: str | Iterable[str],
    *,
    vendor: str | None = None,
) -> Iterator[str]:
    """Yield config-mode commands that, when entered on a device running config *A*,
    bring it to the state described by config *B*.

    Output lines do not include a trailing newline; callers that need newline-terminated
    output should append one themselves (mirrors :func:`diffnc.unified_diff`).

    Raises:
        VendorMismatchError, ParseError: see :mod:`diffnc.errors`.
        NotImplementedError: if the resolved vendor parser does not implement
            :meth:`~diffnc.vendors.base.VendorParser.render_reconcile`.
    """

    parser, tree_a, tree_b = _prepare(a, b, vendor=vendor)
    events = list(_collect_events(parser, tree_a.root, tree_b.root, parent_path=()))
    if not events:
        return
    render = getattr(parser, "render_reconcile", None)
    if render is None:
        raise NotImplementedError(f"vendor {parser.name!r} does not support command generation")
    yield from render(events)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _collect_events(
    parser: VendorParser,
    node_a: ConfigNode,
    node_b: ConfigNode,
    parent_path: tuple[str, ...],
) -> Iterator[ReconcileEvent]:
    """Diff two parent nodes' children and yield reconcile events.

    Mirrors the order-insensitive matching used by :func:`diffnc.diff._diff_children`
    but emits semantic events instead of display lines, and short-circuits any
    order-sensitive subsection into a single :class:`ReconcileRecreate`.
    """

    b_by_line = {c.line: c for c in node_b.children}
    a_by_line = {c.line: c for c in node_a.children}

    for child_a in node_a.children:
        child_b = b_by_line.get(child_a.line)
        if child_b is None:
            yield ReconcileDelete(parent_path, child_a)
            continue
        if child_a.is_leaf and child_b.is_leaf:
            continue
        if child_a.is_leaf != child_b.is_leaf:
            yield ReconcileDelete(parent_path, child_a)
            yield ReconcileAdd(parent_path, child_b)
            continue

        next_path = (*parent_path, child_a.line)
        if is_order_sensitive_for(parser, next_path):
            if not _subtrees_equal(parser, child_a, child_b):
                yield ReconcileRecreate(next_path, child_b)
            continue

        yield from _collect_events(parser, child_a, child_b, next_path)

    for child_b in node_b.children:
        if child_b.line not in a_by_line:
            yield ReconcileAdd(parent_path, child_b)


def _subtrees_equal(parser: VendorParser, a: ConfigNode, b: ConfigNode) -> bool:
    """True iff *a* and *b* render to identical line sequences."""

    return render_subtree(parser, a, 0) == render_subtree(parser, b, 0)
