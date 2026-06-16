"""Vendor parser contract.

A vendor plugin must expose:

* :meth:`parse` — turn raw text into a normalised :class:`~diffnc.ir.ConfigTree`.
* :meth:`format` — render a tree back to a list of display lines.
* :meth:`render_open`, :meth:`render_close`, :meth:`render_leaf` — emit a single line at
  the given indent depth. Used by the diff engine to splice context lines around changes
  without re-rendering full subtrees.
* :meth:`is_order_sensitive` (optional) — declare whether the children at a given
  configuration path are order-sensitive. When ``False`` (the default), the diff engine
  matches children as a multiset so that pure reordering does not produce a diff.

Adding a new vendor is a matter of writing a module that implements :class:`VendorParser`
and registering it via :mod:`diffnc.vendors`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from diffnc.ir import ConfigNode, ConfigTree

if TYPE_CHECKING:
    from diffnc.reconcile import ReconcileEvent


@runtime_checkable
class VendorParser(Protocol):
    name: str
    """Vendor identifier, e.g. ``"junos"`` or ``"nxos"``."""

    def parse(self, text: str) -> ConfigTree: ...
    def format(self, tree: ConfigTree) -> list[str]: ...
    def render_open(self, node: ConfigNode, depth: int) -> str: ...
    def render_close(self, node: ConfigNode, depth: int) -> str | None: ...
    def render_leaf(self, node: ConfigNode, depth: int) -> str: ...

    def is_order_sensitive(self, path: tuple[str, ...]) -> bool:
        """Return True if the children at ``path`` must be diffed positionally.

        ``path`` is the tuple of ``node.line`` values from root (exclusive) down to the
        parent whose children are being matched — e.g. ``("firewall", "filter FOO")``.
        Vendors that don't implement this fall back to order-insensitive matching.
        """
        ...

    def render_reconcile(self, events: Iterable[ReconcileEvent]) -> Iterator[str]:
        """Translate :mod:`diffnc.reconcile` events into config-mode command lines.

        Optional. Parsers that don't implement this can still be used for diffing; only
        :func:`diffnc.reconcile` will fail (with :class:`NotImplementedError`) when
        called against them.
        """
        ...


def is_order_sensitive_for(parser: VendorParser, path: tuple[str, ...]) -> bool:
    """Resolve :meth:`VendorParser.is_order_sensitive` with a safe default.

    Older / third-party parsers may not implement the method; treat such parents as
    order-insensitive so the diff engine can fall back to multiset matching.
    """

    impl = getattr(parser, "is_order_sensitive", None)
    if impl is None:
        return False
    return bool(impl(path))


def toggle_partners_for(parser: VendorParser, a: str, b: str) -> bool:
    """Resolve a parser's optional ``toggle_partners(a, b)`` method, defaulting to ``False``.

    A parser may expose ``toggle_partners`` to declare that leaf lines *a* and *b* are the two
    faces of one toggle setting — e.g. Cisco ``shutdown`` ↔ ``no shutdown``, or Junos
    ``activate X`` ↔ ``deactivate X``. When an A-only and a B-only leaf are partners the
    reconcile engine treats the change as a state transition: it suppresses the delete of the
    A side and emits only the B-side value. Parsers without the method never produce a toggle.
    """

    impl = getattr(parser, "toggle_partners", None)
    if impl is None:
        return False
    return bool(impl(a, b))


NO_TOGGLE_PARTNER = object()


def toggle_partner_of_for(parser: VendorParser, line: str) -> object:
    """Resolve the optional ``VendorParser.toggle_partner_of(line)`` fast path.

    A faster companion to ``toggle_partners``: instead of a symmetric predicate over a pair,
    a parser may expose ``toggle_partner_of`` to yield the one line that would pair with
    *line*. This returns that counterpart (``no X`` for ``X``, ``deactivate P`` for
    ``activate P``, …), ``None`` when *line* has no partner, or the sentinel
    :data:`NO_TOGGLE_PARTNER` when the parser doesn't implement the method — letting callers
    fall back to the generic :func:`toggle_partners_for` pairwise check. The single-partner
    form lets the reconcile engine resolve toggles with an O(1) set lookup instead of an
    O(n²) pairwise scan.
    """

    impl = getattr(parser, "toggle_partner_of", None)
    if impl is None:
        return NO_TOGGLE_PARTNER
    return impl(line)


def is_toggle_state_for(parser: VendorParser, line: str) -> bool:
    """Resolve a parser's optional ``is_toggle_state(line)`` method, defaulting to ``False``.

    A parser may expose ``is_toggle_state`` to mark *line* as a toggle state that must be
    excluded from value-change suppression. That suppression pairs A-only/B-only leaves
    differing only in a trailing token; toggle states (Cisco ``no X`` / ``shutdown``, Junos
    ``activate`` / ``deactivate``) must not be matched that way — a different trailing path
    token there means a different setting, not a new value.
    """

    impl = getattr(parser, "is_toggle_state", None)
    if impl is None:
        return False
    return bool(impl(line))


def base_identity_for(parser: VendorParser, line: str) -> str:
    """Return *line*'s matching key with any vendor toggle prefix stripped.

    A parser may expose an optional ``base_identity(line)`` method to fold a toggled node
    (e.g. Junos ``inactive: ospf``) onto its active form (``ospf``) so the diff/reconcile
    engines pair them as one node in two states. Defaults to the line itself, so vendors
    with no such prefix never produce a toggle.
    """

    impl = getattr(parser, "base_identity", None)
    if impl is None:
        return line
    return impl(line)


def render_toggle_line_for(
    parser: VendorParser, b_line: str, depth: int, *, became_active: bool, kind: str
) -> str:
    """Render a node whose only change is its (in)active state.

    Delegates to the parser's optional ``render_toggle_line`` method. Only ever invoked once
    :func:`base_identity_for` has detected a toggle, which a vendor only does when it also
    implements this method (Junos hierarchical). *kind* is ``"leaf"``, ``"section_open"`` or
    ``"section_collapsed"``.
    """

    impl = cast("Callable[..., str]", getattr(parser, "render_toggle_line", None))
    return impl(b_line, depth, became_active=became_active, kind=kind)


def leaf_section_render_equivalent(
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


def render_subtree(
    parser: VendorParser,
    node: ConfigNode,
    depth: int,
) -> list[str]:
    """Render *node* and all its descendants as display lines."""

    out: list[str] = []
    _render_into(parser, node, depth, out)
    return out


def _render_into(
    parser: VendorParser,
    node: ConfigNode,
    depth: int,
    out: list[str],
) -> None:
    """Append *node*'s rendered lines to *out*.

    Accumulating into a single list avoids the repeated allocate-and-copy that
    ``list.extend`` of per-child results incurs at every level of a deep subtree.
    """

    if node.is_leaf:
        out.append(parser.render_leaf(node, depth))
        return

    out.append(parser.render_open(node, depth))
    for child in node.children:
        _render_into(parser, child, depth + 1, out)
    close = parser.render_close(node, depth)
    if close is not None:
        out.append(close)
