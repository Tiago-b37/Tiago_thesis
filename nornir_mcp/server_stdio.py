#!/usr/bin/env python3
# Nornir MCP server using stdio transport.
import hashlib
import logging
import time
import uuid
from ipaddress import ip_address
from mcp.server.fastmcp import FastMCP
from nornir_ops import NornirManager
from validation_models import (
    BGPConfigModel,
    BGPNeighborsDetailModel,
    DeviceNameModel,
    GetConfigModel,
    LLDPNeighborsDetailModel,
    NetworkInstancesModel,
    SendCommandModel,
    SendCommandMultipleModel,
    CheckDevicesModel,
    TracerouteModel,
    BGPNeighborConfigModel,
    EVPNPeerConfigModel,
    VLAN_VNIMappingModel,
    VXLANConfigModel,
    SVIConfigModel,
    EVPNRdRtConfigModel,
    InterfaceConfigModel,
    VRFConfigModel,
    MLAGConfigModel,
    VXLANDeleteModel,
    BGPNeighborDeleteModel,
    OSPFConfigModel,
    OSPFDeleteModel,
    ConfigMode,
    ResponseMode,
    make_validate_params,
    DeviceBulkConfigModel,
    FabricBulkConfigModel,
    ApplyFabricDryRunModel,
    DataplaneCheckModel,
    VRFDetailModel,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("nornir_mcp_stdio")

try:
    mcp = FastMCP("Nornir_MCP")
    nr_mgr = NornirManager()
except Exception as e:
    logger.critical(f"Fatal error during initialization: {e}", exc_info=True)
    exit(1)

class WorkflowGuard:
    """
    Enforces the 'Dry-Run before Apply' rule for the Network Thesis project.
    """
    def __init__(self):
        # Stores fingerprints of successful dry-run operations
        # Key: (device_name, operation_name, config_hash)
        self._dry_run_history = {}
        self._dry_run_artifacts = {}
        self._artifact_ttl_seconds = 3600

    def _generate_fingerprint(self, device_name, operation_name, config_commands):
        """Generates a unique fingerprint for a configuration intent."""
        config_str = "\n".join(config_commands)
        params_hash = hashlib.sha256(config_str.encode()).hexdigest()
        # We include device_name and operation_name (e.g., 'Configure Interface Ethernet1')
        # to ensure the context matches the dry-run.
        return (device_name, operation_name, params_hash)

    def register_dry_run(self, device_name, operation_name, config_commands):
        """Registers a configuration intent as having been dry-run."""
        fingerprint = self._generate_fingerprint(device_name, operation_name, config_commands)
        self._dry_run_history[fingerprint] = True
        logger.info(f"[WorkflowGuard] Registered dry-run for {device_name} ({operation_name})")

    def check_intent(self, device_name, operation_name, config_commands):
        """Checks if a matching configuration intent was previously dry-run."""
        fingerprint = self._generate_fingerprint(device_name, operation_name, config_commands)
        return self._dry_run_history.get(fingerprint, False)

    def register_fabric_dry_run(self, device_artifacts):
        """Stores a successful fabric dry-run artifact for one-use apply."""
        dry_run_id = f"fabric_{uuid.uuid4().hex[:12]}"
        self._dry_run_artifacts[dry_run_id] = {
            "dry_run_id": dry_run_id,
            "created_at": time.time(),
            "devices": list(device_artifacts.keys()),
            "artifacts": device_artifacts,
            "consumed": False,
        }
        logger.info(
            f"[WorkflowGuard] Registered fabric dry-run {dry_run_id} "
            f"for {len(device_artifacts)} devices"
        )
        return dry_run_id

    def get_fabric_dry_run(self, dry_run_id):
        """Returns a stored fabric dry-run artifact if it is present and valid."""
        artifact = self._dry_run_artifacts.get(dry_run_id)
        if not artifact:
            return None
        if artifact.get("consumed"):
            return None
        if time.time() - artifact.get("created_at", 0) > self._artifact_ttl_seconds:
            self._dry_run_artifacts.pop(dry_run_id, None)
            return None
        return artifact

    def consume_fabric_dry_run(self, dry_run_id):
        """Consumes a fabric dry-run artifact after successful apply."""
        artifact = self._dry_run_artifacts.pop(dry_run_id, None)
        if artifact:
            artifact["consumed"] = True
        logger.info(f"[WorkflowGuard] Consumed fabric dry-run {dry_run_id}")
        return artifact is not None

workflow_guard = WorkflowGuard()

# [Deferred-Guard] In-memory queue: stores access ports blocked by Phase-Guard in Phase 1.
# When Phase 3 arrives (detected by presence of 'vlans'), deferred ports are auto-injected.
# Cleared per device after injection. Lives in RAM — valid for one continuous session.
_deferred_access_ports: dict = {}

# Register validate_params
try:
    validate_params = mcp.tool(
        description="Validate input payloads against known Pydantic models; returns success, validation details, model schema, and example."
    )(make_validate_params(nr_mgr))
except Exception as e:
    logger.warning(f"Failed to register 'validate_params' tool: {e}")

# Register prompts
try:
    from prompts import register_prompts
    register_prompts(mcp)
except Exception as e:
    logger.warning(f"Could not import or register prompts from prompts.py: {e}")

# Register resources
try:
    from resources import register_resources
    register_resources(mcp, nr_mgr)
except Exception as e:
    logger.warning(f"Could not import or register resources from resources.py: {e}")

# --- Network operation tools ---

@mcp.tool()
async def get_facts(data: DeviceNameModel):
    """Retrieve high-level facts and information about the device (e.g., vendor, model, serial number, OS version)."""
    logger.info(f"[Tool] 'get_facts' called for {data.device_name}")
    return await nr_mgr.get_napalm_data(data.device_name, "facts")



@mcp.tool()
async def get_arp_table(data: DeviceNameModel):
    """Get the device's ARP (Address Resolution Protocol) table."""
    logger.info(f"[Tool] 'get_arp_table' called for {data.device_name}")
    return await nr_mgr.get_napalm_data(data.device_name, "arp_table")

@mcp.tool()
async def get_bgp_neighbors(data: DeviceNameModel):
    """Get a summary of BGP (Border Gateway Protocol) neighbors."""
    logger.info(f"[Tool] 'get_bgp_neighbors' called for {data.device_name}")
    return await nr_mgr.get_napalm_data(data.device_name, "bgp_neighbors")



@mcp.tool()
async def get_interfaces_ip(data: DeviceNameModel):
    """Get IP address information for all interfaces."""
    logger.info(f"[Tool] 'get_interfaces_ip' called for {data.device_name}")
    return await nr_mgr.get_napalm_data(data.device_name, "interfaces_ip")



@mcp.tool()
async def get_lldp_neighbors(data: DeviceNameModel):
    """Get a summary of LLDP (Link Layer Discovery Protocol) neighbors."""
    logger.info(f"[Tool] 'get_lldp_neighbors' called for {data.device_name}")
    return await nr_mgr.get_napalm_data(data.device_name, "lldp_neighbors")



@mcp.tool()
async def is_alive(data: DeviceNameModel):
    """Check health and reachability of the device management interface."""
    logger.info(f"[Tool] 'is_alive' called for {data.device_name}")
    return await nr_mgr.check_is_alive(data.device_name)

@mcp.tool()
async def get_config(data: GetConfigModel):
    """Use NAPALM to retrieve device configurations (running, startup, or candidate)."""
    logger.info(f"[Tool] get_config called for {data.device_name} (retrieve={data.retrieve})")
    nr_mgr.recover_failed_hosts([data.device_name])
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "InventoryError",
            "result": f"Device '{data.device_name}' not found.",
        }
    from nornir_napalm.plugins.tasks import napalm_get
    result = host.run(
        task=napalm_get,
        getters=["config"],
        retrieve=data.retrieve,
        name=f"Get '{data.retrieve}' config for {data.device_name}",
        raise_on_error=False,
    )
    return nr_mgr._format_result(result, data.device_name)

@mcp.tool()
async def get_bgp_config(data: BGPConfigModel):
    """Retrieve BGP configuration from the device."""
    logger.info(f"[Tool] get_bgp_config called for {data.device_name}")
    nr_mgr.recover_failed_hosts([data.device_name])
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "InventoryError",
            "result": f"Device '{data.device_name}' not found.",
        }
    from nornir_napalm.plugins.tasks import napalm_get
    result = host.run(
        task=napalm_get,
        getters=["bgp_config"],
        group=data.group,
        neighbor=data.neighbor,
        name=f"Get BGP config for {data.device_name}",
        raise_on_error=False,
    )
    return nr_mgr._format_result(result, data.device_name)

@mcp.tool()
async def get_bgp_neighbors_detail(data: BGPNeighborsDetailModel):
    """Obtain a detailed view of all BGP neighbors."""
    logger.info(f"[Tool] get_bgp_neighbors_detail called for {data.device_name}")
    nr_mgr.recover_failed_hosts([data.device_name])
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "InventoryError",
            "result": f"Device '{data.device_name}' not found.",
        }
    from nornir_napalm.plugins.tasks import napalm_get
    result = host.run(
        task=napalm_get,
        getters=["bgp_neighbors_detail"],
        neighbor_address=data.neighbor_address,
        name=f"Get BGP neighbors detail for {data.device_name}",
        raise_on_error=False,
    )
    return nr_mgr._format_result(result, data.device_name)

@mcp.tool()
async def get_lldp_neighbors_detail(data: LLDPNeighborsDetailModel):
    """Obtain a detailed view of all LLDP neighbors."""
    logger.info(f"[Tool] get_lldp_neighbors_detail called for {data.device_name}")
    nr_mgr.recover_failed_hosts([data.device_name])
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "InventoryError",
            "result": f"Device '{data.device_name}' not found.",
        }
    from nornir_napalm.plugins.tasks import napalm_get
    result = host.run(
        task=napalm_get,
        getters=["lldp_neighbors_detail"],
        interface=data.interface,
        name=f"Get LLDP neighbors detail for {data.device_name}",
        raise_on_error=False,
    )
    return nr_mgr._format_result(result, data.device_name)

@mcp.tool()
async def get_network_instances(data: NetworkInstancesModel):
    """Retrieve a list of network instances (e.g., VRFs)."""
    logger.info(f"[Tool] get_network_instances called for {data.device_name}")
    nr_mgr.recover_failed_hosts([data.device_name])
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "InventoryError",
            "result": f"Device '{data.device_name}' not found.",
        }
    from nornir_napalm.plugins.tasks import napalm_get
    result = host.run(
        task=napalm_get,
        getters=["network_instances"],
        name=data.name,
        raise_on_error=False,
    )
    return nr_mgr._format_result(result, data.device_name)

@mcp.tool()
async def traceroute(data: TracerouteModel):
    """Execute the traceroute command from the device to the specified destination."""
    logger.info(f"[Tool] traceroute called for {data.device_name} to {data.destination}")
    return await nr_mgr.traceroute(
        device_name=data.device_name,
        destination=data.destination,
        source=data.source,
        ttl=data.ttl,
        timeout=data.timeout,
        vrf=data.vrf,
    )



@mcp.tool()
async def send_command_to_devices(data: SendCommandMultipleModel):
    """Send a validated read-only command concurrently to multiple devices."""
    
    cmd_lower = data.command.lower()
    logger.info(f"[Tool] send_command_to_devices called for {data.device_names} with command: {data.command}")
    
    result = await nr_mgr.send_command_multiple(data.device_names, data.command)
    return result

@mcp.tool()
async def check_ospf_summary(data: CheckDevicesModel):
    """
    Check OSPF adjacencies across multiple devices efficiently.
    Returns a highly compact summary of OSPF states to save LLM context tokens.
    CRITICAL: If this returns false or empty, it means the network is converging. You MUST sleep 10 and retry.
    DO NOT attempt to run ANY manual show commands (e.g. show ip ospf neighbor).
    If it explicitly fails after retries, you MUST immediately load the fabric-diagnostics skill.
    """
    logger.info(f"[Tool] check_ospf_summary called for {data.device_names}")
    result = await nr_mgr.send_command_multiple(data.device_names, "show ip ospf neighbor")
    
    summary = {}
    for device, res in result.get("results", {}).items():
        if not res.get("success"):
            summary[device] = {"status": "error", "error": str(res.get("result", ""))}
            continue
            
        output = res.get("result", "")
        # Nornir send_command might return { 'show ip ospf neighbor': '...' }
        if isinstance(output, dict):
            output = list(output.values())[0] if output else ""
            
        neighbors = []
        for line in str(output).splitlines():
            line = line.strip()
            if not line or line.startswith("Neighbor"):
                continue
            parts = line.split()
            # Arista format: Neighbor ID(0), VRF(1), Pri(2), State(3), Dead Time(4), Address(5), Interface(6)
            if len(parts) >= 5:
                neighbor_ip = parts[0]
                # Safely scan columns 3 to 5 for "FULL" (handles Instance column presence)
                state = parts[3]
                for p in parts[3:6]:
                    if "FULL" in p.upper():
                        state = p
                        break
                neighbors.append({"neighbor": neighbor_ip, "state": state})
                    
        is_all_full = all("FULL" in n["state"].upper() for n in neighbors) if neighbors else False
        summary[device] = {
            "all_full": is_all_full,
            "total_neighbors": len(neighbors),
            "adjacencies": neighbors
        }

    failed_devices = [dev for dev, dev_summary in summary.items() if not dev_summary.get("all_full", False)]
    total_neighbors = sum(dev_summary.get("total_neighbors", 0) for dev_summary in summary.values())
    all_full = len(summary) == len(data.device_names) and not failed_devices
    compact = {
        "success": True,
        "all_full": all_full,
        "devices_checked": len(summary),
        "total_neighbors": total_neighbors,
        "failed_devices": failed_devices,
    }
    if not data.include_details:
        return compact
    compact["ospf_summary"] = summary
    return compact


@mcp.tool()
async def check_bgp_underlay_summary(data: CheckDevicesModel):
    """
    Check IPv4 BGP underlay sessions across multiple devices.
    A session is considered established when EOS reports a numeric prefix count
    or an explicit Established/Estab state in the State/PfxRcd column.
    """
    logger.info(f"[Tool] check_bgp_underlay_summary called for {data.device_names}")
    result = await nr_mgr.send_command_multiple(data.device_names, "show ip bgp summary")

    def _looks_like_bgp_uptime(value: str) -> bool:
        value = value.strip().lower()
        if value in {"never", "n/a", "-"}:
            return False
        return ":" in value or any(unit in value for unit in ("w", "d", "h", "m", "s"))

    def _parse_bgp_neighbors(raw_output) -> list[dict]:
        if isinstance(raw_output, dict):
            raw_output = list(raw_output.values())[0] if raw_output else ""

        parsed_neighbors = []
        for line in str(raw_output).splitlines():
            parts = line.strip().split()
            if len(parts) < 2:
                continue

            neighbor_index = None
            neighbor_ip = None
            for index, token in enumerate(parts):
                try:
                    ip_address(token)
                except ValueError:
                    continue
                neighbor_index = index
                neighbor_ip = token
                break

            if neighbor_index is None or neighbor_ip is None:
                continue
            if len(parts) <= neighbor_index + 8:
                continue

            up_down_index = neighbor_index + 7
            state_pfx_index = neighbor_index + 8
            up_down = parts[up_down_index] if len(parts) > up_down_index else ""
            state_pfx = parts[state_pfx_index] if len(parts) > state_pfx_index else parts[-1]

            if state_pfx.isdigit() and _looks_like_bgp_uptime(up_down):
                state = "Established"
            elif "ESTAB" in state_pfx.upper():
                state = "Established"
            else:
                state = state_pfx

            parsed_neighbors.append({"neighbor": neighbor_ip, "state": state})

        return parsed_neighbors

    summary = {}
    for device, res in result.get("results", {}).items():
        if not res.get("success"):
            summary[device] = {"status": "error", "error": str(res.get("result", ""))}
            continue

        neighbors = _parse_bgp_neighbors(res.get("result", ""))
        is_all_estab = all("ESTAB" in n["state"].upper() for n in neighbors) if neighbors else False
        summary[device] = {
            "all_established": is_all_estab,
            "total_neighbors": len(neighbors),
            "sessions": neighbors,
        }

    failed_devices = [dev for dev, dev_summary in summary.items() if not dev_summary.get("all_established", False)]
    total_sessions = sum(dev_summary.get("total_neighbors", 0) for dev_summary in summary.values())
    all_established = len(summary) == len(data.device_names) and not failed_devices
    compact = {
        "success": True,
        "all_established": all_established,
        "devices_checked": len(summary),
        "total_sessions": total_sessions,
        "failed_devices": failed_devices,
    }
    if not data.include_details:
        return compact
    compact["bgp_underlay_summary"] = summary
    return compact


@mcp.tool()
async def check_evpn_summary(data: CheckDevicesModel):
    """
    Check BGP EVPN sessions across multiple devices efficiently.
    Returns a highly compact summary to save LLM context tokens.
    CRITICAL: If this returns false or empty, it means the network is converging. You MUST sleep 10 and retry.
    DO NOT attempt to run ANY manual show commands (e.g. show bgp summary).
    If it explicitly fails after retries, you MUST immediately load the fabric-diagnostics skill.
    """
    logger.info(f"[Tool] check_evpn_summary called for {data.device_names}")
    result = await nr_mgr.send_command_multiple(data.device_names, "show bgp evpn summary")

    def _looks_like_bgp_uptime(value: str) -> bool:
        value = value.strip().lower()
        if value in {"never", "n/a", "-"}:
            return False
        return ":" in value or any(unit in value for unit in ("w", "d", "h", "m", "s"))

    def _parse_evpn_neighbors(raw_output) -> list[dict]:
        if isinstance(raw_output, dict):
            raw_output = list(raw_output.values())[0] if raw_output else ""

        parsed_neighbors = []
        for line in str(raw_output).splitlines():
            parts = line.strip().split()
            if len(parts) < 2:
                continue

            neighbor_index = None
            neighbor_ip = None
            for index, token in enumerate(parts):
                try:
                    ip_address(token)
                except ValueError:
                    continue
                neighbor_index = index
                neighbor_ip = token
                break

            if neighbor_index is None or neighbor_ip is None:
                continue

            # Valid EOS BGP summary rows have at least:
            # Neighbor, V, AS, MsgRcvd, MsgSent, InQ, OutQ, Up/Down, State/PfxRcd.
            if len(parts) <= neighbor_index + 8:
                continue

            state_start = neighbor_index + 7
            state_tokens = parts[state_start:]
            state = state_tokens[-1] if state_tokens else "unknown"

            for token in state_tokens:
                if "ESTAB" in token.upper():
                    state = "Established"
                    break
            else:
                # Some EOS summaries use State/PfxRcd: an Established session is shown
                # as a numeric prefix count, often 0, after the Up/Down column.
                state_pfx_index = neighbor_index + 8
                up_down_index = neighbor_index + 7
                state_pfx = parts[state_pfx_index] if len(parts) > state_pfx_index else state
                up_down = parts[up_down_index] if len(parts) > up_down_index else ""
                if state_pfx.isdigit() and _looks_like_bgp_uptime(up_down):
                    state = "Established"
                else:
                    state = state_pfx

            parsed_neighbors.append({"neighbor": neighbor_ip, "state": state})

        return parsed_neighbors
    
    summary = {}
    for device, res in result.get("results", {}).items():
        if not res.get("success"):
            summary[device] = {"status": "error", "error": str(res.get("result", ""))}
            continue
            
        neighbors = _parse_evpn_neighbors(res.get("result", ""))
                    
        is_all_estab = all("ESTAB" in n["state"].upper() for n in neighbors) if neighbors else False
        summary[device] = {
            "all_established": is_all_estab,
            "total_neighbors": len(neighbors),
            "sessions": neighbors
        }

    failed_devices = [dev for dev, dev_summary in summary.items() if not dev_summary.get("all_established", False)]
    total_sessions = sum(dev_summary.get("total_neighbors", 0) for dev_summary in summary.values())
    all_established = len(summary) == len(data.device_names) and not failed_devices
    compact = {
        "success": True,
        "all_established": all_established,
        "devices_checked": len(summary),
        "total_sessions": total_sessions,
        "failed_devices": failed_devices,
    }
    if not data.include_details:
        return compact
    compact["evpn_summary"] = summary
    return compact


@mcp.tool()
async def check_dataplane_summary(data: DataplaneCheckModel):
    """
    Validate the lightweight Phase 3 VXLAN, VLAN, and SVI fabric state.
    """
    import json
    logger.info(f"[Tool] check_dataplane_summary called for {data.device_names}")

    def parse_json_output(raw_output):
        if isinstance(raw_output, dict):
            return raw_output
        try:
            if isinstance(raw_output, str) and raw_output.strip():
                return json.loads(raw_output)
        except json.JSONDecodeError:
            pass
        return {}

    # Commands for Arista EOS
    commands = [
        "show vxlan vni | json",
        f"show vlan {data.expected_vlan} | json",
        f"show interfaces Vlan{data.expected_vlan} | json",
    ]

    results_matrix = {}
    for cmd in commands:
        res = await nr_mgr.send_command_multiple(data.device_names, cmd)
        results_matrix[cmd] = res.get("results", {})

    summary_details = {}
    phase3_ready = True

    for device in data.device_names:
        dev_res = {
            "vni_status": "down",
            "vlan_status": "down",
            "svi_status": "down",
            "ready": False
        }

        # 1. VXLAN VNI Check
        vni_raw = parse_json_output(results_matrix[commands[0]].get(device, {}).get("result", ""))
        if isinstance(vni_raw, dict) and "vxlanIntfs" in vni_raw:
             vni_info = vni_raw["vxlanIntfs"].get("Vxlan1", {}).get("vniBindings", {}).get(str(data.expected_vni), {})
             # Arista's 'show vxlan vni' doesn't return a 'status', just the existence of the mapping
             dev_res["vni_status"] = "up" if vni_info else "down"

        # 2. VLAN Check
        vlan_raw = parse_json_output(results_matrix[commands[1]].get(device, {}).get("result", ""))
        if isinstance(vlan_raw, dict) and "vlans" in vlan_raw:
            vlan_info = vlan_raw["vlans"].get(str(data.expected_vlan), {})
            dev_res["vlan_status"] = str(vlan_info.get("status", "down")).lower()

        # 3. SVI Check
        svi_raw = parse_json_output(results_matrix[commands[2]].get(device, {}).get("result", ""))
        if isinstance(svi_raw, dict) and "interfaces" in svi_raw:
            svi_info = svi_raw["interfaces"].get(f"Vlan{data.expected_vlan}", {})
            dev_res["svi_status"] = str(svi_info.get("lineProtocolStatus", "down")).lower()

        # Final "Ready" bit for this device
        dev_res["ready"] = (
            dev_res["vni_status"] == "up" and
            dev_res["vlan_status"] == "active" and
            dev_res["svi_status"] == "up"
        )

        if not dev_res["ready"]:
            phase3_ready = False

        summary_details[device] = dev_res

    failed_devices = [dev for dev, dev_res in summary_details.items() if not dev_res.get("ready", False)]
    compact = {
        "success": True,
        "phase3_ready": phase3_ready,
        "devices_checked": len(summary_details),
        "failed_devices": failed_devices,
    }
    if phase3_ready and not data.include_details:
        return compact
    compact["dataplane_summary"] = summary_details
    return compact


@mcp.tool()
async def send_command(data: SendCommandModel):
    """Send a validated read-only command or list of commands to the device."""
    if data.commands:
        cmds = data.commands
    elif data.command:
        cmds = [data.command]
    else:
        logger.warning("send_command called without 'command' or 'commands' field")
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "ValidationError",
            "result": "Either 'command' or 'commands' must be provided.",
        }

    for c in cmds:
        cmd_lower = c.lower()
        if "reboot" in cmd_lower or "reload" in cmd_lower:
            return {
                 "host": data.device_name,
                 "success": False,
                 "error_type": "WorkflowViolation",
                 "result": "Destructive commands like reboot are strictly blocked."
            }

    logger.info(f"[Tool] send_command called for {data.device_name} with commands: {cmds}")
    result = await nr_mgr.send_command(data.device_name, cmds)

    try:
        if hasattr(result, "items"):
            host_key = next(iter(result.keys()), None)
            if host_key is not None:
                host_res = result[host_key]
                if isinstance(host_res, (list, tuple)) and host_res:
                    first = host_res[0]
                    payload = getattr(first, "result", first)
                    if isinstance(payload, dict):
                        return payload
                    if isinstance(payload, str) and len(cmds) == 1:
                        return {cmds[0]: payload}
                    return payload
        if hasattr(result, "result"):
            payload = getattr(result, "result")
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, str) and len(cmds) == 1:
                return {cmds[0]: payload}
            return payload
    except Exception:
        logger.exception("Unable to coerce nr_mgr result into serializable structure")

    return result

@mcp.tool()
async def list_all_hosts():
    """Read canonical device names from the local Nornir inventory without contacting devices.
    Use only when the active target set is missing or ambiguous; do not reconfirm targets
    already supplied by the request or another tool."""
    logger.info("[Tool] list_all_hosts called")
    try:
        hosts_raw = nr_mgr.list_hosts()
        if isinstance(hosts_raw, str):
            import json
            try:
                hosts = json.loads(hosts_raw)
            except Exception:
                logger.exception("Failed to parse hosts JSON string from nr_mgr.list_hosts()")
                return {"success": False, "error": "invalid_inventory_format"}
        else:
            hosts = hosts_raw

        if isinstance(hosts, dict):
            hosts = [hosts]

        if not isinstance(hosts, list):
            logger.warning("Unexpected hosts structure from nr_mgr.list_hosts(): %s", type(hosts).__name__)
            return {"success": False, "error": "unexpected_inventory_shape"}

        result = []
        for h in hosts:
            if not isinstance(h, dict):
                try:
                    import json
                    h = json.loads(h)
                except Exception:
                    logger.warning("Skipping non-dict host entry: %s", type(h).__name__)
                    continue

            device = h.get("device_name") or h.get("name")
            if device:
                result.append({"device_name": device})

        logger.debug("[Tool:list_all_hosts] returning %d hosts", len(result))
        return result
    except Exception as e:
        logger.exception("Unexpected error in list_all_hosts: %s", e)
        return {"success": False, "error": "internal_error", "detail": str(e)}

@mcp.tool()
async def get_fabric_health():
    """Check reachability of fabric network devices in a SINGLE call.
    Use when base reachability is in doubt or a targeted read failed, not as a routine
    preflight for a protocol-specific symptom. Non-network endpoints are reported as skipped."""
    logger.info("[Tool] get_fabric_health called")
    hosts = nr_mgr.list_hosts()
    if not hosts:
        return {"success": False, "error": "No hosts in inventory."}
    
    devices = {}
    up_count = 0
    down_count = 0
    skipped_count = 0
    network_platforms = {"eos", "arista_eos"}
    for h in hosts:
        name = h.get("name", h.get("device_name"))
        if not name:
            continue
        platform = h.get("platform", "unknown")
        groups = {str(group) for group in (h.get("groups") or [])}
        if platform not in network_platforms or "clients" in groups:
            devices[name] = {
                "status": "skipped",
                "platform": platform,
                "reason": "non_fabric_host",
            }
            skipped_count += 1
            continue
        try:
            alive_result = await nr_mgr.check_is_alive(name)
            alive_payload = alive_result.get("result")
            if isinstance(alive_payload, dict):
                is_up = bool(alive_payload.get("is_alive", False))
            else:
                is_up = alive_payload is True
            is_up = bool(alive_result.get("success", False) and is_up)
            devices[name] = {"status": "up" if is_up else "down", "platform": platform}
            if is_up:
                up_count += 1
            else:
                down_count += 1
        except Exception as e:
            devices[name] = {"status": "error", "error": str(e)}
            down_count += 1
    
    return {
        "success": True,
        "total": len(devices),
        "up": up_count,
        "down": down_count,
        "skipped": skipped_count,
        "devices": devices,
    }

# --- Safe Configuration Tools with Protection ---

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from enum import Enum


def _validate_ospf_passive_default(data) -> Optional[str]:
    """Block OSPF configs that would suppress hellos on fabric links."""
    if not getattr(data, "passive_default", False):
        return None

    has_adjacency_network = False
    for net in getattr(data, "networks", None) or []:
        network = net.get("network", "")
        if not network:
            continue
        if "/" not in network:
            has_adjacency_network = True
            break
        try:
            import ipaddress
            prefix = ipaddress.ip_network(network, strict=False)
            if prefix.prefixlen < prefix.max_prefixlen:
                has_adjacency_network = True
                break
        except ValueError:
            has_adjacency_network = True
            break

    if not has_adjacency_network:
        return None

    active_interfaces = [
        iface for iface in (getattr(data, "interfaces", None) or [])
        if iface.get("name") and iface.get("passive", False) is False
    ]
    if active_interfaces:
        return None

    return (
        "OSPF passive_default=true advertises non-loopback networks but no active "
        "OSPF interfaces were provided. Add ospf[].interfaces[] entries for the "
        "P2P fabric links with passive=false and network_type='point-to-point', "
        "or remove passive_default."
    )


def _generate_vxlan_config(data: VXLANConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """
    Generate VXLAN configuration commands for Arista EOS.
    Returns: (config_commands, error_message)
    """
    config_commands = []

    if platform not in ("eos", "arista_eos"):
        return [], f"VXLAN configuration not supported for platform: {platform}"

    config_commands.append("interface Vxlan1")
    config_commands.append(f"  vxlan vlan {data.vlan_id} vni {data.vni}")
    if data.source_interface:
        config_commands.append(f"  vxlan source-interface {data.source_interface}")
    if data.multicast_group:
        config_commands.append(f"  vxlan multicast-group {data.multicast_group}")
    if data.flood_vteps:
        flood_list = " ".join(data.flood_vteps)
        if data.vlan_id:
            config_commands.append(f"  vxlan vlan {data.vlan_id} flood vtep {flood_list}")
        else:
            config_commands.append(f"  vxlan flood vtep {flood_list}")
    
    return config_commands, None


def _generate_bgp_config(data: BGPNeighborConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """
    Generate BGP neighbor configuration commands for Arista EOS.
    Returns: (config_commands, error_message)
    """
    config_commands = []

    if platform not in ("eos", "arista_eos"):
        return [], f"BGP configuration not supported for platform: {platform}"

    if not data.local_as:
        return [], "local_as is required for Arista platforms"
    # Arista cEOS has 'no ip routing' by default; BGP requires it.
    config_commands.append("ip routing")
    config_commands.append(f"router bgp {data.local_as}")
    config_commands.append(f"  neighbor {data.neighbor_ip} remote-as {data.remote_as}")
    if data.description:
        config_commands.append(f"  neighbor {data.neighbor_ip} description {data.description}")
    if data.update_source:
        config_commands.append(f"  neighbor {data.neighbor_ip} update-source {data.update_source}")
    if data.ebgp_multihop:
        config_commands.append(f"  neighbor {data.neighbor_ip} ebgp-multihop {data.ebgp_multihop}")
    if data.password:
        config_commands.append(f"  neighbor {data.neighbor_ip} password {data.password}")
    if data.route_reflector_client is True:
        config_commands.append(f"  neighbor {data.neighbor_ip} route-reflector-client")
    elif data.route_reflector_client is False:
        config_commands.append(f"  no neighbor {data.neighbor_ip} route-reflector-client")
    
    return config_commands, None


def _generate_bgp_networks_config(local_as: int, networks: list, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate deterministic IPv4 BGP network advertisements."""
    if platform not in ("eos", "arista_eos"):
        return [], f"BGP network advertisement not supported for platform: {platform}"
    if not local_as:
        return [], "local_as is required for BGP network advertisements"

    config_commands = ["ip routing", f"router bgp {local_as}"]
    for item in networks:
        network = getattr(item, "network", None)
        if network:
            config_commands.append(f"  network {network}")
    return config_commands, None


def _generate_evpn_peer_config(data: EVPNPeerConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate EVPN Peer configuration commands based on platform."""
    config_commands = []
    
    if platform in ["eos", "arista_eos"]:
        if not data.local_as:
            return [], "local_as is required for Arista platforms"
        config_commands.append(f"router bgp {data.local_as}")
        config_commands.append("  address-family evpn")
        if data.activate:
            config_commands.append(f"    neighbor {data.neighbor_ip} activate")
        else:
            config_commands.append(f"    no neighbor {data.neighbor_ip} activate")
            
        route_reflector_client = getattr(data, "route_reflector_client", None)
        if route_reflector_client is True:
            config_commands.append(f"    neighbor {data.neighbor_ip} route-reflector-client")
        elif route_reflector_client is False:
            config_commands.append(f"    no neighbor {data.neighbor_ip} route-reflector-client")
            
        config_commands.append(f"router bgp {data.local_as}")
        if data.send_community_extended:
            config_commands.append(f"  neighbor {data.neighbor_ip} send-community extended")
        else:
            config_commands.append(f"  no neighbor {data.neighbor_ip} send-community extended")
    else:
        return [], f"EVPN peer configuration not supported for platform: {platform}"
    
    return config_commands, None

def _generate_vlan_vni_mapping_config(data: VLAN_VNIMappingModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate VLAN to VNI mapping commands based on platform."""
    config_commands = []
    
    if platform in ["eos", "arista_eos"]:
        config_commands.append(f"vlan {data.vlan_id}")
        config_commands.append("interface Vxlan1")
        config_commands.append(f"  vxlan vlan {data.vlan_id} vni {data.vni}")
    else:
        return [], f"VLAN to VNI mapping not supported for platform: {platform}"
    
    return config_commands, None

def _generate_interface_config(data: InterfaceConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate interface configuration commands for Arista EOS."""
    config_commands = []
    
    if platform not in ["eos", "arista_eos"]:
        return [], f"Interface configuration not supported for platform: {platform}"
    
    config_commands.append(f"interface {data.interface_name}")
    
    if data.description:
        config_commands.append(f"  description {data.description}")
    
    # Preserve any MTU explicitly requested by the intent instead of assuming
    # that the platform default already matches it.
    if data.mtu is not None:
        config_commands.append(f"  mtu {data.mtu}")
    
    # Switchport vs routed mode
    if data.switchport_mode == "access":
        config_commands.append("  switchport mode access")
        if data.access_vlan:
            config_commands.append(f"  switchport access vlan {data.access_vlan}")
    elif data.switchport_mode == "trunk":
        config_commands.append("  switchport mode trunk")
        if data.trunk_allowed_vlans:
            config_commands.append(f"  switchport trunk allowed vlan {data.trunk_allowed_vlans}")
    elif data.switchport_mode is None and data.ip_address:
        # Routed interface — ensure ip routing is enabled globally
        config_commands.insert(0, "ip routing")
        config_commands.append("  no switchport")
        config_commands.append(f"  ip address {data.ip_address}")
    
    if data.shutdown is True:
        config_commands.append("  shutdown")
    elif data.shutdown is False:
        config_commands.append("  no shutdown")
    
    return config_commands, None

def _generate_acl_config(data, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate IPv4 ACL commands for Arista EOS."""
    if platform not in ["eos", "arista_eos"]:
        return [], f"ACL configuration not supported for platform: {platform}"

    config_commands = [f"ip access-list {data.name}"]
    for rule in sorted(data.rules, key=lambda item: item.sequence):
        config_commands.append(
            f"  {rule.sequence} {rule.action} {rule.protocol} {rule.src} {rule.dst}"
        )

    return config_commands, None

def _generate_interface_acl_attachment_config(data, platform: str) -> tuple[list[str], Optional[str]]:
    """Attach an IPv4 ACL to an interface."""
    if platform not in ["eos", "arista_eos"]:
        return [], f"Interface ACL attachment not supported for platform: {platform}"

    return [
        f"interface {data.interface_name}",
        f"  ip access-group {data.acl_name} {data.direction}",
    ], None

def _generate_vrf_config(data: VRFConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate VRF configuration with optional L3VNI for Arista EOS.
    
    VRF creation requires:
    1. 'vrf instance X' — create the VRF
    2. 'ip routing vrf X' — enable routing in the VRF
    3. 'interface Vxlan1 / vxlan vrf X vni Y' — L3VNI mapping (if l3vni set)
    """
    config_commands = []
    
    if platform not in ["eos", "arista_eos"]:
        return [], f"VRF configuration not supported for platform: {platform}"
    
    # Create VRF instance
    config_commands.append(f"vrf instance {data.vrf_name}")
    
    # Enable IP routing for this VRF
    config_commands.append(f"ip routing vrf {data.vrf_name}")
    
    # If L3VNI is specified, map it in the Vxlan1 interface
    if data.l3vni:
        config_commands.append("interface Vxlan1")
        config_commands.append(f"  vxlan vrf {data.vrf_name} vni {data.l3vni}")
    
    # If RD/RT specified, configure under router bgp
    if data.rd or data.rt_import or data.rt_export:
        # VRFConfigModel has no local_as; bulk configuration handles BGP VRF RD/RT.
        pass
    
    return config_commands, None

def _generate_svi_config(data: SVIConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate SVI (VLAN interface) with anycast gateway for Arista EOS.
    
    Arista cEOS 4.34.3.1M addressing:
    - When a VRF is specified, use 'ip address virtual X.X.X.X/Y'
      instead of 'ip address' + 'ip virtual-router address'.
    - cEOS forbids mixing 'ip address' (physical) and 'ip address virtual'
      on the same SVI; VRF-bound SVIs therefore use virtual addressing only.
    - 'ip virtual-router mac-address' is still set globally (required once).
    """
    config_commands = []
    
    if platform not in ["eos", "arista_eos"]:
        return [], f"SVI configuration not supported for platform: {platform}"
    
    if data.virtual_ip and data.anycast_mac:
        config_commands.append(f"ip virtual-router mac-address {data.anycast_mac}")

    config_commands.append(f"interface Vlan{data.vlan_id}")
    
    if data.description:
        config_commands.append(f"  description {data.description}")
    
    if data.vrf:
        # VRF must be assigned before any IP configuration
        config_commands.append(f"  vrf {data.vrf}")
    
    if data.vrf and data.virtual_ip:
        # Multi-tenant path: use 'ip address virtual'.
        # The virtual_ip may or may not have a mask; ensure it does
        vip = data.virtual_ip
        if "/" not in vip:
            # Derive mask from ip_address if provided, otherwise default /24
            if data.ip_address and "/" in data.ip_address:
                mask = data.ip_address.split("/")[1]
                vip = f"{vip}/{mask}"
            else:
                vip = f"{vip}/24"
        config_commands.append(f"  ip address virtual {vip}")
    else:
        # Single-tenant / legacy path: physical IP + virtual-router address
        if data.ip_address:
            config_commands.append(f"  ip address {data.ip_address}")
        
        if data.virtual_ip:
            config_commands.append(f"  ip virtual-router address {data.virtual_ip}")
    
    if data.mtu:
        config_commands.append(f"  mtu {data.mtu}")
        
    config_commands.append("  no shutdown")
    
    return config_commands, None

def _generate_evpn_rd_rt_config(data: EVPNRdRtConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate EVPN RD/RT configuration per VLAN for Arista EOS."""
    config_commands = []
    
    if platform not in ["eos", "arista_eos"]:
        return [], f"EVPN RD/RT configuration not supported for platform: {platform}"
    
    config_commands.append(f"router bgp {data.local_as}")
    config_commands.append(f"  vlan {data.vlan_id}")
    config_commands.append(f"    rd {data.rd}")
    
    if data.both:
        config_commands.append(f"    route-target both {data.both}")
    else:
        if data.rt_import:
            config_commands.append(f"    route-target import {data.rt_import}")
        if data.rt_export:
            config_commands.append(f"    route-target export {data.rt_export}")
    
    config_commands.append(f"    redistribute learned")
    
    return config_commands, None

def _generate_mlag_config(data: MLAGConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate MLAG configuration for Arista EOS."""
    config_commands = []
    
    if platform not in ["eos", "arista_eos"]:
        return [], f"MLAG configuration not supported for platform: {platform}"
    
    config_commands.append("mlag configuration")
    config_commands.append(f"  domain-id {data.domain_id}")
    config_commands.append(f"  local-interface {data.local_interface}")
    config_commands.append(f"  peer-address {data.peer_address}")
    config_commands.append(f"  peer-link {data.peer_link}")
    
    if data.reload_delay_mlag is not None:
        config_commands.append(f"  reload-delay mlag {data.reload_delay_mlag}")
    if data.reload_delay_non_mlag is not None:
        config_commands.append(f"  reload-delay non-mlag {data.reload_delay_non_mlag}")
    
    return config_commands, None

def _generate_vxlan_delete_config(data: VXLANDeleteModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate VXLAN deletion commands for Arista EOS."""
    config_commands = []

    if platform not in ("eos", "arista_eos"):
        return [], f"VXLAN deletion not supported for platform: {platform}"

    if data.local_as is not None and not data.cleanup_vlan:
        return [], (
            "local_as is only used when cleanup_vlan=true; set cleanup_vlan=true "
            "for full tenant cleanup or omit local_as for mapping-only removal"
        )
    if data.cleanup_vlan and not data.vlan_id:
        return [], "vlan_id is required when cleanup_vlan=true"
    if data.cleanup_vlan and not data.local_as:
        return [], "local_as is required when cleanup_vlan=true so the stale BGP EVPN VLAN stanza can be removed"

    if data.vlan_id:
        if data.cleanup_vlan and data.local_as:
            config_commands.append(f"router bgp {data.local_as}")
            config_commands.append(f"  no vlan {data.vlan_id}")

        config_commands.append("interface Vxlan1")
        for vtep in data.flood_vteps or []:
            config_commands.append(f"  no vxlan vlan {data.vlan_id} flood vtep {vtep}")
        config_commands.append(f"  no vxlan vlan {data.vlan_id} vni {data.vni}")

        # Keep the legacy form as a harmless fallback for configs created as raw VNI mappings.
        config_commands.append(f"  no vxlan vni {data.vni}")

        if data.cleanup_vlan:
            config_commands.append(f"no interface Vlan{data.vlan_id}")
            config_commands.append(f"no vlan {data.vlan_id}")
    else:
        config_commands.append("interface Vxlan1")
        config_commands.append(f"  no vxlan vni {data.vni}")
    
    return config_commands, None


def _generate_bgp_delete_config(data: BGPNeighborDeleteModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate BGP neighbor deletion commands for Arista EOS."""
    config_commands = []

    if platform not in ("eos", "arista_eos"):
        return [], f"BGP neighbor deletion not supported for platform: {platform}"

    if not data.local_as:
        return [], "local_as is required for Arista platforms"
    config_commands.append(f"router bgp {data.local_as}")
    config_commands.append(f"  no neighbor {data.neighbor_ip}")
    
    return config_commands, None


def _generate_ospf_config(data: OSPFConfigModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate OSPF configuration commands for Arista EOS."""
    config_commands = []
    passive_default_error = _validate_ospf_passive_default(data)
    if passive_default_error:
        return [], passive_default_error

    if platform not in ("eos", "arista_eos"):
        return [], f"OSPF configuration not supported for platform: {platform}"

    # Arista cEOS has 'no ip routing' by default; OSPF requires it.
    config_commands.append("ip routing")
    config_commands.append(f"router ospf {data.process_id}")

    if data.router_id:
        config_commands.append(f"  router-id {data.router_id}")

    if data.passive_default:
        config_commands.append("  passive-interface default")

    if data.max_lsa:
        config_commands.append(f"  max-lsa {data.max_lsa}")

    if data.default_originate:
        config_commands.append("  default-information originate")

    if data.redistribute:
        for proto in data.redistribute:
            config_commands.append(f"  redistribute {proto}")

    if data.networks:
        for net in data.networks:
            network = net.get("network", "")
            area = net.get("area", "0.0.0.0")
            if "/" in network:
                import ipaddress
                iface = ipaddress.ip_network(network, strict=False)
                wildcard = str(iface.hostmask)
                net_addr = str(iface.network_address)
                config_commands.append(f"  network {net_addr} {wildcard} area {area}")
            else:
                config_commands.append(f"  network {network} area {area}")

    if data.interfaces:
        for iface in data.interfaces:
            name = iface.get("name")
            area = iface.get("area", "0.0.0.0")
            network_type = iface.get("network_type")
            cost = iface.get("cost")
            passive = iface.get("passive", False)

            # Safety Guard: P2P links MUST NOT be passive to form adjacencies.
            if network_type == "point-to-point" and passive:
                logger.warning(f"[Safety] OSPF interface {name} on {platform} is P2P but marked passive. Forcing passive=False.")
                passive = False

            config_commands.append(f"interface {name}")
            config_commands.append(f"  ip ospf area {area}")
            if network_type:
                config_commands.append("  ip ospf network point-to-point")
            if cost:
                config_commands.append(f"  ip ospf cost {cost}")

            if passive:
                config_commands.append(f"router ospf {data.process_id}")
                config_commands.append(f"  passive-interface {name}")
            elif data.passive_default:
                config_commands.append(f"router ospf {data.process_id}")
                config_commands.append(f"  no passive-interface {name}")

    return config_commands, None


def _generate_ospf_delete_config(data: OSPFDeleteModel, platform: str) -> tuple[list[str], Optional[str]]:
    """Generate OSPF deletion commands for Arista EOS."""
    config_commands = []

    if platform not in ("eos", "arista_eos"):
        return [], f"OSPF deletion not supported for platform: {platform}"

    if data.network and data.area:
        import ipaddress
        if "/" in data.network:
            iface = ipaddress.ip_network(data.network, strict=False)
            wildcard = str(iface.hostmask)
            net_addr = str(iface.network_address)
            config_commands.append(f"router ospf {data.process_id}")
            config_commands.append(f"  no network {net_addr} {wildcard} area {data.area}")
        else:
            config_commands.append(f"router ospf {data.process_id}")
            config_commands.append(f"  no network {data.network} area {data.area}")
    else:
        config_commands.append(f"no router ospf {data.process_id}")

    return config_commands, None


def _sanitize_payload(payload):
    """Remove null values and empty lists recursively to optimize token usage."""
    if isinstance(payload, dict):
        return {
            k: _sanitize_payload(v) 
            for k, v in payload.items() 
            if v is not None and v != []
        }
    elif isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload if item is not None and item != []]
    return payload


def _get_device_fabric_role(device_name: str, nr_mgr) -> Optional[str]:
    """Get fabric_role from device's group membership in Nornir inventory."""
    try:
        host = nr_mgr.nr.filter(name=device_name)
        if not host.inventory.hosts:
            return None
        host_obj = host.inventory.hosts[device_name]
        
        # Check host data first
        if host_obj.data and 'fabric_role' in host_obj.data:
            return host_obj.data['fabric_role']
            
        # Check groups
        for group_name in host_obj.groups:
            group_obj = nr_mgr.nr.inventory.groups.get(group_name) if isinstance(group_name, str) else group_name
            if group_obj and hasattr(group_obj, 'data') and group_obj.data:
                role = group_obj.data.get('fabric_role')
                if role:
                    return role
        return None
    except Exception:
        return None


def _is_routed_fabric_interface(iface) -> bool:
    """Return True for routed Ethernet links that should participate in underlay."""
    name = (getattr(iface, "interface_name", "") or "").lower()
    if not name.startswith("ethernet"):
        return False
    if not getattr(iface, "ip_address", None):
        return False
    return not getattr(iface, "switchport_mode", None)


def _validate_underlay_bulk_completeness(payloads: list[DeviceBulkConfigModel]) -> Optional[dict]:
    """Block partial Phase-1 underlay payloads before command generation."""
    has_underlay_routing = any(bool(payload.ospf) or bool(payload.bgp_neighbors) for payload in payloads)
    has_overlay_or_dataplane = any(
        bool(payload.evpn_peers)
        or bool(payload.evpn_rd_rt)
        or bool(payload.vlans)
        or bool(payload.vxlan)
        or bool(payload.svis)
        for payload in payloads
    )
    if not has_underlay_routing or has_overlay_or_dataplane:
        return None

    missing_underlay = []
    for payload in payloads:
        has_fabric_links = any(
            _is_routed_fabric_interface(iface)
            for iface in (payload.interfaces or [])
        )
        if has_fabric_links and not (payload.ospf or payload.bgp_neighbors):
            missing_underlay.append(payload.device_name)

    if not missing_underlay:
        return None

    return {
        "success": False,
        "error_type": "IncompleteUnderlayPayload",
        "failed_devices": missing_underlay,
        "result": (
            "Phase 1 underlay payload is incomplete: devices with routed fabric "
            "Ethernet interfaces must include an underlay routing protocol. Add "
            "either ospf[] or bgp_neighbors[]/bgp_networks[] for every listed "
            "underlay device."
        ),
        "action_required": "Fix the Phase 1 configure_fabric_bulk payload and retry dry_run. Do not apply a partial underlay.",
    }


def _rt_values(evpn_config) -> list[str]:
    values = []
    if getattr(evpn_config, "both", None):
        values.append(evpn_config.both)
    if getattr(evpn_config, "rt_import", None):
        values.append(evpn_config.rt_import)
    if getattr(evpn_config, "rt_export", None):
        values.append(evpn_config.rt_export)
    return [value for value in values if value]


def _rt_policy(config) -> tuple[set[str], set[str]]:
    """Return normalized (imports, exports) for an EVPN service object."""
    both = {config.both.strip()} if getattr(config, "both", None) else set()
    imports = set(both)
    exports = set(both)
    if getattr(config, "rt_import", None):
        imports.add(config.rt_import.strip())
    if getattr(config, "rt_export", None):
        exports.add(config.rt_export.strip())
    return imports, exports


def _validate_fabric_rt_compatibility(payloads: list[DeviceBulkConfigModel]) -> Optional[dict]:
    """Validate mutual RT import/export for devices in one EVPN service.

    The concrete RT remains a design choice. This guard only enforces that
    participants configured together for one L2VNI or L3VNI can import each
    other's exports. Partial and single-device transactions remain valid.
    """
    services = {}

    for payload in payloads:
        vlan_to_vni = {vlan.vlan_id: vlan.vni for vlan in (payload.vlans or [])}
        for config in payload.evpn_rd_rt or []:
            vni = vlan_to_vni.get(config.vlan_id)
            if vni is None:
                continue
            imports, exports = _rt_policy(config)
            policy = services.setdefault(("l2vni", vni), {}).setdefault(
                payload.device_name, {"imports": set(), "exports": set()}
            )
            policy["imports"].update(imports)
            policy["exports"].update(exports)

        for config in payload.vrfs or []:
            if config.l3vni is None:
                continue
            imports, exports = _rt_policy(config)
            policy = services.setdefault(("l3vni", config.l3vni), {}).setdefault(
                payload.device_name, {"imports": set(), "exports": set()}
            )
            policy["imports"].update(imports)
            policy["exports"].update(exports)

    for (service_type, vni), device_policies in services.items():
        complete = {
            device: policy
            for device, policy in device_policies.items()
            if policy["imports"] and policy["exports"]
        }
        devices = sorted(complete)
        for index, left_device in enumerate(devices):
            left = complete[left_device]
            for right_device in devices[index + 1:]:
                right = complete[right_device]
                if (
                    left["exports"] & right["imports"]
                    and right["exports"] & left["imports"]
                ):
                    continue
                return {
                    "success": False,
                    "error_type": "IncompatibleRouteTargets",
                    "service": {"type": service_type, "vni": vni},
                    "failed_devices": [left_device, right_device],
                    "result": (
                        f"EVPN {service_type} {vni} has incompatible route-target "
                        f"import/export policy between {left_device} and {right_device}."
                    ),
                    "details": {
                        left_device: {
                            "imports": sorted(left["imports"]),
                            "exports": sorted(left["exports"]),
                        },
                        right_device: {
                            "imports": sorted(right["imports"]),
                            "exports": sorted(right["exports"]),
                        },
                    },
                    "action_required": (
                        "Use mutually compatible import/export route-targets for every "
                        "device in the same EVPN service, then repeat dry-run."
                    ),
                }

    return None


def _rt_suffix(value: str) -> str:
    return value.rsplit(":", 1)[-1] if ":" in value else value


def _validate_symmetric_irb_rd_rt_separation(data: DeviceBulkConfigModel, local_as: Optional[int]) -> Optional[str]:
    """Keep L2 MAC-VRF RD/RT separate from L3 IP-VRF RD/RT.

    The bulk schema exposes both evpn_rd_rt[] for VLAN/L2VNI and vrfs[] for
    L3VNI. For Symmetric IRB they must not share the same RD/RT values.
    """
    if not data.vrfs or not data.evpn_rd_rt:
        return None

    l3vnis = {str(vrf.l3vni) for vrf in data.vrfs if vrf.l3vni}
    vrf_rds = {vrf.rd for vrf in data.vrfs if vrf.rd}
    vrf_rts = {
        rt
        for vrf in data.vrfs
        for rt in (vrf.rt_import, vrf.rt_export)
        if rt
    }

    for evpn in data.evpn_rd_rt:
        if evpn.rd in vrf_rds:
            return (
                f"Invalid Symmetric IRB RD/RT separation on {data.device_name}: "
                f"VLAN {evpn.vlan_id} uses RD {evpn.rd}, which is already used by an IP-VRF. "
                "Use a MAC-VRF/L2 RD for the VLAN (for example loopback:VLAN or loopback:L2VNI) "
                "and keep the L3VNI RD under vrfs[]."
            )

        if evpn.rd and _rt_suffix(evpn.rd) in l3vnis:
            return (
                f"Invalid Symmetric IRB RD on {data.device_name}: VLAN {evpn.vlan_id} RD {evpn.rd} "
                "uses an L3VNI value. VLAN evpn_rd_rt[] is for the MAC-VRF/L2VNI; "
                "put L3VNI RD/RT values under vrfs[]."
            )

        for rt in _rt_values(evpn):
            if rt in vrf_rts or _rt_suffix(rt) in l3vnis:
                return (
                    f"Invalid Symmetric IRB route-target on {data.device_name}: VLAN {evpn.vlan_id} "
                    f"uses RT {rt}, which belongs to an IP-VRF/L3VNI. "
                    "Use a MAC-VRF/L2 route-target for the VLAN "
                    "and keep the L3VNI route-target under vrfs[]."
                )

    return None


def _validate_symmetric_irb_completeness(data: DeviceBulkConfigModel, local_as: Optional[int]) -> Optional[str]:
    """Reject incomplete EVPN/Symmetric IRB payloads before command generation."""
    if data.vxlan:
        for vxlan in data.vxlan:
            if vxlan.vlan_id is None:
                return (
                    f"Invalid VXLAN payload on {data.device_name}: VNI {vxlan.vni} is missing vlan_id. "
                    "Include vlan_id so the server can generate 'vxlan vlan <vlan_id> vni <vni>'."
                )

    if data.evpn_rd_rt:
        for evpn in data.evpn_rd_rt:
            if local_as and evpn.local_as and evpn.local_as != local_as:
                return (
                    f"Invalid EVPN RD/RT payload on {data.device_name}: VLAN {evpn.vlan_id} "
                    f"uses local_as {evpn.local_as}, but device local_as is {local_as}. "
                    "Use the device BGP AS for local_as; route-target namespaces belong in rt_import/rt_export."
                )
            if not (evpn.local_as or local_as):
                return (
                    f"Invalid EVPN RD/RT payload on {data.device_name}: VLAN {evpn.vlan_id} is missing local_as. "
                    "Set device-level local_as or evpn_rd_rt[].local_as so the server can configure router bgp."
                )

    vrfs = data.vrfs or []
    svis_with_vrf = [svi for svi in (data.svis or []) if svi.vrf]
    has_l3vni = any(vrf.l3vni for vrf in vrfs)
    is_symmetric_irb = bool(vrfs and has_l3vni and (svis_with_vrf or data.evpn_rd_rt))
    if not is_symmetric_irb:
        return None

    vrf_names = {vrf.vrf_name for vrf in vrfs}
    for svi in svis_with_vrf:
        if svi.vrf not in vrf_names:
            return (
                f"Invalid Symmetric IRB payload on {data.device_name}: SVI Vlan{svi.vlan_id} "
                f"references VRF {svi.vrf}, but that VRF is not present in vrfs[]."
            )

    for vrf in vrfs:
        if local_as and vrf.local_as and vrf.local_as != local_as:
            return (
                f"Invalid Symmetric IRB payload on {data.device_name}: VRF {vrf.vrf_name} "
                f"uses local_as {vrf.local_as}, but device local_as is {local_as}. "
                "Use the device BGP AS for local_as; route-target namespaces belong in rt_import/rt_export."
            )
        missing = []
        if not vrf.l3vni:
            missing.append("l3vni")
        if not (vrf.local_as or local_as):
            missing.append("local_as")
        if not vrf.rd:
            missing.append("rd")
        if not vrf.rt_import:
            missing.append("rt_import")
        if not vrf.rt_export:
            missing.append("rt_export")
        if missing:
            return (
                f"Invalid Symmetric IRB payload on {data.device_name}: VRF {vrf.vrf_name} "
                f"is missing {', '.join(missing)}. Include complete L3VNI RD/RT and local AS context."
            )

    vlan_to_vni = {vlan.vlan_id: vlan.vni for vlan in (data.vlans or [])}
    for evpn in data.evpn_rd_rt or []:
        l2vni = vlan_to_vni.get(evpn.vlan_id)
        if not l2vni:
            return (
                f"Invalid Symmetric IRB payload on {data.device_name}: evpn_rd_rt[] for VLAN {evpn.vlan_id} "
                "requires a matching vlans[] entry with the L2VNI in the same payload."
            )

    return None


def _generate_bulk_config(data: DeviceBulkConfigModel, platform: str, fabric_role: Optional[str] = None) -> tuple[list[str], Optional[str]]:
    """Generate bulk configuration commands by aggregating single commands.
    
    Args:
        data: DeviceBulkConfigModel with configuration payload
        platform: Target platform. This project currently supports Arista EOS/cEOS.
        fabric_role: Device role from inventory ('spine', 'leaf', 'gateway', etc.)
                     If 'spine', VXLAN/VLAN/RD/RT/SVI fields are silently ignored.
    """
    all_commands = []
    is_spine = fabric_role == 'spine'

    # Resolve global_local_as before any feature block uses it.
    global_local_as = getattr(data, 'local_as', None)
    if not global_local_as and data.bgp_neighbors:
        for bgp in data.bgp_neighbors:
            if bgp.local_as:
                global_local_as = bgp.local_as
                break

    if not is_spine:
        semantic_error = _validate_symmetric_irb_completeness(data, global_local_as)
        if semantic_error:
            return [], semantic_error
        semantic_error = _validate_symmetric_irb_rd_rt_separation(data, global_local_as)
        if semantic_error:
            return [], semantic_error

    if data.interfaces:
        vlan_ids_present = {v.vlan_id for v in (data.vlans or [])}
        is_from_scratch_phase1 = bool(data.ospf or data.bgp_neighbors) and bool(data.interfaces) and not bool(data.vlans)
        for iface in data.interfaces:
            # [Phase-Guard] Block access ports when the VLAN is not in the same payload.
            # This prevents accidental Phase-1 access port configs before VLANs exist.
            if (is_from_scratch_phase1 and iface.switchport_mode == "access"
                    and iface.access_vlan
                    and iface.access_vlan not in vlan_ids_present):
                logger.warning(
                    f"[Phase-Guard] {data.device_name}: Interface {iface.interface_name} "
                    f"requests access VLAN {iface.access_vlan} but VLAN not in payload. "
                    f"Skipping access port - configure in Phase 3 with VLANs."
                )
                # [Deferred-Guard] Queue the blocked port for Phase 3 injection
                deferred_entry = {
                    "interface_name": iface.interface_name,
                    "switchport_mode": "access",
                    "access_vlan": iface.access_vlan,
                    "description": iface.description,
                }
                device_deferred = _deferred_access_ports.setdefault(data.device_name, [])
                if not any(
                    entry.get("interface_name") == deferred_entry["interface_name"]
                    and entry.get("access_vlan") == deferred_entry["access_vlan"]
                    for entry in device_deferred
                ):
                    device_deferred.append(deferred_entry)
                logger.info(
                    f"[Deferred-Guard] {data.device_name}: Queued {iface.interface_name} "
                    f"(VLAN {iface.access_vlan}) for auto-injection in Phase 3"
                )
                iface.switchport_mode = None
                iface.access_vlan = None
            cmds, err = _generate_interface_config(iface, platform)
            if err: return [], err
            all_commands.extend(cmds)

    if data.bgp_networks:
        cmds, err = _generate_bgp_networks_config(global_local_as, data.bgp_networks, platform)
        if err: return [], err
        all_commands.extend(cmds)

    # [Deferred-Guard] Phase 3 injection: if this payload has VLANs and we have queued
    # access ports for this device (from a Phase-Guard block in Phase 1), inject them now.
    if not is_spine and data.vlans and data.device_name in _deferred_access_ports:
        if data.mode in [ConfigMode.DRY_RUN, ConfigMode.PREVIEW]:
            deferred = _deferred_access_ports.get(data.device_name)
        else:
            deferred = _deferred_access_ports.pop(data.device_name)
            
        if deferred:
            if data.interfaces is None:
                data.interfaces = []
                
            for deferred_iface_dict in deferred:
                from validation_models import InterfaceDetailModel
                deferred_iface = InterfaceDetailModel(**{k: v for k, v in deferred_iface_dict.items() if v is not None})
                
                data.interfaces.append(deferred_iface)
                
                logger.info(
                    f"[Deferred-Guard] {data.device_name}: Auto-injecting deferred port "
                    f"{deferred_iface.interface_name} (VLAN {deferred_iface.access_vlan}) into Phase 3"
                )
                cmds, err = _generate_interface_config(deferred_iface, platform)
                if err:
                    logger.warning(f"[Deferred-Guard] Failed to generate config for {deferred_iface.interface_name}: {err}")
                else:
                    all_commands.extend(cmds)

    if data.acls:
        for acl in data.acls:
            cmds, err = _generate_acl_config(acl, platform)
            if err: return [], err
            all_commands.extend(cmds)

    if data.interface_acls:
        for attachment in data.interface_acls:
            cmds, err = _generate_interface_acl_attachment_config(attachment, platform)
            if err: return [], err
            all_commands.extend(cmds)

    # --- VRF processing (Symmetric IRB / Multi-Tenant) ---
    # VRFs need vrf instance, ip routing vrf, L3VNI mapping,
    # and BGP VRF blocks with rd/rt/redistribute connected.
    if not is_spine and data.vrfs:
        for vrf in data.vrfs:
            # 1. VRF instance + ip routing vrf
            all_commands.append(f"vrf instance {vrf.vrf_name}")
            all_commands.append(f"ip routing vrf {vrf.vrf_name}")

            # 2. L3VNI mapping on Vxlan1
            if vrf.l3vni:
                all_commands.append("interface Vxlan1")
                all_commands.append(f"  vxlan vrf {vrf.vrf_name} vni {vrf.l3vni}")

            # 3. BGP VRF block (rd, rt, redistribute)
            vrf_as = vrf.local_as or global_local_as
            if vrf_as and (vrf.rd or vrf.rt_import or vrf.rt_export):
                all_commands.append(f"router bgp {vrf_as}")
                all_commands.append(f"  vrf {vrf.vrf_name}")
                if vrf.rd:
                    all_commands.append(f"    rd {vrf.rd}")
                if vrf.rt_import:
                    all_commands.append(f"    route-target import evpn {vrf.rt_import}")
                if vrf.rt_export:
                    all_commands.append(f"    route-target export evpn {vrf.rt_export}")
                if vrf.redistribute_connected:
                    all_commands.append(f"    redistribute connected")

    # Only process VXLAN/VLAN on leaves, not spines/RRs
    if not is_spine and data.vlans:
        for vlan in data.vlans:
            cmds, err = _generate_vlan_vni_mapping_config(vlan, platform)
            if err: return [], err
            all_commands.extend(cmds)

    # Only process SVIs on leaves, not spines
    if not is_spine and data.svis:
        for svi in data.svis:
            cmds, err = _generate_svi_config(svi, platform)
            if err: return [], err
            all_commands.extend(cmds)

    if data.ospf:
        # [OSPF-Guard] Extract Loopback IPs from interfaces and ensure they are advertised in OSPF.
        loopback_networks = []
        if data.interfaces:
            for iface in data.interfaces:
                if iface.interface_name.lower().startswith("loopback") and iface.ip_address:
                    ip_str = iface.ip_address.strip()
                    if "/" not in ip_str:
                        ip_str += "/32"
                    loopback_networks.append({"network": ip_str, "area": "0.0.0.0"})

        for o in data.ospf:
            if loopback_networks:
                if not o.networks:
                    o.networks = []
                existing_nets = {net.get("network") for net in o.networks if isinstance(net, dict)}
                for lb_net in loopback_networks:
                    if lb_net["network"] not in existing_nets:
                        logger.info(
                            f"[OSPF-Guard] {data.device_name}: Auto-injecting Loopback {lb_net['network']} into OSPF networks"
                        )
                        o.networks.append(lb_net)

            cmds, err = _generate_ospf_config(o, platform)
            if err: return [], err
            all_commands.extend(cmds)

    if data.bgp_neighbors:
        evpn_peer_ips = {p.neighbor_ip for p in (data.evpn_peers or [])}
        neighbor_remote_as = {}
        for bgp in data.bgp_neighbors:
            # Propagate device-level local_as if neighbor doesn't have its own
            if not bgp.local_as and global_local_as:
                bgp.local_as = global_local_as
            neighbor_remote_as[bgp.neighbor_ip] = bgp.remote_as
            
            # Strip ebgp_multihop for iBGP sessions (same AS)
            if bgp.local_as and bgp.remote_as and bgp.local_as == bgp.remote_as:
                bgp.ebgp_multihop = None

            # [RR-Guard] Only force RR client for iBGP EVPN designs. eBGP EVPN
            # overlays must not receive route-reflector-client automatically.
            is_ibgp_evpn_peer = (
                is_spine
                and bgp.neighbor_ip in evpn_peer_ips
                and bgp.local_as
                and bgp.remote_as
                and bgp.local_as == bgp.remote_as
            )
            if is_ibgp_evpn_peer and bgp.route_reflector_client is not True:
                logger.info(
                    f"[RR-Guard] Spine {data.device_name}: forcing route_reflector_client=True "
                    f"for IPv4 peer {bgp.neighbor_ip} (was: {bgp.route_reflector_client})"
                )
                bgp.route_reflector_client = True
                
            cmds, err = _generate_bgp_config(bgp, platform)
            if err: return [], err
            all_commands.extend(cmds)

    if data.evpn_peers:
        for evpn in data.evpn_peers:
            if not evpn.local_as and global_local_as:
                evpn.local_as = global_local_as
                
            remote_as = neighbor_remote_as.get(evpn.neighbor_ip) if data.bgp_neighbors else None
            is_ibgp_evpn_peer = (
                is_spine
                and evpn.local_as
                and remote_as
                and evpn.local_as == remote_as
            )
            # [RR-Guard] Also inject into EVPN peer config for iBGP RR designs only.
            if is_ibgp_evpn_peer and evpn.route_reflector_client is not True:
                logger.info(
                    f"[RR-Guard] Spine {data.device_name}: forcing route_reflector_client=True "
                    f"for EVPN peer {evpn.neighbor_ip} (was: {evpn.route_reflector_client})"
                )
                evpn.route_reflector_client = True
                
            cmds, err = _generate_evpn_peer_config(evpn, platform)
            if err: return [], err
            all_commands.extend(cmds)

    if data.evpn_rd_rt:
        for config in data.evpn_rd_rt:
            if not config.local_as and global_local_as:
                config.local_as = global_local_as
                
            # Skip RD/RT config on spines - only needed on VTEPs (leaves)
            if is_spine:
                continue
                
            cmds, err = _generate_evpn_rd_rt_config(config, platform)
            if err: return [], err
            all_commands.extend(cmds)

    if data.vxlan:
        for lx in data.vxlan:
            # Skip VXLAN config on spines - only needed on VTEPs (leaves)
            if is_spine:
                continue
                
            cmds, err = _generate_vxlan_config(lx, platform)
            if err: return [], err
            all_commands.extend(cmds)


    # Deduplicate "ip routing" if it appeared multiple times (optional, but harmless)
    filtered = []
    ip_routing_seen = False
    for cmd in all_commands:
        if cmd.strip() == "ip routing":
            if ip_routing_seen:
                continue
            ip_routing_seen = True
        filtered.append(cmd)

    return filtered, None


def _recover_nornir_failed_host(nr_mgr, device_name: str) -> None:
    """Allow a targeted apply after a previous read task marked the host failed."""
    try:
        nr_mgr.recover_failed_hosts([device_name])
    except Exception as exc:
        logger.warning("[Nornir] Could not recover failed host state for %s: %s", device_name, exc)


async def _apply_configuration_safely(
    nr_mgr,
    device_name: str,
    config_commands: list[str],
    mode: ConfigMode,
    operation_name: str
):
    """
    Apply configuration with safety checks.
    
    Returns a detailed response based on the mode:
    - dry_run: Shows commands without applying
    - preview: Shows commands and validates with diff
    - apply: Applies immediately
    """
    host = nr_mgr.nr.filter(name=device_name)
    if not host.inventory.hosts:
        return {
            "host": device_name,
            "success": False,
            "error_type": "InventoryError",
            "result": f"Device '{device_name}' not found.",
        }
    
    config_text = "\n".join(config_commands)
    
    # DRY_RUN mode: Just return what would be configured
    if mode == ConfigMode.DRY_RUN:
        # Register the intent in the Workflow Guard
        workflow_guard.register_dry_run(device_name, operation_name, config_commands)
        
        return {
            "host": device_name,
            "success": True,
            "mode": "dry_run",
            "operation": operation_name,
            "cmd_count": len(config_commands),
            # Keep the dry-run acknowledgement compact.
            "message": "DRY RUN OK - Intent registered. Proceed to 'apply' with EXACT same parameters.",
        }

    # Enforcement: mode APPLY or PREVIEW must have a preceding DRY_RUN
    if mode in [ConfigMode.APPLY, ConfigMode.PREVIEW]:
        if not workflow_guard.check_intent(device_name, operation_name, config_commands):
            return {
                "host": device_name,
                "success": False,
                "error_type": "WorkflowViolation",
                "result": f"CRITICAL WORKFLOW VIOLATION: No matching dry-run found for this configuration intent on {device_name}. "
                          f"Perform a 'dry_run' first with the exact parameters before applying.",
            }
        _recover_nornir_failed_host(nr_mgr, device_name)
    
    # PREVIEW mode: Get diff without applying
    if mode == ConfigMode.PREVIEW:
        from nornir_napalm.plugins.tasks import napalm_configure
        
        result = host.run(
            task=napalm_configure,
            configuration=config_text,
            replace=False,
            dry_run=True,  # NAPALM dry_run shows diff
            name=f"Preview: {operation_name}",
            raise_on_error=False,
        )
        
        formatted_result = nr_mgr._format_result(result, device_name)
        
        # Add preview-specific metadata
        formatted_result["mode"] = "preview"
        formatted_result["operation"] = operation_name
        # Omit config_commands on success to save LLM context tokens
        if formatted_result.get("success", False):
            formatted_result["message"] = "PREVIEW OK - Use mode='apply' to execute."
        else:
            formatted_result["config_commands"] = config_commands  # Keep on failure for debug
            formatted_result["message"] = f"PREVIEW FAILED - Error: {formatted_result.get('result', 'Unknown error')}"
        
        return formatted_result
    
    # APPLY mode: Apply immediately without rollback
    if mode == ConfigMode.APPLY:
        from nornir_napalm.plugins.tasks import napalm_configure
        
        result = host.run(
            task=napalm_configure,
            configuration=config_text,
            replace=False,
            name=f"Apply: {operation_name}",
            raise_on_error=False,
        )
        
        formatted_result = nr_mgr._format_result(result, device_name)
        formatted_result["mode"] = "apply"
        formatted_result["operation"] = operation_name
        # Omit config_commands on success to save LLM context tokens
        if formatted_result.get("success", False):
            formatted_result["message"] = "Applied OK."
        else:
            formatted_result["config_commands"] = config_commands  # Keep on failure for debug
            formatted_result["message"] = f"FAILED: {formatted_result.get('result', 'Unknown error')}"
        
        return formatted_result

    return {
        "host": device_name,
        "success": False,
        "error_type": "UnsupportedMode",
        "result": f"Unsupported configuration mode: {mode}",
    }


@mcp.tool()
async def delete_vxlan(data: VXLANDeleteModel):
    """Remove VXLAN VNI config from device. For EOS VLAN-to-VNI mappings, pass vlan_id; for tenant migrations, cleanup_vlan=true also removes stale BGP EVPN VLAN, SVI, and VLAN config. Safety modes: dry_run(default), preview, apply."""
    logger.info(f"[Tool] delete_vxlan called for {data.device_name} - VNI {data.vni} (mode={data.mode})")
    
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "InventoryError",
            "result": f"Device '{data.device_name}' not found.",
        }
    
    device_platform = host.inventory.hosts[data.device_name].platform
    
    config_commands, error = _generate_vxlan_delete_config(data, device_platform)
    
    if error:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "UnsupportedPlatform",
            "result": error,
        }
    
    return await _apply_configuration_safely(
        nr_mgr=nr_mgr,
        device_name=data.device_name,
        config_commands=config_commands,
        mode=data.mode,
        operation_name=f"Delete VXLAN VNI {data.vni}",
    )


@mcp.tool()
async def delete_bgp_neighbor(data: BGPNeighborDeleteModel):
    """Remove a BGP neighbor from device. Safety modes: dry_run(default), preview, apply."""
    logger.info(f"[Tool] delete_bgp_neighbor called for {data.device_name} - neighbor {data.neighbor_ip} (mode={data.mode})")
    
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "InventoryError",
            "result": f"Device '{data.device_name}' not found.",
        }
    
    device_platform = host.inventory.hosts[data.device_name].platform
    
    config_commands, error = _generate_bgp_delete_config(data, device_platform)
    
    if error:
        return {
            "host": data.device_name,
            "success": False,
            "error_type": "ValidationError",
            "result": error,
        }
    
    return await _apply_configuration_safely(
        nr_mgr=nr_mgr,
        device_name=data.device_name,
        config_commands=config_commands,
        mode=data.mode,
        operation_name=f"Delete BGP neighbor {data.neighbor_ip}",
    )


# Expose server instance

@mcp.tool()
async def configure_vrf(data: VRFConfigModel):
    """Create one VRF on one device. For multi-device tenant EVPN changes, use configure_fabric_bulk with vrfs[] so VRF, VLAN, VXLAN, SVI, and RD/RT stay in one dry-run/apply transaction."""
    logger.info(f"[Tool] configure_vrf called for {data.device_name} - VRF {data.vrf_name}")
    
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {"success": False, "result": "Device not found."}
    
    platform = host.inventory.hosts[data.device_name].platform
    config_commands, error = _generate_vrf_config(data, platform)
    
    if error:
        return {"success": False, "result": error}
        
    return await _apply_configuration_safely(
        nr_mgr=nr_mgr, device_name=data.device_name,
        config_commands=config_commands, mode=data.mode,
        operation_name=f"Configure VRF {data.vrf_name}"
    )

@mcp.tool()
async def configure_mlag(data: MLAGConfigModel):
    """Configure MLAG domain for dual-homing (domain-id, local-interface, peer-address, peer-link). Safety modes: dry_run(default), preview, apply."""
    logger.info(f"[Tool] configure_mlag called for {data.device_name} - domain {data.domain_id}")
    
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {"success": False, "result": "Device not found."}
    
    platform = host.inventory.hosts[data.device_name].platform
    config_commands, error = _generate_mlag_config(data, platform)
    
    if error:
        return {"success": False, "result": error}
        
    return await _apply_configuration_safely(
        nr_mgr=nr_mgr, device_name=data.device_name,
        config_commands=config_commands, mode=data.mode,
        operation_name=f"Configure MLAG domain {data.domain_id}"
    )

@mcp.tool()
async def delete_ospf(data: OSPFDeleteModel):
    """Delete OSPF process or specific network from device. Safety modes: dry_run(default), preview, apply."""
    logger.info(f"[Tool] delete_ospf called for {data.device_name} - process {data.process_id} (mode={data.mode})")
    
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {"success": False, "result": "Device not found."}
    
    platform = host.inventory.hosts[data.device_name].platform
    config_commands, error = _generate_ospf_delete_config(data, platform)
    
    if error:
        return {"success": False, "result": error}
        
    return await _apply_configuration_safely(
        nr_mgr=nr_mgr, device_name=data.device_name,
        config_commands=config_commands, mode=data.mode,
        operation_name=f"Delete OSPF process {data.process_id}"
    )

@mcp.tool()
async def configure_device_bulk(data: DeviceBulkConfigModel):
    """
    (BULK TOOL) Use this to configure multiple interfaces, OSPF, BGP, EVPN, VXLAN, and SVIs 
    on a *single device* in one transaction. Drastically saves time and RPC calls.
    ALWAYS prefer this over calling single-resource tools sequentially.
    Safety modes: dry_run, preview, apply.
    """
    logger.info(f"[Tool] configure_device_bulk called for {data.device_name} (mode={data.mode})")
    
    host = nr_mgr.nr.filter(name=data.device_name)
    if not host.inventory.hosts:
        return {"success": False, "result": "Device not found."}
    
    platform = host.inventory.hosts[data.device_name].platform
    
    # Sanitize payload: remove nulls and empty lists to save resources
    sanitized_dict = _sanitize_payload(data.dict())
    sanitized_data = DeviceBulkConfigModel(**sanitized_dict)
    
    config_commands, error = _generate_bulk_config(sanitized_data, platform)
    
    if error:
        return {"success": False, "result": error}
        
    return await _apply_configuration_safely(
        nr_mgr=nr_mgr, device_name=data.device_name,
        config_commands=config_commands, mode=data.mode,
        operation_name=f"Bulk configuration for {data.device_name}"
    )

@mcp.tool()
async def configure_fabric_bulk(data: FabricBulkConfigModel):
    """
    (SUPER BULK TOOL) Configure multiple devices across the fabric in a single transaction.
    Drastically saves time and LLM tokens. Provide a list of device configurations.
    Returns a dictionary mapping device names to their success/error results.

    IMPORTANT: If any device returns success=false with error_type=ConfigGenerationError,
    this means the payload has a structural problem (e.g. missing local_as for BGP on Arista).
    DO NOT retry with the exact same payload. Fix the specific field indicated in the error
    and make ONE corrected call. For BGP/EVPN, always set local_as at the device level.
    """
    logger.info(f"[Tool] configure_fabric_bulk called (mode={data.mode}) for {len(data.payloads)} devices")
    logger.info(f"[PAYLOAD] {data.model_dump_json(indent=2)}")

    underlay_error = _validate_underlay_bulk_completeness(data.payloads)
    if underlay_error:
        return underlay_error

    rt_payloads = [
        payload
        for payload in data.payloads
        if _get_device_fabric_role(payload.device_name, nr_mgr) != "spine"
    ]
    rt_error = _validate_fabric_rt_compatibility(rt_payloads)
    if rt_error:
        return rt_error

    results = {}
    device_artifacts = {}
    device_counts = {}
    for device_payload in data.payloads:
        dev_name = device_payload.device_name

        # Top-level mode is authoritative for fabric transactions.
        device_payload.mode = data.mode

        host = nr_mgr.nr.filter(name=dev_name)
        if not host.inventory.hosts:
            results[dev_name] = {"success": False, "result": "Device not found."}
            continue

        platform = host.inventory.hosts[dev_name].platform
        fabric_role = _get_device_fabric_role(dev_name, nr_mgr)
        
        # Sanitize individual device payload
        sanitized_dict = _sanitize_payload(device_payload.dict())
        sanitized_payload = DeviceBulkConfigModel(**sanitized_dict)
        
        config_commands, error = _generate_bulk_config(sanitized_payload, platform, fabric_role)

        if error:
            results[dev_name] = {
                "success": False,
                "error_type": "ConfigGenerationError",
                "result": error,
                "action_required": f"STOP. Fix the payload for {dev_name} before retrying. Do NOT call configure_fabric_bulk again with the same parameters.",
            }
            continue

        operation_name = f"Bulk configuration for {dev_name}"
        device_counts[dev_name] = len(config_commands)
        if data.mode == ConfigMode.DRY_RUN:
            fingerprint = workflow_guard._generate_fingerprint(dev_name, operation_name, config_commands)
            device_artifacts[dev_name] = {
                "device_name": dev_name,
                "operation_name": operation_name,
                "config_commands": config_commands,
                "cmd_count": len(config_commands),
                "fingerprint": fingerprint,
            }

        res = await _apply_configuration_safely(
            nr_mgr=nr_mgr, device_name=dev_name,
            config_commands=config_commands, mode=device_payload.mode,
            operation_name=operation_name
        )
        results[dev_name] = res

    failed_devices = [dev for dev, res in results.items() if not res.get("success", False)]
    all_success = len(results) == len(data.payloads) and not failed_devices

    if data.response_mode == ResponseMode.DETAILED:
        if data.mode == ConfigMode.DRY_RUN and all_success:
            return {
                "success": True,
                "mode": "dry_run",
                "dry_run_id": workflow_guard.register_fabric_dry_run(device_artifacts),
                "results": results,
            }
        return {
            "success": all_success,
            "mode": data.mode.value,
            "failed_devices": failed_devices,
            "results": results,
        }

    if data.mode == ConfigMode.DRY_RUN and all_success:
        dry_run_id = workflow_guard.register_fabric_dry_run(device_artifacts)
        return {
            "success": True,
            "mode": "dry_run",
            "dry_run_id": dry_run_id,
            "devices": {
                dev: {"ok": True, "cmd_count": device_counts.get(dev, 0)}
                for dev in results
            },
        }

    compact = {
        "success": all_success,
        "mode": data.mode.value,
        "devices": {
            dev: {
                "ok": res.get("success", False),
                "cmd_count": device_counts.get(dev, res.get("cmd_count", 0)),
            }
            for dev, res in results.items()
        },
        "failed_devices": failed_devices,
    }
    if not all_success:
        compact["details"] = results
    return compact


@mcp.tool()
async def apply_fabric_dry_run(data: ApplyFabricDryRunModel):
    """
    Apply a previously validated configure_fabric_bulk dry-run artifact.
    This avoids resending the large payload and applies exactly the commands
    generated during dry-run.
    """
    logger.info(f"[Tool] apply_fabric_dry_run called for {data.dry_run_id}")
    artifact = workflow_guard.get_fabric_dry_run(data.dry_run_id)
    if not artifact:
        return {
            "success": False,
            "mode": "apply",
            "dry_run_id": data.dry_run_id,
            "error_type": "DryRunNotFound",
            "result": "No valid unconsumed dry-run artifact found. Repeat configure_fabric_bulk dry_run and apply the new dry_run_id.",
        }

    results = {}
    failed_devices = []
    for dev_name, dev_artifact in artifact.get("artifacts", {}).items():
        res = await _apply_configuration_safely(
            nr_mgr=nr_mgr,
            device_name=dev_name,
            config_commands=dev_artifact["config_commands"],
            mode=ConfigMode.APPLY,
            operation_name=dev_artifact["operation_name"],
        )
        results[dev_name] = res
        if not res.get("success", False):
            failed_devices.append(dev_name)

    if not failed_devices:
        for dev_name, dev_artifact in artifact.get("artifacts", {}).items():
            commands = dev_artifact.get("config_commands", [])
            has_access_vlan = any("switchport access vlan" in cmd for cmd in commands)
            if has_access_vlan:
                _deferred_access_ports.pop(dev_name, None)
        workflow_guard.consume_fabric_dry_run(data.dry_run_id)
        return {
            "success": True,
            "mode": "apply",
            "dry_run_id": data.dry_run_id,
            "devices_applied": len(results),
            "failed_devices": [],
        }

    return {
        "success": False,
        "mode": "apply",
        "dry_run_id": data.dry_run_id,
        "devices_applied": len(results) - len(failed_devices),
        "failed_devices": failed_devices,
        "details": results,
    }


if __name__ == "__main__":
    logger.info("[Setup] Starting Nornir MCP server with stdio transport...")
    mcp.run(transport="stdio")
