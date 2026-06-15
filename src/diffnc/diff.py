"""Structural diff engine.

The algorithm walks two :class:`~diffnc.ir.ConfigTree`'s in parallel, computing per-level
opcodes with :class:`difflib.SequenceMatcher` keyed on each node's ``line``. For matched
sections we recurse so that only their *changed descendants* surface; the matched section
header itself is emitted as a context line so the user can see the surrounding scope.

Two flavours are exposed, both modelled on :mod:`difflib`:

* :func:`unified_diff` — compact: only changed lines plus the section path leading to them
  (and ``--- a`` / ``+++ b`` headers if file names are supplied).
* :func:`ndiff` — verbose: every line is shown, prefixed with ``- ``, ``+ `` or ``  ``.

Both functions accept either ``str`` (raw config text) or ``list[str]`` (already-split
lines, joined internally) for parity with :mod:`difflib`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from diffnc import vendors as _vendors
from diffnc.detect import detect_vendor, is_empty_config
from diffnc.errors import VendorMismatchError
from diffnc.ir import ConfigNode, ConfigTree
from diffnc.vendors.base import VendorParser, is_order_sensitive_for, render_subtree

_SIMILARITY_CUTOFF = 0.6  # difflib.get_close_matches の既定値に合わせる
_TOKEN_SHARE_CUTOFF = 0.4  # 先頭コマンド語が一致する場合に適用する緩い二次閾値


@dataclass(frozen=True)
class _Event:
    op: str  # one of ' ', '-', '+', '!'
    text: str  # already-indented line, no marker prefix


def unified_diff(
    a: str | Iterable[str],
    b: str | Iterable[str],
    fromfile: str = "",
    tofile: str = "",
    lineterm: str = "",
    *,
    vendor: str | None = None,
) -> Iterator[str]:
    """Yield a structural unified diff of *a* vs *b*.

    Equal leaves are omitted; only changed lines are shown, along with the path of
    enclosing sections (as ``  `` context lines) so the diff stays readable.

    Args:
        a, b: configuration text. ``str`` is taken verbatim; an iterable of strings is
            joined with newlines before parsing.
        fromfile, tofile: optional file names rendered as ``--- a`` / ``+++ b`` headers.
        lineterm: line terminator appended to each yielded line. Defaults to the empty
            string; callers that need newline-terminated lines should pass ``"\\n"``.
        vendor: skip auto-detection and force a specific parser. Ignored when unset.

    Raises:
        VendorMismatchError, ParseError: see :mod:`diffnc.errors`.
    """

    events = _structural_events(a, b, vendor=vendor)
    if not events:
        return

    if fromfile or tofile:
        yield f"--- {fromfile}{lineterm}"
        yield f"+++ {tofile}{lineterm}"
    for ev in events:
        yield f"{ev.op}{ev.text}{lineterm}"


def ndiff(
    a: str | Iterable[str],
    b: str | Iterable[str],
    lineterm: str = "",
    *,
    vendor: str | None = None,
) -> Iterator[str]:
    """Yield a verbose, every-line diff using ``- ``/``+ ``/``! ``/``  `` markers.

    ``lineterm`` defaults to the empty string; pass ``"\\n"`` for newline-terminated
    output.
    """

    parser, tree_a, tree_b = _prepare(a, b, vendor=vendor)
    events = list(
        _diff_children(parser, tree_a.root, tree_b.root, depth=0, hide_equal=False, path=())
    )
    for ev in events:
        marker = f"{ev.op} " if ev.op != " " else "  "
        yield f"{marker}{ev.text}{lineterm}"


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _structural_events(
    a: str | Iterable[str],
    b: str | Iterable[str],
    *,
    vendor: str | None,
) -> list[_Event]:
    parser, tree_a, tree_b = _prepare(a, b, vendor=vendor)
    return list(_diff_children(parser, tree_a.root, tree_b.root, depth=0, hide_equal=True, path=()))


def _prepare(
    a: str | Iterable[str],
    b: str | Iterable[str],
    *,
    vendor: str | None,
) -> tuple[VendorParser, ConfigTree, ConfigTree]:
    text_a = _coerce(a)
    text_b = _coerce(b)

    if vendor is None:
        empty_a = is_empty_config(text_a)
        empty_b = is_empty_config(text_b)
        if empty_a and empty_b:
            # Nothing to detect from and nothing to diff: both trees parse empty, so no
            # vendor-specific behaviour is ever reached and any registered parser will do.
            vendor_name = "nxos"
        elif empty_a or empty_b:
            # An empty side carries no vendor signal; detect from the other side only.
            vendor_name = detect_vendor(text_b if empty_a else text_a)
        else:
            vendor_a = detect_vendor(text_a)
            vendor_b = detect_vendor(text_b)
            if vendor_a != vendor_b:
                raise VendorMismatchError(vendor_a, vendor_b)
            vendor_name = vendor_a
    else:
        vendor_name = vendor

    parser = _vendors.get(vendor_name)
    tree_a = parser.parse(text_a)
    tree_b = parser.parse(text_b)
    return parser, tree_a, tree_b


def _coerce(value: str | Iterable[str]) -> str:
    if isinstance(value, str):
        return value
    return "\n".join(value)


def _diff_children(
    parser: VendorParser,
    node_a: ConfigNode,
    node_b: ConfigNode,
    depth: int,
    *,
    hide_equal: bool,
    path: tuple[str, ...],
) -> Iterator[_Event]:
    if is_order_sensitive_for(parser, path):
        yield from _diff_children_ordered(
            parser, node_a, node_b, depth, hide_equal=hide_equal, path=path
        )
    else:
        yield from _diff_children_unordered(
            parser, node_a, node_b, depth, hide_equal=hide_equal, path=path
        )


def _diff_children_ordered(
    parser: VendorParser,
    node_a: ConfigNode,
    node_b: ConfigNode,
    depth: int,
    *,
    hide_equal: bool,
    path: tuple[str, ...],
) -> Iterator[_Event]:
    """Positional matching via :class:`difflib.SequenceMatcher`.

    Used for parents whose children's evaluation order is semantically meaningful — e.g.
    Junos ``firewall filter`` terms, Cisco ``ip access-list`` ACEs, ``policy-map`` class
    blocks. Pure reorders (children whose rendered subtree is byte-identical on both
    sides) surface once with the ``!`` marker; genuine changes still show as ``-``/``+``
    pairs.
    """

    a_children = node_a.children
    b_children = node_b.children
    a_keys = [c.line for c in a_children]
    b_keys = [c.line for c in b_children]
    matcher = SequenceMatcher(a=a_keys, b=b_keys, autojunk=False)
    opcodes = matcher.get_opcodes()

    reordered_a, reordered_b = _collect_reorder_pairs(opcodes, a_children, b_children, parser)

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                child_a = a_children[i1 + k]
                child_b = b_children[j1 + k]
                yield from _equal_pair(parser, child_a, child_b, depth, hide_equal, path)
        elif tag == "delete":
            for k in range(i1, i2):
                op = "!" if k in reordered_a else "-"
                yield from _emit_one_side(parser, a_children[k], depth, op)
        elif tag == "insert":
            for k in range(j1, j2):
                if k in reordered_b:
                    continue
                yield from _emit_one_side(parser, b_children[k], depth, "+")
        elif tag == "replace":
            a_indices = list(range(i1, i2))
            b_indices = [k for k in range(j1, j2) if k not in reordered_b]
            for step in range(max(len(a_indices), len(b_indices))):
                if step < len(a_indices):
                    ka = a_indices[step]
                    op = "!" if ka in reordered_a else "-"
                    yield from _emit_one_side(parser, a_children[ka], depth, op)
                if step < len(b_indices):
                    kb = b_indices[step]
                    yield from _emit_one_side(parser, b_children[kb], depth, "+")


def _collect_reorder_pairs(
    opcodes: Sequence[tuple[str, int, int, int, int]],
    a_children: list[ConfigNode],
    b_children: list[ConfigNode],
    parser: VendorParser,
) -> tuple[set[int], set[int]]:
    """Find delete/insert pairs whose subtrees render identically — i.e. pure reorders.

    Returns ``(reordered_a_indices, reordered_b_indices)``. The A-side index is where
    we will emit a single ``!`` line; the B-side index marks the matching insert that
    should be suppressed.
    """

    a_indices: list[int] = []
    b_indices: list[int] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag in ("delete", "replace"):
            a_indices.extend(range(i1, i2))
        if tag in ("insert", "replace"):
            b_indices.extend(range(j1, j2))

    b_by_render: dict[tuple[str, ...], list[int]] = {}
    for idx in b_indices:
        key = tuple(render_subtree(parser, b_children[idx], 0))
        b_by_render.setdefault(key, []).append(idx)

    reordered_a: set[int] = set()
    reordered_b: set[int] = set()
    for idx in a_indices:
        key = tuple(render_subtree(parser, a_children[idx], 0))
        bucket = b_by_render.get(key)
        if bucket:
            reordered_a.add(idx)
            reordered_b.add(bucket.pop(0))
    return reordered_a, reordered_b


def _diff_children_unordered(
    parser: VendorParser,
    node_a: ConfigNode,
    node_b: ConfigNode,
    depth: int,
    *,
    hide_equal: bool,
    path: tuple[str, ...],
) -> Iterator[_Event]:
    """Set-like matching keyed on ``line``, interleaved by position.

    Within a parent, the IR guarantees each child has a unique ``line`` (same-named
    siblings are merged on parse), so we can pair children by key. Matching stays
    order-insensitive (pure reorders produce no diff), but the display walks ``a`` and
    splices in ``b``-only children at their natural position — i.e. before the next
    matched anchor — so ``-`` / ``+`` lines surface near each other instead of clumping
    at the start and end.

    Additionally, A-only and B-only *leaves* that look like the same setting with a
    changed value (high :class:`difflib.SequenceMatcher` ratio) are paired so the ``+``
    is emitted immediately after its ``-``.
    """

    a_children = node_a.children
    b_children = node_b.children
    b_by_line = {child.line: child for child in b_children}
    common = {child.line for child in a_children} & set(b_by_line)
    b_match_index = {
        child.line: idx for idx, child in enumerate(b_children) if child.line in common
    }

    a_only_leaves = [
        (idx, child)
        for idx, child in enumerate(a_children)
        if child.line not in common and child.is_leaf
    ]
    b_only_leaves = [
        (idx, child)
        for idx, child in enumerate(b_children)
        if child.line not in common and child.is_leaf
    ]
    a_index_to_b_node, paired_b_positions = _pair_changed_leaves(a_only_leaves, b_only_leaves)

    b_pointer = 0
    for idx, child_a in enumerate(a_children):
        if child_a.line not in common:
            yield from _emit_one_side(parser, child_a, depth, "-")
            partner = a_index_to_b_node.get(idx)
            if partner is not None:
                yield from _emit_one_side(parser, partner, depth, "+")
            continue
        b_pos = b_match_index[child_a.line]
        if b_pos >= b_pointer:
            for k in range(b_pointer, b_pos):
                child_b = b_children[k]
                if child_b.line not in common and k not in paired_b_positions:
                    yield from _emit_one_side(parser, child_b, depth, "+")
            b_pointer = b_pos + 1
        yield from _equal_pair(parser, child_a, b_by_line[child_a.line], depth, hide_equal, path)

    for k in range(b_pointer, len(b_children)):
        child_b = b_children[k]
        if child_b.line not in common and k not in paired_b_positions:
            yield from _emit_one_side(parser, child_b, depth, "+")


def _leading_token(line: str) -> str:
    """Return the first whitespace-delimited token of *line* (its command word)."""

    parts = line.split(maxsplit=1)
    return parts[0] if parts else ""


def _pair_changed_leaves(
    a_only: list[tuple[int, ConfigNode]],
    b_only: list[tuple[int, ConfigNode]],
) -> tuple[dict[int, ConfigNode], set[int]]:
    """Greedily pair A-only / B-only leaves that differ only in value.

    A pair is a candidate when either the raw-line ``difflib`` ratio clears
    :data:`_SIMILARITY_CUTOFF`, or the two leaves share the same leading command token
    and the ratio clears the looser :data:`_TOKEN_SHARE_CUTOFF`. The latter rescues short
    settings with a large value change (``vlan 1`` → ``vlan 1,100,200,300``) whose char
    ratio dips below the primary cutoff. Pairs are chosen highest-ratio first and each side
    is used at most once, so genuine high-ratio matches win before the looser fallbacks.

    Returns ``(a_child_index -> paired b node, set of paired b child indices)`` so the
    caller can emit the ``+`` next to its ``-`` and suppress it elsewhere.
    """

    candidates: list[tuple[float, int, int]] = []
    for ai, (_, a_node) in enumerate(a_only):
        for bi, (_, b_node) in enumerate(b_only):
            ratio = SequenceMatcher(None, a_node.line, b_node.line).ratio()
            shares_token = _leading_token(a_node.line) == _leading_token(b_node.line)
            if ratio >= _SIMILARITY_CUTOFF or (shares_token and ratio >= _TOKEN_SHARE_CUTOFF):
                candidates.append((ratio, ai, bi))
    candidates.sort(key=lambda t: t[0], reverse=True)

    used_a: set[int] = set()
    used_b: set[int] = set()
    a_index_to_b_node: dict[int, ConfigNode] = {}
    paired_b_positions: set[int] = set()
    for _, ai, bi in candidates:
        if ai in used_a or bi in used_b:
            continue
        used_a.add(ai)
        used_b.add(bi)
        a_index_to_b_node[a_only[ai][0]] = b_only[bi][1]
        paired_b_positions.add(b_only[bi][0])
    return a_index_to_b_node, paired_b_positions


def _equal_pair(
    parser: VendorParser,
    child_a: ConfigNode,
    child_b: ConfigNode,
    depth: int,
    hide_equal: bool,
    path: tuple[str, ...],
) -> Iterator[_Event]:
    a_is_section = not child_a.is_leaf
    b_is_section = not child_b.is_leaf

    if not a_is_section and not b_is_section:
        # Equal leaf at this level. Suppress in the compact view, show as context in ndiff.
        if not hide_equal:
            yield _Event(" ", parser.render_leaf(child_a, depth))
        return

    if a_is_section != b_is_section:
        leaf_node = child_b if a_is_section else child_a
        section_node = child_a if a_is_section else child_b
        if not _leaf_section_render_equivalent(parser, leaf_node, section_node, depth):
            # A leaf that genuinely became a section (e.g. Junos ``foo;`` → ``foo { ... }``).
            yield from _emit_one_side(parser, child_a, depth, "-")
            yield from _emit_one_side(parser, child_b, depth, "+")
            return
        # Indent-based vendors: the "leaf" is just an empty section with the same header,
        # so fall through and diff their children (the empty side yields all ``-``/``+``).

    # Both are sections with matching headers. Diff their children; only surface the section
    # header if any descendant differs (compact mode) or always (ndiff).
    inner = list(
        _diff_children(
            parser,
            child_a,
            child_b,
            depth + 1,
            hide_equal=hide_equal,
            path=(*path, child_a.line),
        )
    )
    has_change = any(ev.op != " " for ev in inner)

    if not has_change and hide_equal:
        return

    yield _Event(" ", parser.render_open(child_a, depth))
    yield from inner
    close = parser.render_close(child_a, depth)
    if close is not None:
        yield _Event(" ", close)


def _leaf_section_render_equivalent(
    parser: VendorParser,
    leaf_node: ConfigNode,
    section_node: ConfigNode,
    depth: int,
) -> bool:
    """Whether promoting *leaf_node* to an empty section is render-transparent.

    True for indent-based vendors (Cisco/NX-OS), where ``render_leaf == render_open`` and
    there is no closing line, so an empty ``interface eth1`` and a populated one share the
    same header. False for brace/terminator vendors (Junos hierarchical), where a leaf
    (``foo;``) is structurally distinct from a section (``foo { ... }``).
    """

    return parser.render_close(section_node, depth) is None and parser.render_leaf(
        leaf_node, depth
    ) == parser.render_open(section_node, depth)


def _emit_one_side(
    parser: VendorParser,
    node: ConfigNode,
    depth: int,
    op: str,
) -> Iterator[_Event]:
    for line in render_subtree(parser, node, depth):
        yield _Event(op, line)
