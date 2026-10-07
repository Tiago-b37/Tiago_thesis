#!/bin/bash

# Spine-Leaf Startup Script
# Order: Nornir MCP -> ContainerLab -> LiteLLM

set -e

read -r -p "> Start environment? [y/N] " response
case "$response" in
    [yY]) ;;
    *) echo "Aborted."; exit 0 ;;
esac

# --- STEP 1: Nornir MCP ---
echo "--- STEP 1: Nornir MCP ---"
cd nornir_mcp || { echo "Error: nornir_mcp dir not found."; exit 1; }
docker compose up --no-build --pull never -d || { echo "Error: Docker Compose failed."; exit 1; }
cd ..
echo "Nornir MCP running."

# --- STEP 2: ContainerLab ---
echo ""
echo "--- STEP 2: ContainerLab ---"
sudo env CLAB_VERSION_CHECK=disable containerlab deploy -t dc2-topology-frr.clab.yml || echo "Warning: ContainerLab reported errors (topology may still be up)."
echo "Topology active."

# --- STEP 3: LiteLLM ---
echo ""
echo "--- STEP 3: LiteLLM ---"
if pkill -f "litellm"; then
    echo "LiteLLM process terminated."
    sleep 2
else
    echo "LiteLLM was not running."
fi
echo "LiteLLM stopped."

# --- SUMMARY ---
echo ""
echo "Deployment Finished."
echo "Run 'claude' manually when ready."
