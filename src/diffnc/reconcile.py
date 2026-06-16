"""Generate config-mode commands that transform config *A* into config *B*.

Walks two :class:`~diffnc.ir.ConfigTree`'s in parallel and emits a stream of
:class:`ReconcileEvent`'s — one per added subtree, deleted subtree, or order-sensitive
section that needs to be recreated wholesale. Each vendor's :meth:`render_reconcile` then
translates those events into its own CLI syntax (``no`` / ``set`` / ``delete`` ...).

Output is intentionally bare config-mode commands: no ``configure terminal`` / ``end`` /
``commit`` wrappers. Lines are indented to mirror the section hierarchy (using each
vendor's own indent unit) so the result reads like the source config; flat vendors such
as Junos set form emit no indentation. The caller is expected to pipe the result into a
session that's already in config mode (e.g. ``... | ssh device 'configure terminal; ...'``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from diffnc.diff import _prepare
from diffnc.ir import ConfigNode
from diffnc.vendors.base import (
    VendorParser,
    is_order_sensitive_for,
    is_toggle_state_for,
    leaf_section_render_equivalent,
    render_subtree,
    toggle_partners_for,
)


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

    a_only_leaves = [c for c in node_a.children if c.line not in b_by_line and c.is_leaf]
    b_only_leaves = [c for c in node_b.children if c.line not in a_by_line and c.is_leaf]
    suppressed = _suppressed_deletes(parser, a_only_leaves, b_only_leaves)

    for child_a in node_a.children:
        child_b = b_by_line.get(child_a.line)
        if child_b is None:
            # Suppressed: the A leaf is overwritten by a B-side value change, or it is one
            # face of a toggle whose new state B emits directly (e.g. `no shutdown` ->
            # `shutdown`), so the explicit delete would be redundant or contradictory.
            if not (child_a.is_leaf and child_a.line in suppressed):
                yield ReconcileDelete(parent_path, child_a)
            continue
        if child_a.is_leaf and child_b.is_leaf:
            continue
        if child_a.is_leaf != child_b.is_leaf and not _section_leaf_equivalent(
            parser, child_a, child_b
        ):
            # A leaf that genuinely became a section, or vice versa (e.g. Junos `foo;` <->
            # `foo { ... }`). Indent vendors instead fall through and diff children: an
            # empty `interface eth1` is just a section with no children.
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


def _section_leaf_equivalent(
    parser: VendorParser, child_a: ConfigNode, child_b: ConfigNode
) -> bool:
    """Whether a section-vs-leaf mismatch is just an empty section spelled as a leaf.

    Mirrors :func:`diffnc.diff._equal_pair`: for indent-based vendors a populated and an
    empty section share the same header line, so the two can be diffed as one section.
    """

    leaf = child_a if child_a.is_leaf else child_b
    section = child_b if child_a.is_leaf else child_a
    return leaf_section_render_equivalent(parser, leaf, section, 0)


def _suppressed_deletes(
    parser: VendorParser,
    a_only_leaves: list[ConfigNode],
    b_only_leaves: list[ConfigNode],
) -> set[str]:
    """A-only leaf lines whose ReconcileDelete should be suppressed.

    Two independent reasons: the leaf is one face of a toggle whose new state appears on
    the B side (handled by emitting the B value directly), or it is a value-only change
    superseded by a B-side overwrite. Toggle-state lines are excluded from the value-change
    pass — their trailing token is part of an identity (a path), not a tweakable value.
    """

    suppressed: set[str] = set()
    for a in a_only_leaves:
        if any(toggle_partners_for(parser, a.line, b.line) for b in b_only_leaves):
            suppressed.add(a.line)

    val_a = [c for c in a_only_leaves if not is_toggle_state_for(parser, c.line)]
    val_b = [c for c in b_only_leaves if not is_toggle_state_for(parser, c.line)]
    suppressed |= _value_change_suppressed(val_a, val_b)
    return suppressed


def _subtrees_equal(parser: VendorParser, a: ConfigNode, b: ConfigNode) -> bool:
    """True iff *a* and *b* render to identical line sequences."""

    return render_subtree(parser, a, 0) == render_subtree(parser, b, 0)


def _value_head(line: str) -> str | None:
    """The part of *line* before its trailing token, or ``None`` if it has only one token.

    ``"metric 10"`` → ``"metric"``; ``"ip ospf cost 10"`` → ``"ip ospf cost"``;
    ``"shutdown"`` → ``None``.
    """

    head, sep, _ = line.rpartition(" ")
    return head if sep else None


def _value_change_suppressed(
    a_only_leaves: list[ConfigNode], b_only_leaves: list[ConfigNode]
) -> set[str]:
    """Return the A-only leaf lines whose deletion is superseded by a B-only value change.

    An A-only leaf and a B-only leaf that share the same :func:`_value_head` (i.e. differ
    only in the trailing value token) represent the same setting with a new value. Entering
    the new value overwrites the old, so the explicit delete of the A line is redundant and
    suppressed. Pairs are matched one-to-one (each B leaf justifies at most one suppression),
    so genuinely separate settings are not collapsed.
    """

    used = [False] * len(b_only_leaves)
    suppressed: set[str] = set()
    for a in a_only_leaves:
        head = _value_head(a.line)
        if head is None:
            continue
        for i, b in enumerate(b_only_leaves):
            if not used[i] and _value_head(b.line) == head:
                used[i] = True
                suppressed.add(a.line)
                break
    return suppressed
