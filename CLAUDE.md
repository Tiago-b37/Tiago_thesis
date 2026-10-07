
# Thesis Project — LLM-Driven Fabric Automation

## Context

This project implements intent-based automation of a spine-leaf data center fabric using natural language and LLMs. The system translates user requests into validated, auditable configuration changes on Arista cEOS routers, orchestrated via Containerlab and automated with Nornir MCP.

## Stack

- **Topology**: Containerlab (`dc2-topology-frr.clab.yml`) — spine-leaf with Arista cEOS
- **Automation**: Nornir MCP server (`nornir_mcp/`) — router interaction via MCP tools
- **LLM Proxy**: LiteLLM (`litellm_config.yaml`) — multi-provider proxy
- **Aliases**: `claude_aliases.sh` — bash script that starts the proxy + Claude Code on Ubuntu

## Topology Scope

- The active fabric may vary. Support up to 10 network devices total (spines + leafs); do not assume the current 2-spine/2-leaf lab unless the active inventory/topology says so.
- Use canonical Nornir `device_name` values for router operations. If the prompt or thesis test definition already supplies exact devices, client-facing leaf ports, ASNs, loopbacks, VLANs/VNIs, VRFs, and gateways, treat that as sufficient input and do not rediscover it. Resolve missing topology details from Nornir inventory / `topology.json` / `clab inspect` only when a required field is absent, ambiguous, or a validation gate fails. Resolve Linux client container names only after endpoint-verification approval with `docker ps --format '{{.Names}}'`; use `clab inspect` only when client-to-leaf/interface mapping is ambiguous.
- Names such as `spine1-dc2`, `leaf1-dc2`, `client8-dc2`, and `client9-dc2` are current lab examples, not universal constants.

## Mandatory Rules

### Zero-to-Hero Fast Path (Highest Priority)

- If the user names the devices and P2P links, skip preflight discovery (`get_fabric_health`, `list_all_hosts`, LLDP, `get_config`, `get_interfaces_ip`) before Phase 1. Also do not read `topology.json`, Containerlab YAML, or inventory files just to reconfirm supplied details. Use discovery only when a required topology/interface mapping is missing and cannot be derived from the prompt or existing conventions.
- Do not print `Structured Intent` tables, topology tables, derived payloads, pseudo-JSON, or per-device plans in prose. Keep any structured parsing internal, use one short status line per phase, and put the payload only in the tool call. Explain details only when a tool fails.
- Execute each phase as: `memory-mcp.search_device_quirks` -> `configure_fabric_bulk(mode="dry_run")` -> `apply_fabric_dry_run(dry_run_id)` -> phase gate.
- Phase 1 must be complete: every device with routed Ethernet fabric links must include the intended underlay routing protocol. For the thesis test path, prefer eBGP underlay using `bgp_neighbors[]` plus `bgp_networks[]`; OSPF remains supported only as a legacy/alternative path.
- Phase gates are the operational validation for Zero-to-Hero: Phase 1 `check_bgp_underlay_summary` for the eBGP path, Phase 2 `check_evpn_summary`, and Phase 3 one lightweight `check_dataplane_summary` gate plus approved endpoint pings.
- After Phase 3 apply, run `check_dataplane_summary` once. If it passes, ask exactly: "Fabric deployment complete. Should I proceed with the final endpoint verification (Linux client setup & Pings)?" Then STOP ALL TOOL CALLS until the user explicitly approves. Do not run Docker, shell client setup, or ping before that approval.
- After approval: resolve clients with `docker ps --format '{{.Names}}'`, configure `eth1`, run `sleep 15`, then run endpoint pings. Use `ping -q -c 3` for client tests. After the required pings, produce the final summary without additional MCP validation or raw-command diagnostics. Defer comprehensive post-run verification to `tests/validate_results.py`.
- Requests framed as `audit`, `verify`, `validate`, `check`, or `confirm` are read-only by default. Do not turn a validation request into a configuration change unless the user explicitly asks to remediate, configure, migrate, fix, or apply changes after the findings are reported.

### Tokens and context

- **NEVER read log, pcap, or CSV files directly.** Instead, write a Python script that extracts only the needed information.
- **Be concise.** The models used have limited context windows (128K). Avoid long and redundant responses.
- The `clab-dc2-topology/` folder contains internal router configs and logs — **ignore it completely** unless explicitly asked.

### Efficiency — Always Use the Cheapest Solution

> **GOLDEN RULE:** Before using ANY MCP tool, ask yourself: *"Is this information required for the next payload or gate?"*
> If not, skip the read. Use shell only for external lab/container facts and MCP only for router state; do not run shell or MCP discovery just to build a "complete picture."

**Decision hierarchy (cheapest first):**

1. 🟢 **Shell commands** (instant, zero tokens) — `docker ps` for client containers after approval, `cat`, `grep`; `clab inspect` only when topology/link mapping is missing or ambiguous
2. 🟡 **Bulk MCP tools** (one call, multiple devices) — `list_all_hosts`, `get_fabric_health` only when topology is missing, ambiguous, or a gate failed
3. 🔴 **Individual MCP tools** (one call per device) — `is_alive`, `get_facts`, `send_command`

### Diagnostic Reference Routing

- Keep normal deployment and phase validation on the compact summary tools named below; no command catalog is needed for the fast path.
- When `fabric-diagnostics` is active and a summary tool does not provide enough evidence, read `.claude/skills/fabric-diagnostics/references/command-reference.md` only for the current diagnostic layer. Do not load that reference during a healthy T1-T3 deployment.

### [CRITICAL] Rules for Arista cEOS Interactivity

- **OUTSIDE THE ROUTER**: To check if a container is running, or what interfaces exist in the topology, use shell tools (`clab inspect -f json`, `docker ps`).
- **INSIDE THE ROUTER**: To get ANY configuration, state, IP addresses, or routing tables from INSIDE an Arista router, you **MUST EXCLUSIVELY** use the Nornir MCP tools (e.g., `send_command`, `get_interfaces_ip`).
- **NEVER** attempt to run linux commands (`ip addr`, `cat`) via `docker exec` on cEOS containers.
- **NEVER** attempt to run EOS CLI commands via `docker exec`. The shell will hang and crash your session.
- **Linux clients use `eth1` for data traffic.** `eth0` is reserved for ContainerLab management — never configure IPs on `eth0`.

### [CRITICAL] send_command is READ-ONLY by policy

- `send_command` runs in EOS exec mode; use it only for read-only queries, except an explicitly approved `clear ...` under the debug rule below.
- **NEVER** use `send_command` to push configuration (e.g., `ip routing`, `router ospf`, `configure terminal`). It will NOT persist and may timeout.
- **HARD BLOCK via policy/blacklist** for config/destructive intents in `send_command`: `configure`, `conf t`, `reload`, `write memory`, `copy running-config startup-config`, `no <...>`.
- **Telemetry overload & Day-N Troubleshooting**:
  - During Zero-To-Hero deployments, NEVER use `send_command` or `send_command_to_devices` to run ANY `show` command that returns lists or tables during a configuration or validation phase (e.g., `show running-config`, `show mac address-table`, `show vxlan vni detail`).
  - If doing Day-N maintenance or if a validation ping/summary tool fails after convergence: You ARE ALLOWED to use `send_command` with targeted show commands (e.g., `show mac address-table`, `show bgp evpn summary`) for analytical troubleshooting without artificially loading the `fabric-diagnostics` skill.
  - Abstract Summary tools (`check_bgp_underlay_summary`, `check_ospf_summary`, `check_evpn_summary`) are preferred for validation, but no longer rigidly enforce bans on raw generic CLI queries.
  - CONVERGENCE LOOP: Only after a successful apply, retry a false/empty summary up to 3 times with `sleep 10`. In a read-only audit or incident, treat it as fault evidence.
- **Operational exception (debug only):** `clear ...` commands are allowed only with explicit user confirmation in the same interaction. If confirmation is missing, do not execute.
- **ALL configuration changes** must go through `configure_fabric_bulk` for multi-device work or `configure_device_bulk` for single-device work. Use the remaining dedicated tools only for operations not represented in the bulk schema (`configure_vrf` only for standalone single-device VRF work, `configure_mlag`, and delete tools).
- `ip routing` is **automatically included** by the bulk configuration helpers for OSPF, BGP, and routed interfaces - no manual step needed.

#### Compact Validation and Diagnostic Routing

- eBGP underlay gate: `check_bgp_underlay_summary(device_names)` on all intended underlay devices.
- OSPF underlay gate: `check_ospf_summary(device_names)` only when OSPF is the selected underlay.
- EVPN overlay gate: `check_evpn_summary(device_names)` on all intended overlay devices.
- Dataplane gate: `check_dataplane_summary(device_names, expected_vni, expected_vlan, expected_gateway)`.
- Use targeted structured reads such as `get_interfaces_ip`, `get_lldp_neighbors`, `get_bgp_neighbors`, or `get_bgp_neighbors_detail` only when a specific invariant or diagnostic layer requires them. Detailed read-only lookup belongs to `fabric-diagnostics`.

#### Query Multiple Devices Concurrently

Prefer summary tools. If they cannot provide required multi-device evidence, use one targeted `send_command_to_devices` call.

#### Configuration (Use MCP — Always `dry_run` First)

> **FABRIC BULK OPTIMIZATION RULE — MANDATORY**: You MUST use `configure_fabric_bulk` whenever configuring multiple devices at once. One call to `configure_fabric_bulk` per phase for the entire fabric.
> **ZERO-FRAGMENTATION**: Phase 3 (Dataplane) MUST be a single `configure_fabric_bulk` transaction. Do NOT split VLAN, VXLAN, and SVI into separate calls.
>
> **`[HARD BLOCK]` ANTI-FALLBACK**: If `configure_fabric_bulk` fails with a JSON schema/validation error, you MUST read the error message, fix the JSON, and retry `configure_fabric_bulk`. You are **STRICTLY FORBIDDEN** from falling back to per-device `configure_device_bulk` calls as a workaround for schema errors. `configure_device_bulk` may only be used for single-device operations explicitly requested by the user, OR if `configure_fabric_bulk` fails with a server-side error (HTTP 5xx or timeout). A schema error is YOUR mistake — fix it and retry. **EXCEPTION**: After a phase completes and diagnostics identify a specific individual issue (e.g., a single access port in wrong VLAN), you MAY use `configure_device_bulk` with a one-device/one-item payload for targeted remediation. This is remediation, NOT a bulk fallback.
>
> **JSON TOKEN ECONOMY**:
>
> - **MANDATORY SCHEMA**: Fields `ospf`, `bgp_neighbors`, `bgp_networks`, `vlans`, `interfaces`, `svis`, `vxlan`, `evpn_peers`, and `evpn_rd_rt` MUST ALWAYS BE LISTS of objects, NEVER direct dictionaries!
> - **OMIT empty keys**: NEVER include keys with empty lists (e.g., `"svis": []`). If a feature is not used, remove the key entirely.
> - **OMIT unrequested default values**: DO NOT send fields that merely repeat system defaults (e.g., `area: 0.0.0.0`, `passive: false`). Values explicitly required by the approved intent, including operational attributes such as MTU, must be preserved end to end. A fabric MTU requested for physical underlay links does not apply to Loopbacks or SVIs unless the intent explicitly says so.
> - **Summary Limit**: Limit "Intent Summaries" to <10 lines of essence.

> **AUTONOMOUS EXECUTION RULE**: After the user gives an initial configuration request, proceed through Phases 1 & 2 autonomously (`configure_fabric_bulk` dry-run → `apply_fabric_dry_run` → summary). Only stop if a phase **fails** validation.

> **PHASE EXIT GATES & HARD STOP**:
>
> - Before moving to the next Phase, you MUST confirm convergence using summary tools (`check_bgp_underlay_summary` for the eBGP underlay path, `check_ospf_summary` only for OSPF underlay, `check_evpn_summary`, `check_dataplane_summary`).
> - If a Phase Gate remains unmet, **STOP** and offer diagnostics. Approval may authorize diagnosis or remediation, never skipping the gate.

> **PERFORMANCE & VELOCITY RULES (CRITICAL)**:
>
> - **NO TASK BLOCKS**: You are **STRONGLY FORBIDDEN** from using the internal `Task()` or `sub-task` functionality of the AI assistant for standard fabric phases. Do NOT create planning checklists in separate UI tabs. Execute all tool calls directly in the terminal flow to avoid orchestration overhead and slow inference times.
> - **RAPID PIPELINE**: Send `mode: dry_run`, capture the returned `dry_run_id`, then call `apply_fabric_dry_run` with that id in immediate succession. Do NOT pause to summarize, explain, or wait for confirmation between dry-run and apply inside a phase unless the dry-run fails.

## Workflow Enforcement (Safety)

- **WorkflowGuard**: Every apply MUST have a matching `dry_run` fingerprint. For fabric phases, prefer `apply_fabric_dry_run(dry_run_id=...)` so apply uses the exact validated artifact without resending the full payload.
- **eBGP Underlay Safety**: For the thesis test path, use directly connected eBGP neighbors on spine-leaf P2P links and advertise Loopback0 via `bgp_networks[]`.
- **OSPF Safety**: OSPF remains supported as a legacy/alternative underlay; the server forces `passive: false` on point-to-point links if the intent is P2P.
- **Convergence First**: If summary tools fail after the allowed retries, STOP and ask the user whether to start `fabric-diagnostics`; do not launch diagnostics or remediation automatically.

> **PROTOCOL COMPLETENESS PRINCIPLE (MANDATORY)**: Fully represent objects and dependencies within the approved scope; do not expand that scope.
>
> - **Intent Scope and EVPN Service Safety**: Generate only features explicitly requested or strictly required by the selected design. An L2VNI, VXLAN service, or anycast SVI does not by itself require a VRF, L3VNI, or Symmetric IRB. For every intended EVPN exchange, route-target export/import policies must be compatible in each required direction; never derive a different service RT independently from each device's `local_as`.
> - **DEVICE ROLE AWARENESS**:
>   - **Spines**: Only receive `interfaces` and underlay routing fields (`bgp_neighbors`/`bgp_networks` for the thesis eBGP path, or `ospf` for legacy OSPF). Add EVPN overlay fields on spines only if the requested design explicitly makes them route reflectors or route servers. **NEVER** send `vlans`, `vxlan`, `evpn_rd_rt`, or `svis` for Spines. The server ignores them, but sending them wastes tokens.
>   - **Leaves** (VTEPs): Receive the full payload including VXLAN/VNI and SVI Gateway config.
> - **BGP Multihop**: OMIT `ebgp_multihop` for directly connected eBGP underlay sessions and for iBGP sessions. Use `ebgp_multihop` only for loopback-based eBGP overlay peers.
> - **Interface Completeness**: Any interface participating in the Underlay MUST be defined in the `interfaces[]` list with its `ip_address` AND `mtu`. **CRITICAL**: Defining a subnet in `ospf[].networks` or a prefix in `bgp_networks[]` DOES NOT configure the IP on the interface!
> - **Deterministic /31 Assignment**: For spine-leaf P2P subnets, assign the lower/even address to the spine endpoint and the higher/odd address to the leaf endpoint.
> - **eBGP Underlay Completeness**: For the thesis test path, each spine-leaf P2P link needs a direct `bgp_neighbors[]` entry on both ends using the peer's P2P IP and remote AS. Each device must also advertise its Loopback0 /32 using `bgp_networks[]`.
> - **OSPF Local-Scope Networks**: Only applies when the selected underlay is OSPF. Each device's `ospf[].networks[]` MUST include only that device's local Loopback0 /32 and directly attached P2P subnets.
> - **BGP Loopback Peering Completeness**: For every BGP peer formed via Loopback0, the device payload MUST include `local_as`, and every `bgp_neighbors[]` entry MUST include `remote_as` and `update_source: "Loopback0"`. Use a per-neighbor `local_as` only for an intentional override. For loopback-based eBGP overlay peers, include `ebgp_multihop`; do not rely on backend defaults for loopback peering.
> - **EVPN Overlay Scope**: The default thesis design uses direct leaf-to-leaf eBGP EVPN over VTEP loopbacks. Spines provide underlay reachability and are not EVPN participants unless the user explicitly asks for route reflectors or route servers. Do NOT set `route_reflector_client` unless the user explicitly asks for iBGP route reflectors or all overlay peers share the same AS.
> - **Route Reflector Topology Scope**: Only applies when the user explicitly asks for iBGP route reflectors. In that design, the intended EVPN overlay peering is leaf-to-spine only. Do NOT create leaf-to-leaf BGP neighbors, and do NOT add extra spine-to-spine EVPN peers, unless the user explicitly asks for a full mesh or inter-RR peering.
> - **BGP EVPN Peering**: When configuring the default overlay, participating VTEP leaves MUST activate the EVPN address-family for their loopback BGP neighbors. Include spines in `evpn_peers[]` only when they are explicitly part of the EVPN overlay design.
> - **VXLAN Head-End Replication (No Multicast)**: In this project, when the user asks for "head-end replication" or "no multicast", configure explicit ingress replication with `flood_vteps` in `vxlan[]`. Each participating leaf VTEP must list all other participating leaf VTEP loopbacks resolved from the payload/inventory.
> - **Client Access Ports (CRITICAL — Include in Phase 1)**: Interfaces connecting to end-hosts/clients MUST be configured as Layer 2 access ports using `switchport_mode: "access"` and `access_vlan: X` within the `interfaces[]` list of the Phase 1 `configure_fabric_bulk` call. The server's Deferred-Guard will automatically hold them and inject them in Phase 3. **NEVER configure access ports in a separate `configure_fabric_bulk` call after Phase 3** — this is a remediation anti-pattern that wastes tokens and breaks the workflow.
>   - Derive all requested client-facing leaf ports and access VLAN assignments from the approved intent or active topology; do not assume fixed device, port, client, or VLAN identifiers.
>   - If these client-facing ports are missing from the Phase 1 payload, the payload is invalid. Fix Phase 1 before calling `configure_fabric_bulk`; do not move the missing access ports into Phase 3 as a workaround.
> - **Anycast SVI Addressing**: Select the EOS addressing mode from the approved intent. For a non-VRF/legacy anycast SVI, use a unique per-leaf `ip_address` plus the shared `virtual_ip`; do not set them equal unless explicitly requested. For a VRF-bound anycast SVI (Symmetric IRB), set `vrf` and the shared `virtual_ip` with its prefix, and omit `ip_address`; the backend renders `ip address virtual`. Never mix the two modes.
> - **EVPN Route-Target Derivation**: Preserve any explicit RT policy in the approved intent. When the selected convention is `<fabric-admin-AS>:<VNI>`, use the associated L2VNI or L3VNI as the local administrator, never the VLAN ID.
> - **OSPF Adjacency Rules**: If you set `passive_default: true` to optimize routing, you MUST explicitly list the P2P fabric links inside the `ospf[].interfaces[]` array to disable passive mode on those specific links (e.g. `passive: false`, `network_type: point-to-point`). Otherwise, OSPF Hello packets are suppressed and the entire Underlay will fail to converge.
> - **No Redundant Calls**: If a configuration was already applied in a previous phase (e.g., access ports included in Phase 1), do NOT re-apply or re-confirm it in a later phase. The server is stateful — trust that what was applied is active.

### Nornir MCP

- To interact with router CLI, use Nornir MCP tools listed above.
- Nornir inventories and configs are in `nornir_mcp/conf/`.
- **Arista Overlap Guard**: EOS rejects overlapping interface subnets. Bulk cannot remove an IP (`null` is sanitized and `shutdown` does not remove it); require a supported delete operation or explicitly approved manual cleanup before moving the subnet.
- **Phased Deployment Strategy (MANDATORY)**: You MUST deploy the fabric in sequential phases across all devices using `configure_fabric_bulk`:
  - **Before every phase**: complete the matching `memory-mcp.search_device_quirks` call with `operation_type`, `intent_class`, and `phase`. If the memory tool is available and this lookup is skipped, the phase is invalid; do not call `configure_fabric_bulk` for that phase until the memory lookup has completed.
  - **Phase 1 (Underlay)**: Deploy `interfaces`, directly connected eBGP `bgp_neighbors`, and Loopback0 `bgp_networks` for every device with routed fabric links. The `interfaces[]` payload must include Loopback0, all fabric P2P links, and all requested client access ports. After `apply_fabric_dry_run`, run `sleep 10`, then `check_bgp_underlay_summary`; if not Established, retry up to 3 times with `sleep 10`. Use `ospf` and `check_ospf_summary` only if the user explicitly selected an OSPF underlay.
  - **Phase 2 Exit Gate (MANDATORY)**: Deploy loopback-based overlay `bgp_neighbors` and `evpn_peers` on the participating VTEP leaves (`configure_fabric_bulk mode=dry_run` → `apply_fabric_dry_run`). All Loopback0 peerings must include `update_source: "Loopback0"`; eBGP overlay peerings must also include `ebgp_multihop`. Do not mark EVPN peers as RR clients unless the requested design is iBGP route reflection. After `apply_fabric_dry_run`, run `sleep 10`, then call `check_evpn_summary` on ALL intended overlay devices, normally the leaves only. If all intended peers are Established → proceed to Phase 3. If not: sleep 10 (EXACTLY 10 seconds), retry up to 3 times. If still fails → STOP. DO NOT proceed to Phase 3 without confirmed EVPN Established!
  - **Phase 2 parser artifacts**: If `check_evpn_summary` reports `all_established: false` only because of an obvious non-neighbor/header parser artifact, but every intended overlay neighbor pair is present and Established, treat the Phase 2 gate as passed. Do not ignore any real neighbor that is Idle, Active, Connect, missing, or not Established.
  - **Phase 3 (Dataplane)**: Deploy `vxlan`, `vlans`, `evpn_rd_rt`, and `svis` in one call. Every device payload containing BGP-dependent objects (`bgp_neighbors`, `bgp_networks`, `evpn_peers`, `evpn_rd_rt`, or a VRF with RD/RT) must include device-level `local_as`, even when the AS appeared in an earlier phase. Every L2 entry in `vxlan[]` must include both `vni` and its matching `vlan_id` from `vlans[]`. Do not newly introduce access ports here; they must have been present in Phase 1 and deferred by the server. When the request specifies head-end replication/no multicast, include explicit `flood_vteps` for the remote leaf VTEPs.
- **PHASE 3 EXACT VERIFICATION SEQUENCE (MANDATORY)**: After the `apply` call for Phase 3 completes:
  1. **DATAPLANE GATE**: Run `check_dataplane_summary` once for the intended VLAN/VNI/gateway. This is a lightweight fabric-state gate, not an endpoint test.
  2. **STOP & ASK**: If the dataplane gate passes, ask the user: *"Fabric deployment complete. Should I proceed with the final endpoint verification (Linux client setup & Pings)?"*. This is a hard execution boundary: after asking, the answer to the user is the final action in the turn. STOP ALL TOOL CALLS and wait for the user's answer. Do not run Docker, shell client setup, or ping before approval.
  3. **CONFIG LINUX**: AFTER user approval, IMMEDIATELY resolve the requested Linux client containers with `docker ps --format '{{.Names}}'`; use `clab inspect` only if client-to-leaf/interface mapping is ambiguous. Then configure them idempotently via `docker exec <client-container> ip link set eth1 up`, `docker exec <client-container> ip addr replace <ip>/<cidr> dev eth1`, and `docker exec <client-container> ip route replace default via <gateway-ip> dev eth1`. When the approved intent migrates a client to a different IP address or subnet, first run `docker exec <client-container> ip -4 addr flush dev eth1` so the previous service address does not remain active, then apply the new address and route. (Do NOT use `ip addr add ... && ip route add ...`; if the address already exists, the route command will be skipped. Do NOT guess short container names when `docker ps` returned clab-prefixed names).
  4. **SLEEP**: Run `sleep 15` after client setup as the deterministic thesis-test window, not a universal convergence guarantee.
  5. **ENDPOINT VALIDATION**: ONLY AFTER the sleep completes are you allowed to execute client pings. Derive the probe matrix from the parsed intent: test every changed endpoint against its gateway and test both directions for every same-tenant endpoint pair involved in the change. Use `ping -q -c 3` to keep output compact. Never claim bidirectional reachability unless both directions were executed successfully; if a required shell command needs permission, request it instead of omitting the probe.
- **Validation**: `validate_params` supports `FabricBulkConfigModel`, but the required normal gate is `configure_fabric_bulk(mode="dry_run")`, which generates the exact apply artifact.
- **Intent Summary**: After completing ALL configuration phases, output ONE compact final Natural Language Intent Summary covering the full run. Derive device names, addresses, protocol state, and test results only from the approved intent and successful tool evidence; cross-check endpoint addresses against the executed client commands before responding. Use plain text or short bullets only; do NOT use markdown tables, box-drawing tables, pseudo-JSON, or per-phase confirmation summaries.

## Operational Memory MCP (Mandatory Guardrails)

- Before any mutating network operation, call `search_device_quirks` with canonical Nornir `device_name` values.
- For `configure_fabric_bulk`, query memory once per deployment phase, not once per device.
- For zero-to-hero fabric deployments, memory lookup is a hard phase gate:
  1. Before Phase 1 underlay, call `search_device_quirks` with `operation_type="configure_fabric_bulk"`, `intent_class="zero_to_hero_fabric"`, and `phase="underlay"`.
  2. Before Phase 2 overlay, call `search_device_quirks` with `operation_type="configure_fabric_bulk"`, `intent_class="zero_to_hero_fabric"`, and `phase="overlay"`.
  3. Before Phase 3 dataplane, call `search_device_quirks` with `operation_type="configure_fabric_bulk"`, `intent_class="zero_to_hero_fabric"`, and `phase="dataplane"`.
  4. Do not start a phase until its memory lookup has completed, unless the memory MCP server is unavailable.
- Include `operation_type`, `intent_class`, and `phase` when they are known, so retrieval stays precise.
- Treat memory as advisory context only. Nornir inventory remains the source of truth for devices, topology, platform, and roles.
- Never store passwords, secrets, tokens, raw configs, long command outputs, large JSON payloads, or speculative diagnoses.
- After any failed validation, failed phase gate, `fabric-diagnostics` run, or targeted remediation that later succeeds, evaluate whether a stable operational lesson was learned.
- If a clear lesson exists, propose a compact memory episode JSON to the user before saving. Do not propose memory for transient convergence delays, malformed JSON fixes, unclear root causes, duplicate lessons, secrets, raw configs, or long command outputs.
- Before proposing a new episode, check whether an existing memory already covers the same stable rule. Prefer reusing or superseding an existing lesson over saving a near-duplicate.
- Before `save_episode`, show the exact JSON to persist: `episode` with its required fields (`device_target`, `operation_executed`, `result`, `root_cause`, `proposed_rule`, `confidence`) and every populated optional field; `context` with `device_names` and every populated context field.
- Save only after explicit approval, sending those objects unchanged plus `approval`. Use `approved` only for an exact approval and `approved_with_changes` only for the user's explicit edits; never fabricate approval.

## Workflow Enforcement (Mandatory)

For any request that changes topology, interfaces, VLAN/VNI, VRF, BGP/EVPN, or VXLAN, execute this exact order:

1. Load `naming-conventions` first.
2. Explicitly load/run `intent-parser` to produce structured parameters, even if the user already provided most details.

- If `intent-parser` output is incomplete, abort and ask the user to clarify before proceeding.

1. Explicitly load/run `pre-deploy-validation` before any mutating tool call.
2. For each phase: run the required `memory-mcp.search_device_quirks` lookup, then call `configure_fabric_bulk` with `mode=dry_run`, then immediately apply the returned `dry_run_id` with `apply_fabric_dry_run`. **Do NOT stop between phases to ask for confirmation** — proceed autonomously unless an error occurs.
3. For predefined thesis tests T1-T3, use the built-in phase exit criteria as operational validation. Explicitly load/run the `change-validation` skill only for user-requested validation/audit, unclear validation criteria, failed gates, diagnostics, or remediation.
4. If validation fails after the defined retries/check sequence, STOP and ask the user whether to run `fabric-diagnostics`; consider rollback only after diagnostics and explicit user approval, using supported MCP operations and never an automatic fabric-wide rollback.
5. After ALL phases complete successfully, output ONE compact final summary to the user, without tables.

If any step above is skipped, abort and report which gate failed.

For requests framed as audit/verify/validate/check/confirm against existing state:

1. Load `naming-conventions` first when topology identifiers, VLANs, VNIs, VRFs, IPs, or device names are involved.
2. Explicitly load/run `change-validation` if the task is post-change validation or audit-oriented.
3. Use read tools and validation tools only. If the expected object/state is absent, report that finding and stop.
4. Only mutate after the user explicitly asks for remediation or approval to proceed with a change.

## Dry-Run / Apply Traceability (Mandatory)

- Each `apply` must have a corresponding dry-run for the same device and same config block in the current phase.
- For fabric phases, the traceability artifact is the returned `dry_run_id`; use `apply_fabric_dry_run` so the server applies the exact commands generated by dry-run without regenerating or resending the full payload. If `apply_fabric_dry_run` is unavailable or returns `DryRunNotFound`, repeat the dry-run and apply the new ID; do not reuse a stale artifact.
- **Fingerprint Matching**: The `WorkflowGuard` in `server_stdio.py` tracks these intents. If you change a parameter between dry-run and apply, the operation will be rejected.
- Do not batch applies that cannot be mapped to a visible dry-run artifact.

## Final Validation Criteria (Mandatory)

- **Anycast Reachability**: Ping the `virtual_ip` from clients with `ping -q -c 3`.
- **Overlapping Tenant Validation**: If a Day-N request adds tenants with overlapping IP space and VRF/Symmetric IRB isolation, validate both directions inside each tenant, gateway reachability in each VRF, and blocked cross-tenant probes in both directions. Keep the validation compact and do not print repeated planning text.

Do not mark tasks complete unless the corresponding exit criteria are satisfied.
