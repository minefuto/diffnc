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

from typing import Protocol, runtime_checkable

from diffnc.ir import ConfigNode, ConfigTree


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


def is_order_sensitive_for(parser: VendorParser, path: tuple[str, ...]) -> bool:
    """Resolve :meth:`VendorParser.is_order_sensitive` with a safe default.

    Older / third-party parsers may not implement the method; treat such parents as
    order-insensitive so the diff engine can fall back to multiset matching.
    """

    impl = getattr(parser, "is_order_sensitive", None)
    if impl is None:
        return False
    return bool(impl(path))


def render_subtree(
    parser: VendorParser,
    node: ConfigNode,
    depth: int,
) -> list[str]:
    """Render *node* and all its descendants as display lines."""

    if node.is_leaf:
        return [parser.render_leaf(node, depth)]

    lines = [parser.render_open(node, depth)]
    for child in node.children:
        lines.extend(render_subtree(parser, child, depth + 1))
    close = parser.render_close(node, depth)
    if close is not None:
        lines.append(close)
    return lines
