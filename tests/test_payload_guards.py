"""Unit tests for payload filtering and semantic deployment guards."""

import asyncio
import os
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
NORNIR_MCP_DIR = REPO_ROOT / "nornir_mcp"
sys.path.insert(0, str(NORNIR_MCP_DIR))

_ORIGINAL_CWD = Path.cwd()
os.chdir(NORNIR_MCP_DIR)
try:
    import server_stdio as core
    from validation_models import (
        DataplaneCheckModel,
        DeviceBulkConfigModel,
        VXLANDeleteModel,
    )
finally:
    os.chdir(_ORIGINAL_CWD)


@pytest.fixture(autouse=True)
def clear_deferred_access_ports():
    core._deferred_access_ports.clear()
    yield
    core._deferred_access_ports.clear()


def test_spine_role_ignores_dataplane_payload():
    payload = DeviceBulkConfigModel(
        device_name="spine1-dc2",
        local_as=65000,
        vlans=[{"vlan_id": 10, "vni": 10010}],
        vxlan=[{"vni": 10010}],
        svis=[
            {
                "vlan_id": 10,
                "ip_address": "10.10.10.2/24",
                "virtual_ip": "10.10.10.1/24",
            }
        ],
    )

    commands, error = core._generate_bulk_config(payload, "eos", "spine")

    assert error is None
    assert commands == []


def test_incomplete_symmetric_irb_is_rejected_before_generation():
    payload = DeviceBulkConfigModel(
        device_name="leaf1-dc2",
        local_as=65101,
        vrfs=[{"vrf_name": "BLUE", "l3vni": 50010}],
        svis=[{"vlan_id": 10, "vrf": "BLUE", "ip_address": "10.10.10.2/24"}],
    )

    commands, error = core._generate_bulk_config(payload, "eos", "leaf")

    assert commands == []
    assert "Invalid Symmetric IRB payload" in error
    assert all(field in error for field in ("rd", "rt_import", "rt_export"))


def test_access_port_is_deferred_then_injected_with_its_vlan():
    phase1 = DeviceBulkConfigModel(
        device_name="leaf1-dc2",
        local_as=65101,
        interfaces=[
            {
                "interface_name": "Ethernet3",
                "switchport_mode": "access",
                "access_vlan": 10,
                "description": "client8-dc2",
            }
        ],
        bgp_neighbors=[
            {"neighbor_ip": "10.0.11.0", "local_as": 65101, "remote_as": 65000}
        ],
    )

    phase1_commands, error = core._generate_bulk_config(phase1, "eos", "leaf")
    assert error is None
    assert "switchport access vlan 10" not in "\n".join(phase1_commands)
    assert core._deferred_access_ports["leaf1-dc2"][0]["interface_name"] == "Ethernet3"

    phase3 = DeviceBulkConfigModel(
        device_name="leaf1-dc2",
        local_as=65101,
        vlans=[{"vlan_id": 10, "vni": 10010}],
    )
    phase3_commands, error = core._generate_bulk_config(phase3, "eos", "leaf")
    rendered = "\n".join(phase3_commands)

    assert error is None
    assert "interface Ethernet3" in rendered
    assert "switchport mode access" in rendered
    assert "switchport access vlan 10" in rendered


@pytest.mark.parametrize("mtu", [1500, 9000, 9214])
def test_explicit_interface_mtu_is_rendered(mtu):
    payload = DeviceBulkConfigModel(
        device_name="edge-a",
        interfaces=[
            {
                "interface_name": "Ethernet7",
                "ip_address": "192.0.2.0/31",
                "mtu": mtu,
            }
        ],
    )

    commands, error = core._generate_bulk_config(payload, "eos", "leaf")

    assert error is None
    assert f"  mtu {mtu}" in commands


def test_omitted_interface_mtu_is_not_invented():
    payload = DeviceBulkConfigModel(
        device_name="edge-a",
        interfaces=[
            {
                "interface_name": "Ethernet7",
                "ip_address": "192.0.2.0/31",
            }
        ],
    )

    commands, error = core._generate_bulk_config(payload, "eos", "leaf")

    assert error is None
    assert not any(command.strip().startswith("mtu ") for command in commands)


def test_svi_mtu_is_only_rendered_when_explicitly_requested():
    base_svi = {
        "vlan_id": 42,
        "ip_address": "192.0.2.2/24",
        "virtual_ip": "192.0.2.1/24",
        "anycast_mac": "00:1c:73:00:00:01",
    }
    omitted = DeviceBulkConfigModel(device_name="edge-a", svis=[base_svi])
    explicit = DeviceBulkConfigModel(
        device_name="edge-a", svis=[{**base_svi, "mtu": 9000}]
    )

    omitted_commands, omitted_error = core._generate_bulk_config(
        omitted, "eos", "leaf"
    )
    explicit_commands, explicit_error = core._generate_bulk_config(
        explicit, "eos", "leaf"
    )

    assert omitted_error is None
    assert explicit_error is None
    assert not any(
        command.strip().startswith("mtu ") for command in omitted_commands
    )
    assert "  mtu 9000" in explicit_commands


def test_svi_anycast_addressing_modes_are_explicit():
    non_vrf = DeviceBulkConfigModel(
        device_name="edge-a",
        svis=[
            {
                "vlan_id": 10,
                "ip_address": "192.0.2.2/24",
                "virtual_ip": "192.0.2.1/24",
            }
        ],
    )
    vrf = DeviceBulkConfigModel(
        device_name="edge-a",
        svis=[
            {
                "vlan_id": 20,
                "vrf": "TENANT_A",
                "virtual_ip": "198.51.100.1/24",
            }
        ],
    )

    non_vrf_commands, non_vrf_error = core._generate_bulk_config(
        non_vrf, "eos", "leaf"
    )
    vrf_commands, vrf_error = core._generate_bulk_config(vrf, "eos", "leaf")

    assert non_vrf_error is None
    assert "  ip address 192.0.2.2/24" in non_vrf_commands
    assert "  ip virtual-router address 192.0.2.1/24" in non_vrf_commands
    assert vrf_error is None
    assert "  vrf TENANT_A" in vrf_commands
    assert "  ip address virtual 198.51.100.1/24" in vrf_commands

    with pytest.raises(
        ValueError, match="VRF-bound anycast SVIs use virtual_ip only"
    ):
        DeviceBulkConfigModel(
            device_name="edge-a",
            svis=[
                {
                    "vlan_id": 20,
                    "vrf": "TENANT_A",
                    "ip_address": "198.51.100.2/24",
                    "virtual_ip": "198.51.100.1/24",
                }
            ],
        )


def test_vxlan_delete_rejects_ignored_local_as_without_full_cleanup():
    payload = VXLANDeleteModel(
        device_name="edge-a",
        vni=424242,
        vlan_id=42,
        local_as=64521,
        cleanup_vlan=False,
    )

    commands, error = core._generate_vxlan_delete_config(payload, "eos")

    assert commands == []
    assert "local_as is only used when cleanup_vlan=true" in error
    assert "mapping-only removal" in error


def evpn_service_payload(device_name, local_as, l2_rt, l3_rt=None):
    payload = {
        "device_name": device_name,
        "local_as": local_as,
        "vlans": [{"vlan_id": 42, "vni": 424242}],
        "evpn_rd_rt": [
            {
                "vlan_id": 42,
                "rd": f"192.0.2.{local_as % 100}:424242",
                "rt_import": l2_rt,
                "rt_export": l2_rt,
            }
        ],
    }
    if l3_rt:
        payload["vrfs"] = [
            {
                "vrf_name": "ISOLATED",
                "l3vni": 434343,
                "rd": f"192.0.2.{local_as % 100}:434343",
                "rt_import": l3_rt,
                "rt_export": l3_rt,
            }
        ]
    return DeviceBulkConfigModel(**payload)


def test_rt_guard_accepts_mutually_compatible_services():
    payloads = [
        evpn_service_payload("edge-a", 64521, "64512:424242", "64512:434343"),
        evpn_service_payload("edge-b", 64522, "64512:424242", "64512:434343"),
    ]

    assert core._validate_fabric_rt_compatibility(payloads) is None


def test_rt_guard_accepts_directional_cross_policy():
    left = evpn_service_payload("edge-a", 64521, "64512:424242")
    right = evpn_service_payload("edge-b", 64522, "64512:424242")
    left.evpn_rd_rt[0].rt_import = "64512:200"
    left.evpn_rd_rt[0].rt_export = "64512:100"
    right.evpn_rd_rt[0].rt_import = "64512:100"
    right.evpn_rd_rt[0].rt_export = "64512:200"

    assert core._validate_fabric_rt_compatibility([left, right]) is None


@pytest.mark.parametrize(
    ("left_l2", "right_l2", "left_l3", "right_l3", "service_type"),
    [
        ("64521:424242", "64522:424242", None, None, "l2vni"),
        ("64512:424242", "64512:424242", "64521:434343", "64522:434343", "l3vni"),
    ],
)
def test_rt_guard_rejects_incompatible_services(
    left_l2, right_l2, left_l3, right_l3, service_type
):
    payloads = [
        evpn_service_payload("edge-a", 64521, left_l2, left_l3),
        evpn_service_payload("edge-b", 64522, right_l2, right_l3),
    ]

    error = core._validate_fabric_rt_compatibility(payloads)

    assert error["error_type"] == "IncompatibleRouteTargets"
    assert error["service"]["type"] == service_type
    assert error["failed_devices"] == ["edge-a", "edge-b"]


class FakeDataplaneManager:
    def __init__(self):
        self.commands = []

    async def send_command_multiple(self, device_names, command):
        self.commands.append(command)
        results = {}
        for device in device_names:
            if command.startswith("show vxlan vni"):
                output = {
                    "vxlanIntfs": {
                        "Vxlan1": {"vniBindings": {"424242": {"vlan": 42}}}
                    }
                }
            elif command.startswith("show vlan"):
                output = {"vlans": {"42": {"status": "active"}}}
            elif command.startswith("show interfaces Vlan"):
                output = {"interfaces": {"Vlan42": {"lineProtocolStatus": "up"}}}
            else:
                output = {}
            results[device] = {"success": True, "result": output}
        return {"results": results}


def test_initial_dataplane_gate_skips_evpn_route_query(monkeypatch):
    manager = FakeDataplaneManager()
    monkeypatch.setattr(core, "nr_mgr", manager)
    check = DataplaneCheckModel(
        device_names=["edge-a", "edge-b"],
        expected_vni=424242,
        expected_vlan=42,
        expected_gateway="192.0.2.1/24",
    )

    result = asyncio.run(core.check_dataplane_summary(check))

    assert result["phase3_ready"] is True
    assert manager.commands == [
        "show vxlan vni | json",
        "show vlan 42 | json",
        "show interfaces Vlan42 | json",
    ]
