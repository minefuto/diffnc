from __future__ import annotations

from pathlib import Path

import pytest

from diffnc.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_exits_0_for_identical(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(FIXTURES / "nxos_a.conf"), str(FIXTURES / "nxos_a.conf"), "--color", "never"])
    assert code == 0
    assert capsys.readouterr().out == ""


def test_cli_exits_1_for_diff(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            str(FIXTURES / "nxos_a.conf"),
            str(FIXTURES / "nxos_b.conf"),
            "--color",
            "never",
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "--- " in out
    assert "+++ " in out
    assert "+feature ospf" in out


def test_cli_exits_2_for_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(FIXTURES / "does_not_exist.conf"), str(FIXTURES / "nxos_a.conf")])
    assert code == 2
    err = capsys.readouterr().err
    assert "diffnc:" in err


def test_cli_exits_2_for_vendor_mismatch(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            str(FIXTURES / "nxos_a.conf"),
            str(FIXTURES / "junos_set_a.conf"),
            "--color",
            "never",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "different vendors" in err


def test_cli_ndiff_mode(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            str(FIXTURES / "nxos_a.conf"),
            str(FIXTURES / "nxos_b.conf"),
            "-n",
            "--color",
            "never",
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    # ndiff shows every line, including unchanged ones, with 2-char markers.
    assert "  hostname switch-a\n" in out
    assert "+ feature ospf\n" in out


def test_cli_vendor_override(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    a = tmp_path / "a.conf"
    b = tmp_path / "b.conf"
    a.write_text("feature lldp\n")
    b.write_text("feature bgp\n")
    code = main([str(a), str(b), "--vendor", "nxos", "--color", "never"])
    assert code == 1
    out = capsys.readouterr().out
    assert "-feature lldp" in out
    assert "+feature bgp" in out


def test_cli_reconcile_mode(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            str(FIXTURES / "nxos_a.conf"),
            str(FIXTURES / "nxos_b.conf"),
            "-r",
            "--color",
            "never",
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    # Reconcile mode emits no `--- ` / `+++ ` headers — just bare CLI lines.
    assert "--- " not in out
    assert "+++ " not in out
    assert "feature ospf\n" in out
    assert "interface Ethernet1/1\n" in out
    assert "no description uplink\n" in out
    assert "description uplink-to-spine\n" in out


def test_cli_reconcile_mode_identical_files_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            str(FIXTURES / "nxos_a.conf"),
            str(FIXTURES / "nxos_a.conf"),
            "-r",
            "--color",
            "never",
        ]
    )
    assert code == 0
    assert capsys.readouterr().out == ""


def test_cli_reconcile_and_unified_are_mutually_exclusive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                str(FIXTURES / "nxos_a.conf"),
                str(FIXTURES / "nxos_b.conf"),
                "-u",
                "-r",
            ]
        )


def test_cli_reorder_uses_bang_marker(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """A pure reorder in an order-sensitive parent surfaces as ``!`` lines, not ``-/+``."""

    a = tmp_path / "a.conf"
    b = tmp_path / "b.conf"
    a.write_text("ip access-list FOO\n  10 permit ip any any\n  20 deny ip any any\n")
    b.write_text("ip access-list FOO\n  20 deny ip any any\n  10 permit ip any any\n")
    code = main([str(a), str(b), "--vendor", "nxos", "--color", "never"])
    assert code == 1
    out = capsys.readouterr().out
    body = [
        line
        for line in out.splitlines()
        if not line.startswith("---") and not line.startswith("+++")
    ]
    # At least one ACE surfaces with the `!` marker — SequenceMatcher anchors the
    # other side as the "equal" block (which gets suppressed in unified mode).
    assert any(line.startswith("!") for line in body)
    assert not any(line.startswith("-") for line in body)
    assert not any(line.startswith("+") for line in body)
