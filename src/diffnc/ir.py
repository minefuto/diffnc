"""Internal representation of a network configuration.

A configuration is modelled as a tree of :class:`ConfigNode`. Each node carries one logical
command line plus its (ordered) children. The whole document is wrapped in :class:`ConfigTree`
which records the originating vendor so that the diff engine can later format output back
in the input's flavour.

The constructors in this module also implement the normalisation rules described in the plan:

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

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def add_child(self, child: ConfigNode) -> ConfigNode:
        """Append *child* (or fold it into an existing same-named sibling) and return the
        node that now represents it in the tree.

        Indent-based vendors (e.g. NX-OS) can't tell at insertion time whether a line will
        end up being a leaf or a section, so the merge rule is intentionally simple: any
        sibling with the same ``line`` absorbs the new node's children. This collapses
        repeated blocks (``interface eth1`` appearing twice) into one.
        """

        for sibling in self.children:
            if sibling.line == child.line:
                for grandchild in child.children:
                    sibling.add_child(grandchild)
                return sibling
        self.children.append(child)
        return child


@dataclass
class ConfigTree:
    """A parsed configuration document."""

    root: ConfigNode
    vendor: str

    @classmethod
    def empty(cls, vendor: str) -> ConfigTree:
        return cls(root=ConfigNode(line=""), vendor=vendor)
