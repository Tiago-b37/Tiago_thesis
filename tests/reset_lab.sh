#!/usr/bin/env bash
set -euo pipefail

# Script to completely reset the containerlab fabric between evaluation runs.
# Assumes the clab file is dc2-topology-frr.clab.yml
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "Resetting the fabric..."

# Destroy the existing lab
clab destroy -t dc2-topology-frr.clab.yml --cleanup

# Re-deploy the lab fresh
clab deploy -t dc2-topology-frr.clab.yml --reconfigure

echo "Fabric has been reset. You can now begin a new evaluation run."
