"""Structural diff for network device configurations.

Public API mirrors :mod:`difflib`:

* :func:`unified_diff` — compact, change-focused diff with section context.
* :func:`ndiff` — every-line diff with ``- ``/``+ ``/``  `` markers.
* :func:`reconcile` — config-mode commands that transform *A* into *B*.
* :func:`detect_vendor` — auto-detect the vendor for a config blob.

Errors are exposed via :class:`DiffncError` and its subclasses.
"""

from __future__ import annotations

from importlib.metadata import version

from diffnc.detect import detect_vendor
from diffnc.diff import ndiff, unified_diff
from diffnc.errors import (
    DiffncError,
    ParseError,
    VendorMismatchError,
)
from diffnc.reconcile import reconcile

__all__ = [
    "DiffncError",
    "ParseError",
    "VendorMismatchError",
    "__version__",
    "detect_vendor",
    "ndiff",
    "reconcile",
    "unified_diff",
]

__version__ = version("diffnc")
