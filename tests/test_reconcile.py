from __future__ import annotations

from pathlib import Path

import pytest

from diffnc import VendorMismatchError, reconcile

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# Cisco-like (nxos as the representative; all 5 share CiscoLikeParser)
# ---------------------------------------------------------------------------


def test_nxos_leaf_add() -> None:
    a = "interface eth1\n  description foo\n"
    b = "interface eth1\n  description foo\n  ip address 1.1.1.1/24\n"
    assert list(reconcile(a, b, vendor="nxos")) == [
        "interface eth1",
        "ip address 1.1.1.1/24",
    ]


def test_nxos_leaf_delete_inverts_no_prefix() -> None:
    a = "interface eth1\n  description foo\n"
    b = "interface eth1\n"
    # B's `interface eth1` parses as a leaf; the mismatch falls through to a
    # whole-section replace.
    out = list(reconcile(a, b, vendor="nxos"))
    assert out == ["no interface eth1", "interface eth1"]


def test_nxos_delete_plain_leaf_negates_with_no() -> None:
    a = "interface eth1\n  description foo\n  no shutdown\n"
    b = "interface eth1\n  no shutdown\n"
    assert list(reconcile(a, b, vendor="nxos")) == [
        "interface eth1",
        "no description foo",
    ]


def test_nxos_delete_no_prefixed_leaf_drops_no() -> None:
    """Deleting ``no shutdown`` means going back to the implicit ``shutdown`` state."""

    a = "interface eth1\n  description foo\n  no shutdown\n"
    b = "interface eth1\n  description foo\n"
    assert list(reconcile(a, b, vendor="nxos")) == [
        "interface eth1",
        "shutdown",
    ]


def test_nxos_add_whole_section_walks_subtree() -> None:
    a = "hostname switch-a\n"
    b = "hostname switch-a\ninterface eth2\n  description new\n  no shutdown\n"
    assert list(reconcile(a, b, vendor="nxos")) == [
        "interface eth2",
        "description new",
        "no shutdown",
    ]


def test_nxos_delete_whole_section_uses_no_prefix() -> None:
    a = "hostname switch-a\ninterface eth1\n  description foo\n"
    b = "hostname switch-a\n"
    assert list(reconcile(a, b, vendor="nxos")) == ["no interface eth1"]


def test_nxos_acl_change_recreates_section() -> None:
    a = "ip access-list extended FOO\n  10 permit ip any any\n"
    b = "ip access-list extended FOO\n  10 permit ip any any\n  20 deny ip any any\n"
    assert list(reconcile(a, b, vendor="nxos")) == [
        "no ip access-list extended FOO",
        "ip access-list extended FOO",
        "10 permit ip any any",
        "20 deny ip any any",
    ]


def test_nxos_section_header_emitted_once_for_multiple_changes() -> None:
    a = "interface eth1\n  description old\n  mtu 1500\n"
    b = "interface eth1\n  description new\n  mtu 9000\n"
    # Section header should only appear once even though there are two changes inside.
    out = list(reconcile(a, b, vendor="nxos"))
    assert out.count("interface eth1") == 1


def test_nxos_identical_inputs_produce_no_output() -> None:
    config = _read("nxos_a.conf")
    assert list(reconcile(config, config)) == []


def test_nxos_fixture_end_to_end() -> None:
    a = _read("nxos_a.conf")
    b = _read("nxos_b.conf")
    out = list(reconcile(a, b))
    # B adds `feature ospf` at top level and changes the eth1 description.
    assert "feature ospf" in out
    assert "interface Ethernet1/1" in out
    assert "no description uplink" in out
    assert "description uplink-to-spine" in out


def test_ios_vendor_uses_same_logic() -> None:
    a = "interface GigabitEthernet0/0\n description old\n"
    b = "interface GigabitEthernet0/0\n description new\n"
    assert list(reconcile(a, b, vendor="ios")) == [
        "interface GigabitEthernet0/0",
        "no description old",
        "description new",
    ]


# ---------------------------------------------------------------------------
# Junos hierarchical
# ---------------------------------------------------------------------------


def test_junos_leaf_add_emits_set_with_full_path() -> None:
    a = "system {\n    host-name router-a;\n}\n"
    b = (
        "system {\n"
        "    host-name router-a;\n"
        "    login {\n"
        "        user alice {\n"
        "            uid 1001;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert list(reconcile(a, b, vendor="junos")) == [
        "set system login user alice uid 1001",
    ]


def test_junos_leaf_delete_emits_delete_with_full_path() -> None:
    a = "system {\n    host-name router-a;\n    domain-name example.com;\n}\n"
    b = "system {\n    host-name router-a;\n}\n"
    assert list(reconcile(a, b, vendor="junos")) == [
        "delete system domain-name example.com",
    ]


def test_junos_section_delete_collapses_to_single_delete() -> None:
    a = (
        "system {\n"
        "    host-name router-a;\n"
        "    login {\n"
        "        user alice {\n"
        "            uid 1001;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    b = "system {\n    host-name router-a;\n}\n"
    assert list(reconcile(a, b, vendor="junos")) == ["delete system login"]


def test_junos_change_emits_delete_and_set_pair() -> None:
    a = "system {\n    host-name router-a;\n}\n"
    b = "system {\n    host-name router-b;\n}\n"
    out = list(reconcile(a, b, vendor="junos"))
    assert "delete system host-name router-a" in out
    assert "set system host-name router-b" in out


def test_junos_firewall_filter_recreates_on_change() -> None:
    a = (
        "firewall {\n"
        "    filter MYFILTER {\n"
        "        term T1 {\n"
        "            then accept;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    b = (
        "firewall {\n"
        "    filter MYFILTER {\n"
        "        term T1 {\n"
        "            then discard;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    out = list(reconcile(a, b, vendor="junos"))
    assert out[0] == "delete firewall filter MYFILTER"
    assert "set firewall filter MYFILTER term T1 then discard" in out


def test_junos_fixture_end_to_end() -> None:
    a = _read("junos_a.conf")
    b = _read("junos_b.conf")
    out = list(reconcile(a, b))
    assert "delete system host-name router-a" in out
    assert "set system host-name router-b" in out
    assert "set interfaces ge-0/0/1 unit 0" in out


# ---------------------------------------------------------------------------
# Junos set form
# ---------------------------------------------------------------------------


def test_junos_set_add_yields_line_verbatim() -> None:
    a = "set system host-name router-a\n"
    b = "set system host-name router-a\nset protocols bgp group external type external\n"
    assert list(reconcile(a, b, vendor="junos_set")) == [
        "set protocols bgp group external type external",
    ]


def test_junos_set_delete_strips_set_prefix() -> None:
    a = "set system host-name router-a\nset system domain-name example.com\n"
    b = "set system host-name router-a\n"
    assert list(reconcile(a, b, vendor="junos_set")) == [
        "delete system domain-name example.com",
    ]


def test_junos_set_change_pairs_delete_and_set() -> None:
    a = "set system host-name router-a\n"
    b = "set system host-name router-b\n"
    out = list(reconcile(a, b, vendor="junos_set"))
    assert out == [
        "delete system host-name router-a",
        "set system host-name router-b",
    ]


def test_junos_set_deactivate_add() -> None:
    a = "set interfaces ge-0/0/0 unit 0\n"
    b = "set interfaces ge-0/0/0 unit 0\ndeactivate interfaces ge-0/0/0\n"
    assert list(reconcile(a, b, vendor="junos_set")) == [
        "deactivate interfaces ge-0/0/0",
    ]


def test_junos_set_deactivate_delete_strips_prefix() -> None:
    a = "set interfaces ge-0/0/0 unit 0\ndeactivate interfaces ge-0/0/0\n"
    b = "set interfaces ge-0/0/0 unit 0\n"
    assert list(reconcile(a, b, vendor="junos_set")) == [
        "delete interfaces ge-0/0/0",
    ]


def test_junos_set_fixture_end_to_end() -> None:
    a = _read("junos_set_a.conf")
    b = _read("junos_set_b.conf")
    out = list(reconcile(a, b))
    assert "delete system host-name router-a" in out
    assert "set system host-name router-b" in out
    assert "set protocols bgp group external type external" in out


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_no_output_all_vendors() -> None:
    a = "set system host-name router-a\n"
    assert list(reconcile(a, a)) == []


def test_vendor_mismatch_raises() -> None:
    with pytest.raises(VendorMismatchError):
        list(reconcile(_read("nxos_a.conf"), _read("junos_set_a.conf")))


def test_iterable_input_is_accepted() -> None:
    a_lines = ["interface eth1", "  description old"]
    b_lines = ["interface eth1", "  description new"]
    out = list(reconcile(a_lines, b_lines, vendor="nxos"))
    assert out == ["interface eth1", "no description old", "description new"]


# ---------------------------------------------------------------------------
# Empty-side inputs
# ---------------------------------------------------------------------------


def test_reconcile_to_empty_deletes_everything() -> None:
    a = "set interface ge-0/0/0 unit 0 family inet dhcp\n"
    assert list(reconcile(a, "")) == ["delete interface ge-0/0/0 unit 0 family inet dhcp"]


def test_reconcile_from_empty_adds_everything() -> None:
    b = "set interface ge-0/0/0 unit 0 family inet dhcp\nset system host-name r1\n"
    assert list(reconcile("", b)) == [
        "set interface ge-0/0/0 unit 0 family inet dhcp",
        "set system host-name r1",
    ]


def test_reconcile_both_empty_produces_no_output() -> None:
    assert list(reconcile("", "! comment only\n")) == []
