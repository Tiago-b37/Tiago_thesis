#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Add repository root to path so the script can import the MCP implementation.
REPO_ROOT = Path(__file__).resolve().parent.parent
NORNIR_MCP_DIR = REPO_ROOT / "nornir_mcp"
TESTS_DIR = Path(__file__).resolve().parent
DEFAULT_RESULTS_DIR = TESTS_DIR / "results"
sys.path.append(str(REPO_ROOT))
sys.path.append(str(NORNIR_MCP_DIR))

ORIGINAL_CWD = Path.cwd()
os.chdir(NORNIR_MCP_DIR)
try:
    from server_stdio import (  # noqa: E402
        check_bgp_underlay_summary,
        check_dataplane_summary,
        check_evpn_summary,
        send_command_to_devices,
    )
    from validation_models import CheckDevicesModel, DataplaneCheckModel, SendCommandMultipleModel  # noqa: E402
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing Python dependency while importing the MCP validation stack. "
        "Run this script from the same Ubuntu/virtualenv environment used to run the Nornir MCP server."
    ) from exc
finally:
    os.chdir(ORIGINAL_CWD)


FABRIC_DEVICES = ["spine1-dc2", "spine2-dc2", "leaf1-dc2", "leaf2-dc2"]
LEAF_DEVICES = ["leaf1-dc2", "leaf2-dc2"]
CLIENT_CONTAINERS = {
    "client8-dc2": "clab-dc2-topology-client8-dc2",
    "client9-dc2": "clab-dc2-topology-client9-dc2",
    "client10-dc2": "clab-dc2-topology-client10-dc2",
    "client11-dc2": "clab-dc2-topology-client11-dc2",
}


def packet_loss_percent(output: str) -> int | None:
    """Extract packet loss from Linux/BusyBox ping output."""
    matches = re.findall(r"(\d+)% packet loss", output)
    return int(matches[-1]) if matches else None


def docker_ping(source_client: str, destination_ip: str) -> dict:
    """Run a tenant dataplane ping from inside a client container."""
    container = CLIENT_CONTAINERS[source_client]
    cmd = ["docker", "exec", container, "ping", "-c", "3", "-W", "1", destination_ip]
    try:
        completed = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {
            "success": False,
            "packet_loss": None,
            "returncode": None,
            "output": str(exc),
        }

    output = (completed.stdout or "") + (completed.stderr or "")
    loss = packet_loss_percent(output)
    return {
        "success": completed.returncode == 0 and loss == 0,
        "packet_loss": loss,
        "returncode": completed.returncode,
        "output": output.strip(),
    }


def ping_allowed(source_client: str, destination_ip: str) -> bool:
    return docker_ping(source_client, destination_ip)["success"]


def ping_blocked(source_client: str, destination_ip: str) -> bool:
    result = docker_ping(source_client, destination_ip)
    return result["packet_loss"] == 100


def parse_json_output(raw_output):
    if isinstance(raw_output, dict):
        return raw_output
    try:
        if isinstance(raw_output, str) and raw_output.strip():
            return json.loads(raw_output)
    except json.JSONDecodeError:
        pass
    return {}


async def check_tenant_removed(vlan_id: int, vni: int) -> dict:
    """Verify a migrated tenant's old VLAN/VNI state is absent from every leaf."""
    results = {
        "old_vni_removed": True,
        "old_vlan_removed": True,
        "details": {},
    }

    vxlan_res = await send_command_to_devices(
        SendCommandMultipleModel(device_names=LEAF_DEVICES, command="show vxlan vni | json")
    )
    vlan_res = await send_command_to_devices(
        SendCommandMultipleModel(device_names=LEAF_DEVICES, command="show vlan | json")
    )

    for device in LEAF_DEVICES:
        vxlan_raw = parse_json_output(vxlan_res.get("results", {}).get(device, {}).get("result", ""))
        vlan_raw = parse_json_output(vlan_res.get("results", {}).get(device, {}).get("result", ""))

        vni_bindings = (
            vxlan_raw.get("vxlanIntfs", {})
            .get("Vxlan1", {})
            .get("vniBindings", {})
        )
        vlans = vlan_raw.get("vlans", {})

        vni_present = str(vni) in vni_bindings
        vlan_present = str(vlan_id) in vlans

        if vni_present:
            results["old_vni_removed"] = False
        if vlan_present:
            results["old_vlan_removed"] = False

        results["details"][device] = {
            "old_vni_present": vni_present,
            "old_vlan_present": vlan_present,
        }

    return results


async def check_vrf_vni_bindings(expected_bindings: dict[int, str]) -> bool:
    """Verify expected L3VNI-to-VRF bindings on every participating leaf."""
    response = await send_command_to_devices(
        SendCommandMultipleModel(
            device_names=LEAF_DEVICES,
            command="show vxlan vni | json",
        )
    )

    for device in LEAF_DEVICES:
        device_result = response.get("results", {}).get(device, {})
        if not device_result.get("success"):
            return False

        vxlan_raw = parse_json_output(device_result.get("result", ""))
        vrf_bindings = (
            vxlan_raw.get("vxlanIntfs", {})
            .get("Vxlan1", {})
            .get("vniBindingsToVrf", {})
        )

        for vni, expected_vrf in expected_bindings.items():
            binding = vrf_bindings.get(str(vni), {})
            if binding.get("vrfName") != expected_vrf:
                return False

    return True


async def validate_t1() -> dict:
    print("Validating T1: Zero-to-Hero...")
    results = {
        "bgp_underlay_established": False,
        "evpn_established": False,
        "dataplane_ready": False,
        "client8_to_client9": False,
        "client9_to_client8": False,
        "client8_to_gateway": False,
        "client9_to_gateway": False,
        "pings_ok": False,
    }

    try:
        underlay_res = await check_bgp_underlay_summary(CheckDevicesModel(device_names=FABRIC_DEVICES))
        results["bgp_underlay_established"] = underlay_res.get("all_established", False)
        print(f"BGP Underlay Established: {results['bgp_underlay_established']}")
    except Exception as exc:
        print(f"BGP underlay validation failed: {exc}")

    try:
        evpn_res = await check_evpn_summary(CheckDevicesModel(device_names=LEAF_DEVICES))
        results["evpn_established"] = evpn_res.get("all_established", False)
        print(f"EVPN Established: {results['evpn_established']}")
    except Exception as exc:
        print(f"EVPN validation failed: {exc}")

    try:
        dp_res = await check_dataplane_summary(
            DataplaneCheckModel(
                device_names=LEAF_DEVICES,
                expected_vni=10010,
                expected_vlan=10,
                expected_gateway="10.10.10.1/24",
            )
        )
        results["dataplane_ready"] = dp_res.get("phase3_ready", False)
        print(f"Dataplane Ready: {results['dataplane_ready']}")
    except Exception as exc:
        print(f"Dataplane validation failed: {exc}")

    results["client8_to_client9"] = ping_allowed("client8-dc2", "10.10.10.20")
    results["client9_to_client8"] = ping_allowed("client9-dc2", "10.10.10.10")
    results["client8_to_gateway"] = ping_allowed("client8-dc2", "10.10.10.1")
    results["client9_to_gateway"] = ping_allowed("client9-dc2", "10.10.10.1")
    results["pings_ok"] = all(
        [
            results["client8_to_client9"],
            results["client9_to_client8"],
            results["client8_to_gateway"],
            results["client9_to_gateway"],
        ]
    )
    print(f"Connectivity Matrix OK: {results['pings_ok']}")
    return results


async def validate_t2() -> dict:
    print("Validating T2: VLAN Migration...")
    results = {
        "vlan20_ready": False,
        "client8_to_client9": False,
        "client9_to_client8": False,
        "client8_to_gateway": False,
        "client9_to_gateway": False,
        "old_vni_removed": False,
        "old_vlan_removed": False,
        "old_tenant_removed": False,
        "pings_ok": False,
        "migration_complete": False,
    }

    try:
        dp_res = await check_dataplane_summary(
            DataplaneCheckModel(
                device_names=LEAF_DEVICES,
                expected_vni=10020,
                expected_vlan=20,
                expected_gateway="10.20.20.1/24",
            )
        )
        results["vlan20_ready"] = dp_res.get("phase3_ready", False)
        print(f"VLAN 20/VNI 10020 Ready: {results['vlan20_ready']}")
    except Exception as exc:
        print(f"Dataplane validation failed: {exc}")

    results["client8_to_client9"] = ping_allowed("client8-dc2", "10.20.20.20")
    results["client9_to_client8"] = ping_allowed("client9-dc2", "10.20.20.10")
    results["client8_to_gateway"] = ping_allowed("client8-dc2", "10.20.20.1")
    results["client9_to_gateway"] = ping_allowed("client9-dc2", "10.20.20.1")
    results["pings_ok"] = all(
        [
            results["client8_to_client9"],
            results["client9_to_client8"],
            results["client8_to_gateway"],
            results["client9_to_gateway"],
        ]
    )
    print(f"Migration Connectivity OK: {results['pings_ok']}")

    try:
        cleanup_res = await check_tenant_removed(vlan_id=10, vni=10010)
        results["old_vni_removed"] = cleanup_res["old_vni_removed"]
        results["old_vlan_removed"] = cleanup_res["old_vlan_removed"]
        results["old_tenant_removed"] = results["old_vni_removed"] and results["old_vlan_removed"]
        print(f"Old Tenant Removed: {results['old_tenant_removed']}")
    except Exception as exc:
        print(f"Old tenant cleanup validation failed: {exc}")

    results["migration_complete"] = all(
        [
            results["vlan20_ready"],
            results["pings_ok"],
            results["old_tenant_removed"],
        ]
    )
    print(f"Migration Complete: {results['migration_complete']}")
    return results


async def validate_t3() -> dict:
    """Validate T3: Overlapping Tenant Isolation (VRF + Symmetric IRB).

    Tests that two tenants (BLUE on VLAN 10, RED on VLAN 20) using the
    same IP range 10.10.10.0/24 are fully isolated via VRF/L3VNI while
    each tenant has full intra-tenant cross-leaf connectivity.

    Isolation proof: if both tenants work simultaneously with overlapping
    IPs, route leaking is impossible — packets would go to wrong
    destinations and pings would fail.
    """
    print("Validating T3: Overlapping Tenant Isolation (VRF + Symmetric IRB)...")
    results = {
        "blue_c8_to_c9": False,
        "blue_c9_to_c8": False,
        "red_c10_to_c11": False,
        "red_c11_to_c10": False,
        "blue_c8_to_gateway": False,
        "red_c10_to_gateway": False,
        "blue_to_red_blocked": False,
        "red_to_blue_blocked": False,
        "blue_intra_tenant_ok": False,
        "red_intra_tenant_ok": False,
        "overlapping_gateway_ok": False,
        "cross_tenant_blocked": False,
        "symmetric_irb_ready": False,
        "policy_compliance": False,
    }

    # BLUE tenant (VLAN 10): client8 <-> client9
    results["blue_c8_to_c9"] = ping_allowed("client8-dc2", "10.10.10.20")
    results["blue_c9_to_c8"] = ping_allowed("client9-dc2", "10.10.10.10")
    results["blue_intra_tenant_ok"] = results["blue_c8_to_c9"] and results["blue_c9_to_c8"]
    print(f"BLUE Intra-Tenant (c8<->c9): {results['blue_intra_tenant_ok']}")

    # RED tenant (VLAN 20): client10 <-> client11 (same IPs!)
    results["red_c10_to_c11"] = ping_allowed("client10-dc2", "10.10.10.40")
    results["red_c11_to_c10"] = ping_allowed("client11-dc2", "10.10.10.30")
    results["red_intra_tenant_ok"] = results["red_c10_to_c11"] and results["red_c11_to_c10"]
    print(f"RED  Intra-Tenant (c10<->c11): {results['red_intra_tenant_ok']}")

    # Gateway reachability (both VRFs use 10.10.10.1)
    results["blue_c8_to_gateway"] = ping_allowed("client8-dc2", "10.10.10.1")
    results["red_c10_to_gateway"] = ping_allowed("client10-dc2", "10.10.10.1")
    results["overlapping_gateway_ok"] = results["blue_c8_to_gateway"] and results["red_c10_to_gateway"]
    print(f"Overlapping Gateway OK: {results['overlapping_gateway_ok']}")

    # Cross-tenant isolation: BLUE must not reach RED, and RED must not reach BLUE.
    results["blue_to_red_blocked"] = ping_blocked("client8-dc2", "10.10.10.30")
    results["red_to_blue_blocked"] = ping_blocked("client10-dc2", "10.10.10.10")
    results["cross_tenant_blocked"] = results["blue_to_red_blocked"] and results["red_to_blue_blocked"]
    print(f"Cross-Tenant Blocked: {results['cross_tenant_blocked']}")

    try:
        results["symmetric_irb_ready"] = await check_vrf_vni_bindings(
            {
                50010: "BLUE",
                50020: "RED",
            }
        )
        print(f"Symmetric IRB Ready: {results['symmetric_irb_ready']}")
    except Exception as exc:
        print(f"Symmetric IRB validation failed: {exc}")

    # Final verdict
    results["policy_compliance"] = all([
        results["blue_intra_tenant_ok"],
        results["red_intra_tenant_ok"],
        results["overlapping_gateway_ok"],
        results["cross_tenant_blocked"],
        results["symmetric_irb_ready"],
    ])
    print(f"Policy Compliance: {results['policy_compliance']}")
    return results


def resolve_run_label(args: argparse.Namespace) -> str:
    run_label = args.run or args.model
    if not run_label:
        raise SystemExit("Provide a run label with --run, for example: --run claude_sonnet")
    return run_label


async def main() -> None:
    parser = argparse.ArgumentParser(description="Validate post-LLM network state")
    parser.add_argument("test_id", choices=["T1", "T2", "T3"], help="Test scenario to validate")
    parser.add_argument("--run", help="Run label used under tests/results")
    parser.add_argument("--model", help="Deprecated alias for --run")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Directory for JSON results")
    args = parser.parse_args()

    if args.test_id == "T1":
        results = await validate_t1()
    elif args.test_id == "T2":
        results = await validate_t2()
    else:
        results = await validate_t3()

    out_dir = Path(args.results_dir) / resolve_run_label(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{args.test_id}_validation.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nValidation complete. Results saved to {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
