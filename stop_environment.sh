#!/bin/bash

# Spine-Leaf Shutdown Script
# Order: ContainerLab -> Nornir MCP

set -e

read -r -p "> Stop environment? [y/N] " response
case "$response" in
    [yY]) ;;
    *) echo "Aborted."; exit 0 ;;
esac

# --- STEP 1: ContainerLab ---
echo "--- STEP 1: ContainerLab ---"
sudo containerlab destroy -t dc2-topology-frr.clab.yml --cleanup || { echo "Error: ContainerLab failed."; exit 1; }
echo "Topology destroyed."

# --- STEP 2: Nornir MCP ---
echo ""
echo "--- STEP 2: Nornir MCP ---"
cd nornir_mcp || { echo "Error: nornir_mcp dir not found."; exit 1; }
docker compose down || { echo "Error: Docker Compose down failed."; exit 1; }
cd ..
echo "Nornir MCP stopped."

# --- SUMMARY ---
echo ""
echo "Cleanup Finished."
echo "Check:"
echo "  MCP:          docker ps"
echo "  ContainerLab: sudo containerlab inspect -t dc2-topology-frr.clab.yml"