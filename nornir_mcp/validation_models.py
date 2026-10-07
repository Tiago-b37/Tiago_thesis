#!/usr/bin/env python3
"""Pydantic models and validation helpers moved out of server.py.

Provides a factory `make_validate_params(nr_mgr)` which returns an async
`validate_params` function bound to the provided Nornir manager instance.
"""
import logging
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, get_origin

from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger("nornir_mcp.validation")


# --- Pydantic Models for Input Validation ---
class DeviceNameModel(BaseModel):
    device_name: str = Field(
        ..., description="The unique device name as defined in the Nornir inventory."
    )


class ConfigMode(str, Enum):
    DRY_RUN = "dry_run"
    PREVIEW = "preview"
    APPLY = "apply"


class ResponseMode(str, Enum):
    COMPACT = "compact"
    DETAILED = "detailed"


class GetConfigModel(DeviceNameModel):
    retrieve: str = Field(default="running")


class SendCommandModel(DeviceNameModel):
    command: Optional[str] = Field(None)
    commands: Optional[List[str]] = Field(None)

class SendCommandMultipleModel(BaseModel):
    """Model for sending a command to multiple devices concurrently"""
    device_names: List[str] = Field(..., description="List of unique device names")
    command: str = Field(..., description="The command to execute on all devices")

class CheckDevicesModel(BaseModel):
    device_names: List[str] = Field(..., description="List of unique device names to check")
    include_details: bool = Field(False, description="Return per-neighbor details even when the check succeeds")


class DataplaneCheckModel(BaseModel):
    """Model for comprehensive Phase 3 dataplane validation."""
    device_names: List[str] = Field(..., description="List of leaf devices to check")
    expected_vni: int = Field(..., description="VNI expected by the approved intent")
    expected_vlan: int = Field(..., description="VLAN expected by the approved intent")
    expected_gateway: str = Field(..., description="Anycast gateway address and prefix expected by the approved intent")
    include_details: bool = Field(False, description="Return per-device dataplane details even when the check succeeds")



class BGPConfigModel(DeviceNameModel):
    group: str = Field(default="")
    neighbor: str = Field(default="")


class BGPNeighborConfigModel(DeviceNameModel):
    neighbor_ip: str = Field(..., description="BGP neighbor IP address")
    peer_group: Optional[str] = Field(None, description="BGP peer group name")
    remote_as: int = Field(..., description="Remote AS number")
    local_as: Optional[int] = Field(None, description="Local AS number")
    description: Optional[str] = Field(None, description="Neighbor description")
    update_source: Optional[str] = Field(None, description="Update source interface")
    ebgp_multihop: Optional[int] = Field(None, description="eBGP multihop TTL value")
    password: Optional[str] = Field(None, description="BGP authentication password")
    route_reflector_client: Optional[bool] = Field(None, description="Enable route reflector client")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class EVPNPeerConfigModel(DeviceNameModel):
    """Model for EVPN peering configuration"""
    neighbor_ip: str = Field(..., description="BGP neighbor IP address or peer group name")
    local_as: Optional[int] = Field(None, description="Local AS number")
    activate: bool = Field(True, description="Activate the neighbor for address-family evpn")
    send_community_extended: bool = Field(True, description="Enable send-community extended for the neighbor")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class VLAN_VNIMappingModel(DeviceNameModel):
    """Model for VLAN to VNI mapping"""
    vlan_id: int = Field(..., description="VLAN ID")
    vni: int = Field(..., description="VXLAN Network Identifier")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class VXLANConfigModel(DeviceNameModel):
    """Model for VXLAN configuration"""
    vni: int = Field(..., description="VXLAN Network Identifier (VNI)")
    vlan_id: Optional[int] = Field(None, description="Associated VLAN ID")
    multicast_group: Optional[str] = Field(None, description="Multicast group IP address")
    flood_vteps: Optional[List[str]] = Field(None, description="List of VTEP IPs for HER flood list")
    source_interface: Optional[str] = Field(None, description="Source interface for VXLAN tunnel")
    vtep_ip: Optional[str] = Field(None, description="VTEP (VXLAN Tunnel Endpoint) IP address")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class SVIConfigModel(DeviceNameModel):
    """Model for SVI configuration"""
    vlan_id: int = Field(..., description="VLAN ID for the SVI")
    vrf: Optional[str] = Field(None, description="VRF name")
    ip_address: Optional[str] = Field(None, description="Routed IP address and prefix for the SVI")
    virtual_ip: Optional[str] = Field(None, description="Shared anycast/virtual gateway address and prefix")
    description: Optional[str] = Field(None, description="Description for the SVI")
    anycast_mac: Optional[str] = Field(None, description="Anycast MAC address for the SVI")
    mtu: Optional[int] = Field(None, description="MTU for the SVI")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class EVPNRdRtConfigModel(DeviceNameModel):
    """Model for EVPN RD/RT configuration"""
    vlan_id: int = Field(..., description="VLAN ID")
    local_as: int = Field(..., description="Local AS number")
    rd: str = Field(..., description="Route Distinguisher in administrator:service-id format")
    rt_import: Optional[str] = Field(None, description="Route Target Import in administrator:service-id format")
    rt_export: Optional[str] = Field(None, description="Route Target Export in administrator:service-id format")
    both: Optional[str] = Field(None, description="Route Target for both directions in administrator:service-id format")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class InterfaceConfigModel(DeviceNameModel):
    """Model for physical interface configuration"""
    interface_name: str = Field(..., description="Interface name from the approved intent or inventory")
    description: Optional[str] = Field(None, description="Interface description")
    mtu: Optional[int] = Field(None, description="MTU size")
    switchport_mode: Optional[str] = Field(None, description="Switchport mode: access or trunk")
    access_vlan: Optional[int] = Field(None, description="Access VLAN ID")
    trunk_allowed_vlans: Optional[str] = Field(None, description="Comma-separated VLAN IDs allowed on the trunk")
    ip_address: Optional[str] = Field(None, description="IP address/mask for routed interface")
    shutdown: Optional[bool] = Field(None, description="Shutdown status (True=shutdown, False=no shutdown)")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class VRFConfigModel(DeviceNameModel):
    """Model for VRF configuration"""
    vrf_name: str = Field(..., description="VRF instance name")
    l3vni: Optional[int] = Field(None, description="L3 VNI for the VRF")
    rd: Optional[str] = Field(None, description="Route Distinguisher")
    rt_import: Optional[str] = Field(None, description="Route Target Import")
    rt_export: Optional[str] = Field(None, description="Route Target Export")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class MLAGConfigModel(DeviceNameModel):
    """Model for MLAG configuration"""
    domain_id: str = Field(..., description="MLAG domain ID")
    local_interface: str = Field(..., description="Local interface for MLAG control from the approved design")
    peer_address: str = Field(..., description="Peer IP address for MLAG")
    peer_link: str = Field(..., description="Peer-link interface from the approved design")
    reload_delay_mlag: Optional[int] = Field(None, description="MLAG reload delay")
    reload_delay_non_mlag: Optional[int] = Field(None, description="Non-MLAG reload delay")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


# --- Bulk Models ---
class InterfaceDetailModel(BaseModel):
    interface_name: str = Field(..., description="Interface name from the approved intent or inventory")
    description: Optional[str] = Field(None, description="Interface description")
    mtu: Optional[int] = Field(
        None, description="MTU size; omit unless explicitly required by the intent"
    )
    switchport_mode: Optional[str] = Field(None, description="Switchport mode: access or trunk")
    access_vlan: Optional[int] = Field(None, description="Access VLAN ID")
    trunk_allowed_vlans: Optional[str] = Field(None, description="Comma-separated VLAN IDs allowed on the trunk")
    ip_address: Optional[str] = Field(None, description="IP address/mask for routed interface")
    shutdown: Optional[bool] = Field(False, description="Shutdown status (True=shutdown, False=no shutdown), default is False")

class OSPFDetailModel(BaseModel):
    process_id: int = Field(1, description="OSPF process ID, default is 1")
    router_id: Optional[str] = Field(None, description="OSPF router ID")
    networks: Optional[List[dict]] = Field(None, description="Networks to advertise, each with network and area fields")
    interfaces: Optional[List[dict]] = Field(None, description="Interfaces to configure, each with name, area, network type, and passive state")
    passive_default: bool = Field(False, description="Set all interfaces as passive by default, default is False")
    max_lsa: Optional[int] = Field(12000, description="Maximum number of LSAs, default is 12000")
    default_originate: bool = Field(False, description="Originate a default route into OSPF")
    redistribute: Optional[List[str]] = Field(None, description="Protocols to redistribute")

class BGPNeighborDetailModel(BaseModel):
    neighbor_ip: str = Field(..., description="BGP neighbor IP address")
    peer_group: Optional[str] = Field(None, description="BGP peer group name")
    remote_as: int = Field(..., description="Remote AS number")
    local_as: Optional[int] = Field(None, description="Local AS number")
    description: Optional[str] = Field(None, description="Neighbor description")
    update_source: Optional[str] = Field(None, description="Update source interface; use Loopback0 for loopback-based overlay peers, omit for directly connected underlay peers")
    ebgp_multihop: Optional[int] = Field(None, description="eBGP multihop TTL value")
    password: Optional[str] = Field(None, description="BGP authentication password")
    route_reflector_client: Optional[bool] = Field(None, description="Enable route reflector client when using an iBGP route-reflector design")

class BGPNetworkDetailModel(BaseModel):
    network: str = Field(..., description="IPv4 prefix to advertise in BGP")

class EVPNPeerDetailModel(BaseModel):
    neighbor_ip: str = Field(..., description="BGP neighbor IP address or peer group name")
    local_as: Optional[int] = Field(None, description="Local AS number")
    activate: bool = Field(True, description="Activate the neighbor for address-family evpn")
    send_community_extended: bool = Field(True, description="Enable send-community extended")
    route_reflector_client: Optional[bool] = Field(None, description="Enable route reflector client for EVPN when using an iBGP route-reflector design")

class VXLANDetailModel(BaseModel):
    vni: int = Field(..., description="VXLAN Network Identifier (L2VNI)")
    vlan_id: Optional[int] = Field(None, description="Associated VLAN ID, required for L2VNI mappings")
    multicast_group: Optional[str] = Field(None, description="Multicast group IP address")
    flood_vteps: Optional[List[str]] = Field(None, description="List of VTEP IPs for HER flood list")
    source_interface: Optional[str] = Field(None, description="Source interface for VXLAN tunnel")
    vtep_ip: Optional[str] = Field(None, description="VTEP (VXLAN Tunnel Endpoint) IP address")

class SVIDetailModel(BaseModel):
    vlan_id: int = Field(..., description="VLAN ID for the SVI")
    vrf: Optional[str] = Field(
        None,
        description=(
            "VRF bound to the SVI. With virtual_ip, EOS uses VRF anycast "
            "mode ('ip address virtual')."
        ),
    )
    ip_address: Optional[str] = Field(
        None,
        description=(
            "Routed SVI address. Required alongside virtual_ip for non-VRF "
            "anycast; omit it for a VRF-bound anycast SVI."
        ),
    )
    virtual_ip: Optional[str] = Field(
        None,
        description=(
            "Anycast gateway including prefix length. In a VRF, use this "
            "without ip_address; outside a VRF, accompany it with ip_address."
        ),
    )
    description: Optional[str] = Field(None, description="Description for the SVI")
    anycast_mac: Optional[str] = Field(None, description="Anycast MAC address")
    mtu: Optional[int] = Field(
        None, description="Optional SVI MTU; include only when explicitly requested"
    )

    @model_validator(mode="after")
    def validate_addressing_mode(self):
        if self.vrf and self.virtual_ip:
            if self.ip_address:
                raise ValueError(
                    "VRF-bound anycast SVIs use virtual_ip only; omit ip_address "
                    "because EOS would ignore it in 'ip address virtual' mode"
                )
            if "/" not in self.virtual_ip:
                raise ValueError(
                    "VRF-bound anycast virtual_ip must include its prefix length"
                )
        elif self.virtual_ip and not self.ip_address:
            raise ValueError(
                "Non-VRF anycast SVIs require ip_address alongside virtual_ip"
            )
        return self

class VLAN_VNIDetailModel(BaseModel):
    vlan_id: int = Field(..., description="VLAN ID")
    vni: int = Field(..., description="VXLAN Network Identifier")

class VRFDetailModel(BaseModel):
    """VRF configuration for Symmetric IRB / multi-tenant EVPN."""
    vrf_name: str = Field(..., description="VRF instance name supplied by the approved intent")
    l3vni: Optional[int] = Field(None, description="L3 VNI for symmetric IRB; requires local_as, rd and RTs")
    local_as: Optional[int] = Field(None, description="Device BGP AS for this VRF, not the RT namespace")
    rd: Optional[str] = Field(None, description="IP-VRF Route Distinguisher")
    rt_import: Optional[str] = Field(None, description="IP-VRF Route Target Import")
    rt_export: Optional[str] = Field(None, description="IP-VRF Route Target Export")
    redistribute_connected: bool = Field(True, description="Redistribute connected routes in this VRF")

class EVPNRdRtDetailModel(BaseModel):
    vlan_id: int = Field(..., description="VLAN ID for MAC-VRF/L2VNI")
    local_as: Optional[int] = Field(None, description="Device BGP AS for EVPN RD/RT, not the RT namespace")
    rd: str = Field(..., description="MAC-VRF Route Distinguisher")
    rt_import: Optional[str] = Field(None, description="MAC-VRF Route Target Import")
    rt_export: Optional[str] = Field(None, description="MAC-VRF Route Target Export")
    both: Optional[str] = Field(None, description="MAC-VRF Route Target both")

class ACLRuleModel(BaseModel):
    sequence: int = Field(..., description="ACL sequence number")
    action: Literal["permit", "deny"] = Field(..., description="ACL action")
    protocol: str = Field("ip", description="Protocol to match, e.g. ip, tcp, udp, icmp")
    src: str = Field(..., description="Source match as any, host IP, IP address, or CIDR")
    dst: str = Field(..., description="Destination match as any, host IP, IP address, or CIDR")

class ACLDetailModel(BaseModel):
    name: str = Field(..., description="ACL name")
    rules: List[ACLRuleModel] = Field(..., description="Ordered ACL rules")

class InterfaceACLAttachmentModel(BaseModel):
    interface_name: str = Field(..., description="Interface where the ACL is attached")
    acl_name: str = Field(..., description="ACL name to attach")
    direction: Literal["in", "out"] = Field("in", description="ACL direction")

class DeviceBulkConfigModel(DeviceNameModel):
    """Model for bulk provisioning of a device (interfaces, ospf, bgp, evpn, vxlan) in one go."""
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode")
    local_as: Optional[int] = Field(
        None,
        description=(
            "Device-level local BGP AS. Required whenever the payload contains "
            "BGP neighbors, networks, EVPN peers, EVPN RD/RT, or VRF RD/RT; "
            "inherited by those entries unless explicitly overridden."
        ),
    )

    interfaces: Optional[List[InterfaceDetailModel]] = Field(None, description="List of interfaces")
    ospf: Optional[List[OSPFDetailModel]] = Field(None, description="List of OSPF processes")
    bgp_neighbors: Optional[List[BGPNeighborDetailModel]] = Field(None, description="List of BGP neighbors")
    bgp_networks: Optional[List[BGPNetworkDetailModel]] = Field(None, description="List of IPv4 prefixes to advertise in BGP, used by eBGP underlay to advertise loopbacks")
    evpn_peers: Optional[List[EVPNPeerDetailModel]] = Field(None, description="List of EVPN peers")
    evpn_rd_rt: Optional[List[EVPNRdRtDetailModel]] = Field(None, description="List of EVPN RD/RT properties per VLAN; each VLAN must also exist in vlans[] with its L2VNI")
    vlans: Optional[List[VLAN_VNIDetailModel]] = Field(None, description="List of VLAN to VNI mappings")
    vxlan: Optional[List[VXLANDetailModel]] = Field(None, description="List of VXLAN definitions")
    svis: Optional[List[SVIDetailModel]] = Field(None, description="List of SVIs")
    vrfs: Optional[List['VRFDetailModel']] = Field(None, description="List of VRF instances for multi-tenant EVPN (Symmetric IRB)")
    acls: Optional[List[ACLDetailModel]] = Field(None, description="List of IPv4 ACLs to configure")
    interface_acls: Optional[List[InterfaceACLAttachmentModel]] = Field(None, description="List of ACL attachments to interfaces")

class FabricBulkConfigModel(BaseModel):
    """Model for bulk provisioning of the entire fabric (multiple devices) in one go."""
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run or apply")
    response_mode: ResponseMode = Field(ResponseMode.COMPACT, description="Response verbosity: compact by default, detailed for debugging")
    payloads: List[DeviceBulkConfigModel] = Field(..., description="List of bulk configurations per device")


class ApplyFabricDryRunModel(BaseModel):
    """Apply a previously validated fabric dry-run artifact without resending payloads."""
    dry_run_id: str = Field(..., description="ID returned by configure_fabric_bulk dry_run")

class VXLANDeleteModel(DeviceNameModel):
    """Model for VXLAN deletion"""
    vni: int = Field(..., description="VXLAN Network Identifier (VNI) to delete")
    vlan_id: Optional[int] = Field(None, description="VLAN ID mapped to this VNI when deleting EOS VLAN-to-VNI mappings")
    flood_vteps: Optional[List[str]] = Field(None, description="Optional remote VTEPs to remove from the VLAN flood list")
    local_as: Optional[int] = Field(None, description="Local BGP AS; include it when cleaning a VLAN EVPN stanza")
    cleanup_vlan: bool = Field(False, description="Also remove stale BGP EVPN VLAN stanza, SVI, and VLAN for a tenant migration")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class BGPNeighborDeleteModel(DeviceNameModel):
    """Model for BGP neighbor deletion"""
    neighbor_ip: str = Field(..., description="BGP neighbor IP address to remove")
    local_as: Optional[int] = Field(None, description="Local AS number")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode: dry_run, preview, or apply")


class BGPNeighborsDetailModel(DeviceNameModel):
    neighbor_address: str = Field(default="")


class LLDPNeighborsDetailModel(DeviceNameModel):
    interface: str = Field(default="")


class NetworkInstancesModel(DeviceNameModel):
    name: str = Field(default="")


class PingModel(DeviceNameModel):
    destination: str
    source: str = ""
    ttl: int = 255
    timeout: int = 2
    size: int = 100
    count: int = 5
    vrf: str = ""
    source_interface: str = ""


class TracerouteModel(DeviceNameModel):
    destination: str
    source: str = ""
    ttl: int = 255
    timeout: int = 2
    vrf: str = ""


class OSPFConfigModel(DeviceNameModel):
    """Model for OSPF configuration"""
    process_id: int = Field(1, description="OSPF process ID (default: 1)")
    router_id: Optional[str] = Field(None, description="OSPF router ID supplied by the approved intent")
    networks: Optional[List[dict]] = Field(None, description="Networks to advertise, each with network and area fields")
    interfaces: Optional[List[dict]] = Field(None, description="Interfaces to configure, each with name, area, network type, cost, and passive state")
    passive_default: bool = Field(False, description="Set all interfaces as passive by default")
    max_lsa: Optional[int] = Field(None, description="Maximum number of LSAs (e.g., 12000)")
    default_originate: bool = Field(False, description="Originate a default route into OSPF")
    redistribute: Optional[List[str]] = Field(None, description="Protocols to redistribute (e.g., ['connected', 'static', 'bgp'])")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode")


class OSPFDeleteModel(DeviceNameModel):
    """Model for OSPF process or network deletion"""
    process_id: int = Field(1, description="OSPF process ID to delete")
    network: Optional[str] = Field(None, description="Specific network to remove; if omitted, removes the entire OSPF process")
    area: Optional[str] = Field(None, description="OSPF area of the network to remove (required if network is specified)")
    mode: ConfigMode = Field(ConfigMode.DRY_RUN, description="Execution mode")


# --- Result Models ---
class PingProbe(BaseModel):
    ip_address: str
    rtt: float


class PingSuccess(BaseModel):
    probes_sent: int
    packet_loss: float
    rtt_min: float
    rtt_max: float
    rtt_avg: float
    rtt_stddev: float
    results: List[PingProbe]


class PingResultModel(BaseModel):
    success: Optional[PingSuccess] = None
    error: Optional[str] = None


class DataplaneCheckResult(BaseModel):
    """Result model for atomic Phase 3 dataplane validation."""
    phase3_ready: bool = Field(..., description="True if all critical dataplane components are 'up' or 'active'")
    summary: Dict[str, Any] = Field(..., description="Aggregated success/failure counts")
    details: Dict[str, Any] = Field(..., description="Per-device dictionary of check results")


class TracerouteHop(BaseModel):
    rtt: float
    ip_address: str
    host_name: Optional[str] = None


class TracerouteResultModel(BaseModel):
    success: Optional[Dict[str, TracerouteHop]] = None
    error: Optional[str] = None


# --- Helpers ---
def _example_from_model(cls: BaseModel) -> Dict[str, Any]:
    example: Dict[str, Any] = {}
    # Pydantic v2: use model_fields and FieldInfo.is_required
    fields = getattr(cls, "model_fields", None)
    if fields is None:
        # fallback for older pydantic versions
        fields = getattr(cls, "__fields__", {})

    for name, field in fields.items():
        # FieldInfo in pydantic v2 exposes `is_required`
        is_required = getattr(field, "is_required", None)
        if is_required is None:
            # pydantic v1 compatibility: Field has 'required'
            is_required = getattr(field, "required", False)

        if is_required:
            ft = getattr(field, "annotation", None) or getattr(
                field, "outer_type_", None
            )
            origin = get_origin(ft)
            if ft is int or origin is int:
                example[name] = 0
            elif ft is float or origin is float:
                example[name] = 0.0
            elif ft is bool or origin is bool:
                example[name] = False
            elif origin is list or ft is list:
                example[name] = []
            else:
                example[name] = "<str>"
        else:
            # get default value when present
            default = None
            if hasattr(field, "default"):
                default = getattr(field, "default")
            elif hasattr(field, "get_default"):
                default = field.get_default()
            example[name] = default
    return example


def _format_validation_error(exc: ValidationError) -> Dict[str, Any]:
    errors = exc.errors()
    return {
        "errors": errors,
        "summary": errors[0]["msg"] if errors else "validation failed",
        "json": exc.json(),
    }


# Model map (input + result models)
MODEL_MAP: Dict[str, Any] = {
    "DeviceNameModel": DeviceNameModel,
    "GetConfigModel": GetConfigModel,
    "SendCommandModel": SendCommandModel,
    "BGPConfigModel": BGPConfigModel,
    "BGPNeighborsDetailModel": BGPNeighborsDetailModel,
    "LLDPNeighborsDetailModel": LLDPNeighborsDetailModel,
    "NetworkInstancesModel": NetworkInstancesModel,
    "PingModel": PingModel,
    "TracerouteModel": TracerouteModel,
    "BGPNeighborConfigModel": BGPNeighborConfigModel,
    "BGPNetworkDetailModel": BGPNetworkDetailModel,
    "VXLANConfigModel": VXLANConfigModel,
    "SVIConfigModel": SVIConfigModel,
    "EVPNPeerConfigModel": EVPNPeerConfigModel,
    "VLAN_VNIMappingModel": VLAN_VNIMappingModel,
    "EVPNRdRtConfigModel": EVPNRdRtConfigModel,
    "InterfaceConfigModel": InterfaceConfigModel,
    "ACLRuleModel": ACLRuleModel,
    "ACLDetailModel": ACLDetailModel,
    "InterfaceACLAttachmentModel": InterfaceACLAttachmentModel,
    "VRFDetailModel": VRFDetailModel,
    "DeviceBulkConfigModel": DeviceBulkConfigModel,
    "FabricBulkConfigModel": FabricBulkConfigModel,
    "ApplyFabricDryRunModel": ApplyFabricDryRunModel,
    "VRFConfigModel": VRFConfigModel,
    "MLAGConfigModel": MLAGConfigModel,
    "VXLANDeleteModel": VXLANDeleteModel,
    "BGPNeighborDeleteModel": BGPNeighborDeleteModel,
    "OSPFConfigModel": OSPFConfigModel,
    "OSPFDeleteModel": OSPFDeleteModel,
    # result models
    "PingResultModel": PingResultModel,
    "TracerouteResultModel": TracerouteResultModel,
    "DataplaneCheckModel": DataplaneCheckModel,
    "DataplaneCheckResult": DataplaneCheckResult,
}


def make_validate_params(nr_mgr):
    """Return an async validate_params function bound to the provided nr_mgr.

    This avoids circular imports: server creates nr_mgr then registers
    mcp.tool()(make_validate_params(nr_mgr)).
    """

    async def validate_params(raw: Dict[str, Any], model_name: str = "DeviceNameModel"):
        logger.info(f"[Tool] validate_params called for model {model_name}")
        model_cls = MODEL_MAP.get(model_name)
        if model_cls is None:
            return {
                "success": False,
                "error": "unknown_model",
                "available_models": list(MODEL_MAP.keys()),
            }

        try:
            model_cls.parse_obj(raw)
            return {
                "success": True,
                "validated": raw,
                "model_schema": model_cls.schema(),
                "model_schema_json": model_cls.schema_json(),
                "correct_example": _example_from_model(model_cls),
            }
        except ValidationError as ve:
            missing_required = []
            if isinstance(raw, dict):
                # pydantic v2: model_fields -> FieldInfo with is_required
                fields = getattr(model_cls, "model_fields", None)
                if fields is None:
                    fields = getattr(model_cls, "__fields__", {})
                for fname, field in fields.items():
                    is_required = getattr(field, "is_required", None)
                    if is_required is None:
                        is_required = getattr(field, "required", False)
                    if is_required and fname not in raw:
                        missing_required.append(fname)

            # Build a helpful suggested_payload when client used common alternate keys
            suggested_payload = None
            if isinstance(raw, dict):
                if "name" in raw and "device_name" in missing_required:
                    suggested_payload = {"device_name": raw.get("name")}
                elif "hostname" in raw and "device_name" in missing_required:
                    try:
                        hosts = nr_mgr.list_hosts()
                        match = next(
                            (
                                h
                                for h in hosts
                                if h.get("hostname") == raw.get("hostname")
                            ),
                            None,
                        )
                        if match:
                            suggested_payload = {"device_name": match.get("name")}
                        else:
                            suggested_payload = {
                                "device_name": f"<name from list_all_hosts for hostname {raw.get('hostname')}>"
                            }
                    except Exception:
                        suggested_payload = {"device_name": "<inventory_name>"}

            formatted = _format_validation_error(ve)
            if "device_name" in missing_required:
                formatted["summary"] = "'device_name' is a required property"
                friendly = formatted.get("friendly", [])
                friendly.insert(0, formatted["summary"])
                formatted["friendly"] = friendly

            return {
                "success": False,
                "validation": formatted,
                "correct_example": _example_from_model(model_cls),
                "model_schema": model_cls.schema(),
                "model_schema_json": model_cls.schema_json(),
                "suggested_payload": suggested_payload,
                "note": "If you provided 'name' or 'hostname', map it to the inventory 'name' and send it as 'device_name'. Call list_all_hosts() to discover inventory names.",
            }

    return validate_params
