from __future__ import annotations

from pathlib import Path

import pytest

from diffnc import (
    VendorMismatchError,
    ndiff,
    unified_diff,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_example_scenario_unified() -> None:
    """The README example: duplicate ``interface eth1`` blocks should be merged."""

    a = "interface eth1\n  no shut\n  ip address 1.1.1.1/24\n  stp\n"
    b = "interface eth1\n   shut\n   ip address 1.1.1.1/24\n\ninterface eth1\n  stp\n"
    output = "".join(unified_diff(a, b, lineterm="\n"))
    assert output == " interface eth1\n-  no shut\n+  shut\n"


def test_unified_default_lineterm_is_empty() -> None:
    """Library callers get bare lines by default; CLI opts into ``\\n`` explicitly."""

    a = "interface eth1\n  no shut\n"
    b = "interface eth1\n  shut\n"
    output = list(unified_diff(a, b))
    assert output == [" interface eth1", "-  no shut", "+  shut"]


def test_ndiff_default_lineterm_is_empty() -> None:
    a = "interface eth1\n  no shut\n"
    b = "interface eth1\n  shut\n"
    output = list(ndiff(a, b))
    assert output == ["  interface eth1", "-   no shut", "+   shut"]


def test_example_scenario_ndiff_shows_all_lines() -> None:
    a = "interface eth1\n  no shut\n  ip address 1.1.1.1/24\n  stp\n"
    b = "interface eth1\n   shut\n   ip address 1.1.1.1/24\n\ninterface eth1\n  stp\n"
    output = "".join(ndiff(a, b, lineterm="\n"))
    # Order-insensitive matching: ``no shut`` is delete (only in A), ``shut`` is insert
    # (only in B). Both sit before the matched ``ip address`` anchor in their respective
    # inputs, so the insert is spliced in next to the delete rather than dangling at the
    # end of the section.
    assert output == (
        "  interface eth1\n-   no shut\n+   shut\n    ip address 1.1.1.1/24\n    stp\n"
    )


def test_identical_inputs_produce_no_output() -> None:
    config = _read("nxos_a.conf")
    assert list(unified_diff(config, config)) == []


def test_unified_includes_file_headers_when_provided() -> None:
    a = _read("nxos_a.conf")
    b = _read("nxos_b.conf")
    out = list(unified_diff(a, b, fromfile="a.conf", tofile="b.conf", lineterm="\n"))
    assert out[0] == "--- a.conf\n"
    assert out[1] == "+++ b.conf\n"


def test_nxos_diff_changed_description() -> None:
    a = _read("nxos_a.conf")
    b = _read("nxos_b.conf")
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "+feature ospf\n" in out
    assert "-  description uplink\n" in out
    assert "+  description uplink-to-spine\n" in out
    assert " interface Ethernet1/1\n" in out
    # Unchanged interface should not appear at all.
    assert "interface Ethernet1/2" not in out


def test_junos_set_diff_includes_added_and_changed() -> None:
    a = _read("junos_set_a.conf")
    b = _read("junos_set_b.conf")
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "-set system host-name router-a\n" in out
    assert "+set system host-name router-b\n" in out
    assert "+set protocols bgp group external type external\n" in out


def test_junos_hierarchical_emits_braces_in_added_block() -> None:
    a = _read("junos_a.conf")
    b = _read("junos_b.conf")
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "-    host-name router-a;\n" in out
    assert "+    host-name router-b;\n" in out
    assert "+    ge-0/0/1 {\n" in out
    assert "+        unit 0;\n" in out
    assert "+    }\n" in out


def test_vendor_mismatch_raises() -> None:
    nxos = _read("nxos_a.conf")
    junos = _read("junos_set_a.conf")
    with pytest.raises(VendorMismatchError):
        list(unified_diff(nxos, junos))


def test_junos_set_vs_junos_hierarchical_raises_vendor_mismatch() -> None:
    with pytest.raises(VendorMismatchError):
        list(unified_diff(_read("junos_set_a.conf"), _read("junos_a.conf")))


def test_iterable_input_is_accepted() -> None:
    a_lines = ["interface eth1", "  no shut"]
    b_lines = ["interface eth1", "  shut"]
    out = "".join(unified_diff(a_lines, b_lines, lineterm="\n"))
    assert "-  no shut\n" in out
    assert "+  shut\n" in out


def test_vendor_override_skips_autodetect() -> None:
    # Pass `--vendor nxos` even though detection might choose otherwise.
    a = "feature lldp\n"
    b = "feature bgp\n"
    out = "".join(unified_diff(a, b, lineterm="\n", vendor="nxos"))
    assert "-feature lldp\n" in out
    assert "+feature bgp\n" in out


def test_junos_set_activate_deactivate_diff_as_distinct_lines() -> None:
    a = "set interfaces ge-0/0/0 unit 0\n"
    b = "deactivate interfaces ge-0/0/0 unit 0\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "-set interfaces ge-0/0/0 unit 0\n" in out
    assert "+deactivate interfaces ge-0/0/0 unit 0\n" in out


def test_junos_hier_inactive_section_identical_subtree_collapses() -> None:
    # Only the inactive state of the section changed; its subtree is identical, so the diff
    # collapses to a single ``!`` line with no braces instead of re-emitting the subtree.
    a = "interfaces {\n    ge-0/0/0 {\n        unit 0;\n    }\n}\n"
    b = "interfaces {\n    inactive: ge-0/0/0 {\n        unit 0;\n    }\n}\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert out == " interfaces {\n!    inactive: ge-0/0/0\n }\n"


def test_junos_hier_inactive_leaf_deactivated() -> None:
    a = "system {\n    host-name foo;\n}\n"
    b = "system {\n    inactive: host-name foo;\n}\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert out == " system {\n!    inactive: host-name foo;\n }\n"


def test_junos_hier_inactive_leaf_activated_shows_activate_marker() -> None:
    # Reactivation has no literal marker on the B line, so a synthetic ``activate:`` is shown.
    a = "system {\n    inactive: host-name foo;\n}\n"
    b = "system {\n    host-name foo;\n}\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert out == " system {\n!    activate: host-name foo;\n }\n"


def test_junos_hier_inactive_section_with_inner_change_expands() -> None:
    # ospf deactivated while the interface inside it is reactivated: the toggled section
    # header is marked ``!`` and expanded, with context lines around the inner toggle.
    a = (
        "protocols {\n    ospf {\n        area 0.0.0.0 {\n"
        "            inactive: interface ge-0/0/0.0;\n        }\n    }\n}\n"
    )
    b = (
        "protocols {\n    inactive: ospf {\n        area 0.0.0.0 {\n"
        "            interface ge-0/0/0.0;\n        }\n    }\n}\n"
    )
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert out == (
        " protocols {\n"
        "!    inactive: ospf {\n"
        "         area 0.0.0.0 {\n"
        "!            activate: interface ge-0/0/0.0;\n"
        "         }\n"
        "     }\n"
        " }\n"
    )


def test_junos_hier_inactive_with_real_subtree_change_still_diffs() -> None:
    # When the subtree genuinely differs as well, the section header toggle is marked ``!``
    # and the real leaf change still shows as ``-``/``+``.
    a = "interfaces {\n    ge-0/0/0 {\n        unit 0;\n    }\n}\n"
    b = "interfaces {\n    inactive: ge-0/0/0 {\n        unit 1;\n    }\n}\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert out == (
        " interfaces {\n!    inactive: ge-0/0/0 {\n-        unit 0;\n+        unit 1;\n     }\n }\n"
    )


def test_junos_set_delete_changes_effective_diff() -> None:
    a = (
        "set interfaces ge-0/0/0 unit 0 family inet address 192.168.1.1/24\n"
        "delete interfaces ge-0/0/0\n"
        "set interfaces ge-0/0/0 unit 0 family mpls\n"
    )
    b = (
        "set interfaces ge-0/0/0 unit 0 family inet address 192.168.1.1/24\n"
        "set interfaces ge-0/0/0 unit 0 family mpls\n"
    )
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "+set interfaces ge-0/0/0 unit 0 family inet address 192.168.1.1/24\n" in out
    assert "delete" not in out


def test_junos_set_user_example_three_state_toggle() -> None:
    a = (
        "set interface ge-0/0/0 unit 0 family inet address 192.168.1.1/24\n"
        "deactivate interface ge-0/0/0\n"
        "activate interface ge-0/0/0\n"
        "set interface ge-0/0/1 unit 0 family inet address 192.168.2.1/24\n"
        "activate interface ge-0/0/1\n"
    )
    b = (
        "set interface ge-0/0/0 unit 0 family inet address 192.168.1.1/24\n"
        "set interface ge-0/0/1 unit 0 family inet address 192.168.2.1/24\n"
        "deactivate interface ge-0/0/1\n"
    )
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "-activate interface ge-0/0/0\n" in out
    assert "-activate interface ge-0/0/1\n" in out
    assert "+deactivate interface ge-0/0/1\n" in out
    # `deactivate interface ge-0/0/0` was toggled away in A — must not appear.
    assert "deactivate interface ge-0/0/0" not in out


def test_nxos_shutdown_three_state_toggle_diff() -> None:
    a = "interface eth1\n  shutdown\n  no shutdown\n"
    b = "interface eth1\n  shutdown\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert " interface eth1\n" in out
    assert "-  no shutdown\n" in out
    assert "+  shutdown\n" in out
    # The intermediate `shutdown` toggle in A must not surface in the diff.
    assert out.count("shutdown") == 2


def test_ios_diff_changed_description() -> None:
    a = _read("ios_a.conf")
    b = _read("ios_b.conf")
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "- description uplink\n" in out
    assert "+ description uplink-to-spine\n" in out
    assert "+interface GigabitEthernet0/2\n" in out
    assert " interface GigabitEthernet0/0\n" in out
    # Unchanged interface should not appear at all.
    assert "interface GigabitEthernet0/1" not in out


def test_ios_shutdown_toggle_three_state_diff() -> None:
    a = "interface GigabitEthernet0/0\n shutdown\n no shutdown\n"
    b = "interface GigabitEthernet0/0\n shutdown\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert " interface GigabitEthernet0/0\n" in out
    assert "- no shutdown\n" in out
    assert "+ shutdown\n" in out


def test_nxos_default_changes_effective_diff() -> None:
    a = (
        "interface Ethernet1/1\n"
        "  description uplink\n"
        "  no shutdown\n"
        "default interface Ethernet1/1\n"
        "interface Ethernet1/1\n"
        "  description new-uplink\n"
    )
    b = "interface Ethernet1/1\n  description new-uplink\n"
    assert list(unified_diff(a, b)) == []


def test_nxos_emptied_section_header_shown_as_context() -> None:
    """An interface that loses all its children stays a context header, not a -/+ replace."""

    a = "interface Ethernet1/1\n  no shutdown\n"
    b = "interface Ethernet1/1\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert out == " interface Ethernet1/1\n-  no shutdown\n"
    assert "+interface Ethernet1/1" not in out


def test_nxos_changed_leaves_paired_adjacently() -> None:
    """Value changes of the same setting surface as adjacent -/+ pairs, not clumped."""

    a = "interface Ethernet1/2\n  ip address 192.168.1.1/24\n  ip ospf cost 50\n"
    b = "interface Ethernet1/2\n  ip address 192.168.1.2/24\n  ip ospf cost 100\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert out == (
        " interface Ethernet1/2\n"
        "-  ip address 192.168.1.1/24\n"
        "+  ip address 192.168.1.2/24\n"
        "-  ip ospf cost 50\n"
        "+  ip ospf cost 100\n"
    )


def test_short_leaf_value_change_paired_by_leading_token() -> None:
    """A short setting with a big value change pairs via its shared command word.

    ``vlan 1`` vs ``vlan 1,100,200,300`` scores below ``_SIMILARITY_CUTOFF`` on raw chars,
    but the shared ``vlan`` token rescues the pairing so the ``+`` sits next to its ``-``.
    """

    a = "vlan 1\nlicense smart transport smart\nlicense smart source-interface mgmt0\n"
    b = "vlan 1,100,200,300\nlicense smart source-interface mgmt0\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert out == ("-vlan 1\n+vlan 1,100,200,300\n-license smart transport smart\n")


def test_junos_leaf_to_section_still_renders_as_replace() -> None:
    """A Junos leaf becoming a populated section must not collapse into a context header."""

    a = "interfaces {\n    ge-0/0/0;\n}\n"
    b = "interfaces {\n    ge-0/0/0 {\n        unit 0;\n    }\n}\n"
    out = "".join(unified_diff(a, b, lineterm="\n"))
    assert "-    ge-0/0/0;\n" in out
    assert "+    ge-0/0/0 {\n" in out
    assert "+        unit 0;\n" in out
    assert "+    }\n" in out


# ---------------------------------------------------------------------------
# Empty-side inputs
# ---------------------------------------------------------------------------


def test_ndiff_against_empty_b_marks_all_as_deleted() -> None:
    a = "set interface ge-0/0/0 unit 0 family inet dhcp"
    assert list(ndiff(a, "")) == ["- set interface ge-0/0/0 unit 0 family inet dhcp"]


def test_unified_against_empty_a_marks_all_as_added() -> None:
    b = "set interface ge-0/0/0 unit 0 family inet dhcp\nset system host-name r1\n"
    assert list(unified_diff("", b)) == [
        "+set interface ge-0/0/0 unit 0 family inet dhcp",
        "+set system host-name r1",
    ]


def test_comment_only_side_treated_as_empty() -> None:
    a = "interface Ethernet1/1\n  no shutdown\n"
    b = "! header comment only\n"
    out = list(unified_diff(a, b))
    assert out == ["-interface Ethernet1/1", "-  no shutdown"]


def test_empty_side_emits_whole_subtree() -> None:
    a = "interface Ethernet1/1\n  description uplink\n  no shutdown\n"
    assert list(ndiff(a, "")) == [
        "- interface Ethernet1/1",
        "-   description uplink",
        "-   no shutdown",
    ]


def test_both_sides_empty_produce_no_output() -> None:
    assert list(unified_diff("", "")) == []
    assert list(ndiff("", "! comment\n")) == []
