#!/usr/bin/env bash
# prepare_baseline.sh — Deterministic baseline for T2/T3/T4 tests.
#
# Applies the equivalent of a successful T1 "Zero-to-Hero" run without
# relying on the LLM. Configures:
#   - eBGP underlay (spines AS 65000, leaf1 AS 65101, leaf2 AS 65102)
#   - BGP EVPN overlay directly between leaf VTEPs over loopbacks
#   - VXLAN VTEPs (source Loopback0, head-end replication)
#   - VLAN 10 / VNI 10010 on both leaves
#   - Unique SVI IPs (.2/.3) plus Anycast Gateway 10.10.10.1/24
#     (ip virtual-router address, MAC 00:1c:73:00:00:01)
#   - client8-dc2: 10.10.10.10/24 via leaf1-dc2 eth3
#   - client9-dc2: 10.10.10.20/24 via leaf2-dc2 eth3
#
# Does NOT touch: client10/client11, VRFs, VLAN 20 — those are for T3.
#
# Usage (from repo root on the Ubuntu VM):
#   bash tests/prepare_baseline.sh
#
# Pre-requisite: clab is running (clab deploy already done).

set -euo pipefail

OK="\033[0;32m[OK]\033[0m"
INFO="\033[0;34m[..]\033[0m"
FAIL="\033[0;31m[FAIL]\033[0m"

echo -e "${INFO} Applying deterministic baseline to fabric..."

# ---------------------------------------------------------------------------
# SPINE1-DC2
# ---------------------------------------------------------------------------
echo -e "${INFO} Configuring spine1-dc2..."
docker exec -i clab-dc2-topology-spine1-dc2 Cli -p 15 > /dev/null << 'EOF'
configure
interface Ethernet1-2
   no switchport
EOF
sleep 1
docker exec -i clab-dc2-topology-spine1-dc2 Cli -p 15 > /dev/null << 'EOF'
configure
ip routing
interface Loopback0
   ip address 1.1.1.1/32
interface Ethernet1
   description spine1->leaf1
   ip address 10.0.11.0/31
   mtu 9214
   no shutdown
interface Ethernet2
   description spine1->leaf2
   ip address 10.0.12.0/31
   mtu 9214
   no shutdown
router bgp 65000
   router-id 1.1.1.1
   network 1.1.1.1/32
   neighbor 10.0.11.1 remote-as 65101
   neighbor 10.0.12.1 remote-as 65102
EOF
echo -e "${OK} spine1-dc2 done"

# ---------------------------------------------------------------------------
# SPINE2-DC2
# ---------------------------------------------------------------------------
echo -e "${INFO} Configuring spine2-dc2..."
docker exec -i clab-dc2-topology-spine2-dc2 Cli -p 15 > /dev/null << 'EOF'
configure
interface Ethernet1-2
   no switchport
EOF
sleep 1
docker exec -i clab-dc2-topology-spine2-dc2 Cli -p 15 > /dev/null << 'EOF'
configure
ip routing
interface Loopback0
   ip address 1.1.1.2/32
interface Ethernet1
   description spine2->leaf1
   ip address 10.0.21.0/31
   mtu 9214
   no shutdown
interface Ethernet2
   description spine2->leaf2
   ip address 10.0.22.0/31
   mtu 9214
   no shutdown
router bgp 65000
   router-id 1.1.1.2
   network 1.1.1.2/32
   neighbor 10.0.21.1 remote-as 65101
   neighbor 10.0.22.1 remote-as 65102
EOF
echo -e "${OK} spine2-dc2 done"

# ---------------------------------------------------------------------------
# LEAF1-DC2
# ---------------------------------------------------------------------------
echo -e "${INFO} Configuring leaf1-dc2..."
docker exec -i clab-dc2-topology-leaf1-dc2 Cli -p 15 > /dev/null << 'EOF'
configure
interface Ethernet1-2
   no switchport
EOF
sleep 1
docker exec -i clab-dc2-topology-leaf1-dc2 Cli -p 15 > /dev/null << 'EOF'
configure
ip routing
interface Loopback0
   ip address 1.1.1.11/32
interface Ethernet1
   description leaf1->spine1
   ip address 10.0.11.1/31
   mtu 9214
   no shutdown
interface Ethernet2
   description leaf1->spine2
   ip address 10.0.21.1/31
   mtu 9214
   no shutdown
interface Ethernet3
   description leaf1->client8
   switchport access vlan 10
   no shutdown
vlan 10
   name TENANT_BLUE
ip virtual-router mac-address 00:1c:73:00:00:01
interface Vlan10
   ip address 10.10.10.2/24
   ip virtual-router address 10.10.10.1/24
   no shutdown
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 10 vni 10010
   vxlan flood vtep 1.1.1.12
router bgp 65101
   router-id 1.1.1.11
   network 1.1.1.11/32
   neighbor 10.0.11.0 remote-as 65000
   neighbor 10.0.21.0 remote-as 65000
   neighbor 1.1.1.12 remote-as 65102
   neighbor 1.1.1.12 update-source Loopback0
   neighbor 1.1.1.12 ebgp-multihop 3
   neighbor 1.1.1.12 send-community extended
   vlan 10
      rd 1.1.1.11:10
      route-target both 65000:10010
      redistribute learned
   exit
   address-family evpn
      neighbor 1.1.1.12 activate
EOF
echo -e "${OK} leaf1-dc2 done"

# ---------------------------------------------------------------------------
# LEAF2-DC2
# ---------------------------------------------------------------------------
echo -e "${INFO} Configuring leaf2-dc2..."
docker exec -i clab-dc2-topology-leaf2-dc2 Cli -p 15 > /dev/null << 'EOF'
configure
interface Ethernet1-2
   no switchport
EOF
sleep 1
docker exec -i clab-dc2-topology-leaf2-dc2 Cli -p 15 > /dev/null << 'EOF'
configure
ip routing
interface Loopback0
   ip address 1.1.1.12/32
interface Ethernet1
   description leaf2->spine1
   ip address 10.0.12.1/31
   mtu 9214
   no shutdown
interface Ethernet2
   description leaf2->spine2
   ip address 10.0.22.1/31
   mtu 9214
   no shutdown
interface Ethernet3
   description leaf2->client9
   switchport access vlan 10
   no shutdown
vlan 10
   name TENANT_BLUE
ip virtual-router mac-address 00:1c:73:00:00:01
interface Vlan10
   ip address 10.10.10.3/24
   ip virtual-router address 10.10.10.1/24
   no shutdown
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 10 vni 10010
   vxlan flood vtep 1.1.1.11
router bgp 65102
   router-id 1.1.1.12
   network 1.1.1.12/32
   neighbor 10.0.12.0 remote-as 65000
   neighbor 10.0.22.0 remote-as 65000
   neighbor 1.1.1.11 remote-as 65101
   neighbor 1.1.1.11 update-source Loopback0
   neighbor 1.1.1.11 ebgp-multihop 3
   neighbor 1.1.1.11 send-community extended
   vlan 10
      rd 1.1.1.12:10
      route-target both 65000:10010
      redistribute learned
   exit
   address-family evpn
      neighbor 1.1.1.11 activate
EOF
echo -e "${OK} leaf2-dc2 done"

# ---------------------------------------------------------------------------
# CLIENT8-DC2  (10.10.10.10/24 via leaf1 eth3)
# ---------------------------------------------------------------------------
echo -e "${INFO} Configuring client8-dc2..."
docker exec clab-dc2-topology-client8-dc2 sh -c "
  ip addr flush dev eth1 2>/dev/null || true
  ip addr add 10.10.10.10/24 dev eth1
  ip link set eth1 up
  ip route del default 2>/dev/null || true
  ip route add default via 10.10.10.1
"
echo -e "${OK} client8-dc2 done"

# ---------------------------------------------------------------------------
# CLIENT9-DC2  (10.10.10.20/24 via leaf2 eth3)
# ---------------------------------------------------------------------------
echo -e "${INFO} Configuring client9-dc2..."
docker exec clab-dc2-topology-client9-dc2 sh -c "
  ip addr flush dev eth1 2>/dev/null || true
  ip addr add 10.10.10.20/24 dev eth1
  ip link set eth1 up
  ip route del default 2>/dev/null || true
  ip route add default via 10.10.10.1
"
echo -e "${OK} client9-dc2 done"

# ---------------------------------------------------------------------------
# WAIT FOR CONVERGENCE + VERIFY
# ---------------------------------------------------------------------------
echo -e "${INFO} Waiting 20s for BGP/EVPN convergence..."
sleep 20

failures=0

check_bgp_neighbor() {
    local container="$1"
    local command="$2"
    local neighbor="$3"
    local description="$4"

    if docker exec "$container" Cli -p 15 -c "$command" 2>/dev/null \
        | awk -v neighbor="$neighbor" '
            $1 == neighbor && ($NF ~ /^[0-9]+$/ || toupper($NF) ~ /ESTAB/) { established = 1 }
            END { exit(established ? 0 : 1) }
        '; then
        echo -e "${OK} ${description}"
    else
        echo -e "${FAIL} ${description}"
        failures=$((failures + 1))
    fi
}

check_ping() {
    local container="$1"
    local destination="$2"
    local count="$3"
    local description="$4"

    if docker exec "$container" ping -c "$count" -W 2 "$destination" > /dev/null 2>&1; then
        echo -e "${OK} ${description}"
    else
        echo -e "${FAIL} ${description}"
        failures=$((failures + 1))
    fi
}

echo -e "${INFO} Verifying BGP control plane..."

# Underlay: every expected spine/leaf adjacency must be Established.
check_bgp_neighbor clab-dc2-topology-spine1-dc2 "show ip bgp summary" 10.0.11.1 "spine1 <-> leaf1 underlay established"
check_bgp_neighbor clab-dc2-topology-spine1-dc2 "show ip bgp summary" 10.0.12.1 "spine1 <-> leaf2 underlay established"
check_bgp_neighbor clab-dc2-topology-spine2-dc2 "show ip bgp summary" 10.0.21.1 "spine2 <-> leaf1 underlay established"
check_bgp_neighbor clab-dc2-topology-spine2-dc2 "show ip bgp summary" 10.0.22.1 "spine2 <-> leaf2 underlay established"
check_bgp_neighbor clab-dc2-topology-leaf1-dc2 "show ip bgp summary" 10.0.11.0 "leaf1 <-> spine1 underlay established"
check_bgp_neighbor clab-dc2-topology-leaf1-dc2 "show ip bgp summary" 10.0.21.0 "leaf1 <-> spine2 underlay established"
check_bgp_neighbor clab-dc2-topology-leaf2-dc2 "show ip bgp summary" 10.0.12.0 "leaf2 <-> spine1 underlay established"
check_bgp_neighbor clab-dc2-topology-leaf2-dc2 "show ip bgp summary" 10.0.22.0 "leaf2 <-> spine2 underlay established"

# Overlay: direct leaf-to-leaf EVPN adjacency over Loopback0.
check_bgp_neighbor clab-dc2-topology-leaf1-dc2 "show bgp evpn summary" 1.1.1.12 "leaf1 <-> leaf2 EVPN established"
check_bgp_neighbor clab-dc2-topology-leaf2-dc2 "show bgp evpn summary" 1.1.1.11 "leaf2 <-> leaf1 EVPN established"

echo -e "${INFO} Verifying baseline connectivity..."

# Gateway reachability and cross-leaf connectivity, in both directions.
check_ping clab-dc2-topology-client8-dc2 10.10.10.1 2 "client8 -> gateway"
check_ping clab-dc2-topology-client9-dc2 10.10.10.1 2 "client9 -> gateway"
check_ping clab-dc2-topology-client8-dc2 10.10.10.20 3 "client8 -> client9"
check_ping clab-dc2-topology-client9-dc2 10.10.10.10 3 "client9 -> client8"

echo ""
if (( failures > 0 )); then
    echo -e "${FAIL} Baseline validation failed with ${failures} error(s). Do not run T2, T3, or T4."
    exit 1
fi

echo -e "\033[0;32mBaseline ready. You can now run T2, T3, or T4 against this fabric.\033[0m"
