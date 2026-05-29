"""Command-line interface — ``diffnc FILE_A FILE_B``.

Exit codes follow :manpage:`diff(1)`:

* ``0`` — inputs are equivalent (no diff output).
* ``1`` — inputs differ.
* ``2`` — an error occurred (parse failure, vendor mismatch, missing file, ...).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from diffnc import __version__
from diffnc.diff import ndiff, unified_diff
from diffnc.errors import DiffncError
from diffnc.reconcile import reconcile

_GREEN = "\x1b[32m"
_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_RESET = "\x1b[0m"


def main(argv: list[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    try:
        text_a = _read_file(args.file_a)
        text_b = _read_file(args.file_b)
    except OSError as exc:
        print(f"diffnc: {exc}", file=sys.stderr)
        return 2

    try:
        if args.mode == "ndiff":
            lines: Iterable[str] = ndiff(text_a, text_b, lineterm="\n", vendor=args.vendor)
        elif args.mode == "reconcile":
            lines = (f"{line}\n" for line in reconcile(text_a, text_b, vendor=args.vendor))
        else:
            lines = unified_diff(
                text_a,
                text_b,
                fromfile=str(args.file_a),
                tofile=str(args.file_b),
                lineterm="\n",
                vendor=args.vendor,
            )
        materialised = list(lines)
    except DiffncError as exc:
        print(f"diffnc: {exc}", file=sys.stderr)
        return 2

    if not materialised:
        return 0

    use_color = _should_colorize(args.color)
    for line in materialised:
        sys.stdout.write(_colorize(line, use_color))

    return 1


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diffnc",
        description="Structural diff for network device configurations.",
    )
    parser.add_argument("file_a", type=Path, help="left-hand configuration file")
    parser.add_argument("file_b", type=Path, help="right-hand configuration file")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-u",
        "--unified",
        dest="mode",
        action="store_const",
        const="unified",
        help="emit a compact, structure-aware unified diff (default)",
    )
    mode_group.add_argument(
        "-n",
        "--ndiff",
        dest="mode",
        action="store_const",
        const="ndiff",
        help="emit a verbose diff showing every line",
    )
    mode_group.add_argument(
        "-r",
        "--reconcile",
        dest="mode",
        action="store_const",
        const="reconcile",
        help="emit config-mode commands that transform FILE_A into FILE_B",
    )
    parser.set_defaults(mode="unified")

    parser.add_argument(
        "--vendor",
        choices=["junos", "junos_set", "nxos", "ios", "iosxe", "iosxr", "eos"],
        default=None,
        help="skip auto-detection and force a vendor",
    )
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="colorise +/- lines (default: auto, based on terminal)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _should_colorize(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty()


def _colorize(line: str, use_color: bool) -> str:
    if not use_color:
        return line
    if line.startswith("+") and not line.startswith("+++"):
        return f"{_GREEN}{line}{_RESET}"
    if line.startswith("-") and not line.startswith("---"):
        return f"{_RED}{line}{_RESET}"
    if line.startswith("!"):
        return f"{_YELLOW}{line}{_RESET}"
    return line
