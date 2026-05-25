"""Structural diff for network device configurations.

Public API mirrors :mod:`difflib`:

* :func:`unified_diff` — compact, change-focused diff with section context.
* :func:`ndiff` — every-line diff with ``- ``/``+ ``/``  `` markers.
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

__all__ = [
    "DiffncError",
    "ParseError",
    "VendorMismatchError",
    "__version__",
    "detect_vendor",
    "ndiff",
    "unified_diff",
]

__version__ = version("diffnc")
