from __future__ import annotations

import pytest

from diffnc.detect import detect_vendor
from diffnc.errors import ParseError


def test_detect_junos_set() -> None:
    text = "set system host-name foo\nset interfaces ge-0/0/0 unit 0\n"
    assert detect_vendor(text) == "junos_set"


def test_detect_junos_hierarchical() -> None:
    text = (
        "system {\n    host-name foo;\n}\ninterfaces {\n    ge-0/0/0 {\n        unit 0;\n    }\n}\n"
    )
    assert detect_vendor(text) == "junos"


def test_detect_nxos_short_interface() -> None:
    text = "interface eth1\n  no shutdown\n"
    assert detect_vendor(text) == "nxos"


def test_detect_nxos_full_interface() -> None:
    text = "hostname switch\nfeature lldp\ninterface Ethernet1/1\n  no shutdown\n"
    assert detect_vendor(text) == "nxos"


def test_detect_empty_raises() -> None:
    with pytest.raises(ParseError):
        detect_vendor("")


def test_detect_comment_only_raises() -> None:
    with pytest.raises(ParseError):
        detect_vendor("! just a banner\n")


def test_detect_ios_via_service_marker() -> None:
    text = (
        "service password-encryption\n"
        "hostname Router1\n"
        "interface GigabitEthernet0/0\n"
        " no shutdown\n"
    )
    assert detect_vendor(text) == "ios"


def test_detect_ios_via_interface_naming() -> None:
    text = "hostname Router1\ninterface GigabitEthernet0/0\n no shutdown\n"
    assert detect_vendor(text) == "ios"


def test_detect_ios_via_line_con() -> None:
    text = "hostname Router1\nline con 0\n logging synchronous\n"
    assert detect_vendor(text) == "ios"


def test_detect_ios_via_boot_marker() -> None:
    text = "hostname Router1\nboot-start-marker\nboot-end-marker\n"
    assert detect_vendor(text) == "ios"


def test_detect_nxos_wins_over_ios_when_feature_present() -> None:
    # `feature lldp` is a strong NX-OS signal that beats the IOS-style interface name.
    text = "feature lldp\ninterface GigabitEthernet0/0\n no shutdown\n"
    assert detect_vendor(text) == "nxos"


def test_detect_nxos_fallback_when_no_markers() -> None:
    text = "hostname plain\n"
    assert detect_vendor(text) == "nxos"


def test_detect_eos_via_vrf_instance() -> None:
    text = "hostname leaf\nvrf instance MGMT\nspanning-tree mode mstp\n"
    assert detect_vendor(text) == "eos"


def test_detect_eos_via_daemon_terminattr() -> None:
    text = "hostname leaf\ndaemon TerminAttr\n   no shutdown\n"
    assert detect_vendor(text) == "eos"


def test_detect_iosxr_via_bundle_ether() -> None:
    text = "hostname xr\ninterface Bundle-Ether1\n no shutdown\n"
    assert detect_vendor(text) == "iosxr"


def test_detect_iosxr_via_four_tuple_interface() -> None:
    text = "hostname xr\ninterface GigabitEthernet0/0/0/0\n no shutdown\n"
    assert detect_vendor(text) == "iosxr"


def test_detect_iosxe_via_platform_marker() -> None:
    text = (
        "service password-encryption\n"
        "hostname CSR\n"
        "platform punt-keepalive disable-kernel-core\n"
        "interface GigabitEthernet0/0/0\n"
        " no shutdown\n"
    )
    assert detect_vendor(text) == "iosxe"


def test_detect_iosxe_via_three_tuple_interface() -> None:
    text = "hostname CSR\ninterface GigabitEthernet0/0/0\n no shutdown\n"
    assert detect_vendor(text) == "iosxe"


def test_detect_eos_wins_over_nxos_when_vrf_instance_present() -> None:
    # `vrf instance` is EOS-specific (NX-OS uses `vrf context`), so EOS wins even when
    # an NX-OS-style `Ethernet1/1` interface is also present.
    text = "vrf instance MGMT\ninterface Ethernet1/1\n   no shutdown\n"
    assert detect_vendor(text) == "eos"


def test_detect_iosxr_wins_over_ios_when_bundle_ether_present() -> None:
    text = "service password-encryption\ninterface Bundle-Ether1\n no shutdown\n"
    assert detect_vendor(text) == "iosxr"


def test_detect_ios_still_wins_for_two_tuple_iface() -> None:
    # A classic IOS 2-tuple interface must not be misclassified as IOS-XE.
    text = "service password-encryption\ninterface GigabitEthernet0/0\n no shutdown\n"
    assert detect_vendor(text) == "ios"
