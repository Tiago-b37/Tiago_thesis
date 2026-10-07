#!/usr/bin/env bash
set -euo pipefail

# This script injects a subtle fault into the fabric for Test 4 (Troubleshooting).
# It changes the expected remote AS of leaf1-dc2's directly connected eBGP
# underlay neighbor toward spine1-dc2. This causes the BGP underlay adjacency
# on Ethernet1 to fail without shutting the interface down.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "Injecting fault on leaf1-dc2: Changing eBGP remote AS for spine1 underlay neighbor..."

docker exec clab-dc2-topology-leaf1-dc2 Cli -p 15 -c "configure
router bgp 65101
no neighbor 10.0.11.0
neighbor 10.0.11.0 remote-as 65200
end"

echo "Fault injected. eBGP underlay adjacency between leaf1-dc2 and spine1-dc2 should drop due to remote-AS mismatch."
echo "You can now proceed with T4."
