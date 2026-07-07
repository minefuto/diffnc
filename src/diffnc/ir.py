"""Internal representation of a network configuration.

A configuration is modelled as a tree of :class:`ConfigNode`. Each node carries one logical
command line plus its (ordered) children. The whole document is wrapped in :class:`ConfigTree`
which records the originating vendor so that the diff engine can later format output back
in the input's flavour.

The constructors in this module also implement the following normalisation rules:

* Same-name non-leaf siblings get merged (their children concatenate).
* Duplicate leaf siblings collapse to one occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConfigNode:
    """A single configuration statement, optionally with nested children."""

    line: str
    children: list[ConfigNode] = field(default_factory=list)
    # line -> child node, kept in sync with ``children`` so same-name lookups stay O(1).
    # Excluded from equality/repr: a node's identity is its line plus its children.
    _index: dict[str, ConfigNode] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        # Children supplied at construction (e.g. in tests) bypass ``add_child``; index them
        # so lookups and merges behave identically to a tree built incrementally.
        if self.children:
            self._index = {child.line: child for child in self.children}

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def add_child(self, child: ConfigNode) -> ConfigNode:
        """Append *child* (or fold it into an existing same-named sibling) and return the
        node that now represents it in the tree.

        Indent-based vendors (e.g. NX-OS) can't tell at insertion time whether a line will
        end up being a leaf or a section, so the merge rule is intentionally simple: any
        sibling with the same ``line`` absorbs the new node's children. This collapses
        repeated blocks (``interface eth1`` appearing twice) into one. The ``_index`` map
        makes the same-name check O(1) instead of scanning every sibling.
        """

        existing = self._index.get(child.line)
        if existing is not None:
            for grandchild in child.children:
                existing.add_child(grandchild)
            return existing
        self.children.append(child)
        self._index[child.line] = child
        return child

    def child_by_line(self, line: str) -> ConfigNode | None:
        """Return the child whose ``line`` equals *line*, or ``None`` — O(1) via the index."""

        return self._index.get(line)

    def relabel_child(self, child: ConfigNode, new_line: str) -> None:
        """Rename an existing *child* to *new_line* in place, keeping the index in sync.

        Used by toggle collapsing (``X`` ↔ ``no X``, ``activate`` ↔ ``deactivate``) where the
        last occurrence wins but the child's position must be preserved.
        """

        self._index.pop(child.line, None)
        child.line = new_line
        self._index[new_line] = child

    def retain_children(self, surviving: list[ConfigNode]) -> None:
        """Replace the child list (e.g. after a ``default`` / ``delete`` purge) and rebuild
        the index from it."""

        self.children = surviving
        self._index = {child.line: child for child in surviving}


@dataclass
class ConfigTree:
    """A parsed configuration document."""

    root: ConfigNode
    vendor: str

    @classmethod
    def empty(cls, vendor: str) -> ConfigTree:
        return cls(root=ConfigNode(line=""), vendor=vendor)
