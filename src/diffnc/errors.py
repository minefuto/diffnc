"""Exception types used across diffnc."""

from __future__ import annotations


class DiffncError(Exception):
    """Base class for all diffnc errors."""


class ParseError(DiffncError):
    """Raised when a configuration cannot be parsed or its vendor cannot be detected."""


class VendorMismatchError(DiffncError):
    """Raised when two configurations belong to different vendors."""

    def __init__(self, vendor_a: str, vendor_b: str) -> None:
        super().__init__(
            f"cannot diff configurations from different vendors: {vendor_a!r} vs {vendor_b!r}"
        )
        self.vendor_a = vendor_a
        self.vendor_b = vendor_b
