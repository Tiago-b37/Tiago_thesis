"""Unit tests for pure guards in the active stdio MCP server.

These tests never connect to a device or modify network state.
"""

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
    from validation_models import DeviceBulkConfigModel
finally:
    os.chdir(_ORIGINAL_CWD)


@pytest.fixture(autouse=True)
def clear_deferred_access_ports():
    core._deferred_access_ports.clear()
    yield
    core._deferred_access_ports.clear()


def routed_interface(name, address):
    return {"interface_name": name, "ip_address": address}


def ebgp_neighbor(address, local_as, remote_as):
    return {
        "neighbor_ip": address,
        "local_as": local_as,
        "remote_as": remote_as,
    }


def test_fabric_dry_run_artifact_is_one_use_and_expires():
    guard = core.WorkflowGuard()
    dry_run_id = guard.register_fabric_dry_run(
        {"leaf1-dc2": {"commands": ["interface Ethernet1"]}}
    )
    assert guard.get_fabric_dry_run(dry_run_id) is not None
    assert guard.consume_fabric_dry_run(dry_run_id) is True
    assert guard.get_fabric_dry_run(dry_run_id) is None
    assert guard.consume_fabric_dry_run(dry_run_id) is False

    expired_id = guard.register_fabric_dry_run(
        {"leaf2-dc2": {"commands": ["interface Ethernet1"]}}
    )
    guard._dry_run_artifacts[expired_id]["created_at"] -= (
        guard._artifact_ttl_seconds + 1
    )
    assert guard.get_fabric_dry_run(expired_id) is None


def test_underlay_guard_rejects_partial_payload():
    spine = DeviceBulkConfigModel(
        device_name="spine1-dc2",
        local_as=65000,
        interfaces=[routed_interface("Ethernet1", "10.0.11.0/31")],
        bgp_neighbors=[ebgp_neighbor("10.0.11.1", 65000, 65101)],
        bgp_networks=[{"network": "1.1.1.1/32"}],
    )
    leaf = DeviceBulkConfigModel(
        device_name="leaf1-dc2",
        local_as=65101,
        interfaces=[routed_interface("Ethernet1", "10.0.11.1/31")],
    )

    error = core._validate_underlay_bulk_completeness([spine, leaf])
    assert error["error_type"] == "IncompleteUnderlayPayload"
    assert error["failed_devices"] == ["leaf1-dc2"]


def test_underlay_guard_accepts_complete_payload():
    spine = DeviceBulkConfigModel(
        device_name="spine1-dc2",
        local_as=65000,
        interfaces=[routed_interface("Ethernet1", "10.0.11.0/31")],
        bgp_neighbors=[ebgp_neighbor("10.0.11.1", 65000, 65101)],
        bgp_networks=[{"network": "1.1.1.1/32"}],
    )
    leaf = DeviceBulkConfigModel(
        device_name="leaf1-dc2",
        local_as=65101,
        interfaces=[routed_interface("Ethernet1", "10.0.11.1/31")],
        bgp_neighbors=[ebgp_neighbor("10.0.11.0", 65101, 65000)],
        bgp_networks=[{"network": "1.1.1.11/32"}],
    )

    assert core._validate_underlay_bulk_completeness([spine, leaf]) is None


def test_fabric_health_does_not_treat_an_empty_alive_result_as_up(monkeypatch):
    class EmptyAliveManager:
        def list_hosts(self):
            return [
                {
                    "name": "leaf1",
                    "platform": "eos",
                    "groups": ["leaf"],
                }
            ]

        async def check_is_alive(self, _device_name):
            return {"host": "leaf1", "success": True, "result": {}}

    monkeypatch.setattr(core, "nr_mgr", EmptyAliveManager())

    result = asyncio.run(core.get_fabric_health())

    assert result["up"] == 0
    assert result["down"] == 1
    assert result["devices"]["leaf1"]["status"] == "down"
