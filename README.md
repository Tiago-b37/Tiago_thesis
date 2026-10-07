# LLM-Assisted EVPN/VXLAN Network Configuration

This project implements the prototype evaluated in a master's dissertation on
using Large Language Models to configure and operate a spine-leaf fabric.
The agent runs in Claude Code and uses MCP tools to interact with a
Nornir/NAPALM backend. Evaluation considers the resulting network state,
the sequence of operations and compliance with the execution workflow.

The lab contains two Arista cEOS spines, two leaf VTEPs and four Alpine Linux
clients. Its target configuration uses an eBGP underlay, a direct leaf-to-leaf
eBGP EVPN overlay and VXLAN head-end replication. Spines provide underlay
reachability; the leaves host the tenant services.

## Architecture

```text
Claude Code + project instructions + local skills
  -> LiteLLM proxy -> selected language model
  -> MCP over stdio -> Nornir backend in Docker -> NAPALM -> cEOS devices
  -> MCP over stdio -> local Memory MCP -> operational lessons in JSON
```

[.mcp.json](.mcp.json) defines the two MCP connections. Docker Compose keeps
`nornir-mcp-server` running, and Claude Code starts `server_stdio.py` inside it
through `docker exec -i`. The backend MCP server does not expose an HTTP port.
The Memory MCP runs as a separate local Python process.

The network backend provides inventory access, operational getters,
configuration tools and compact BGP, EVPN and dataplane summaries. Its main
configuration path is `configure_fabric_bulk(mode="dry_run")` followed by
`apply_fabric_dry_run(dry_run_id)`. Single-device configuration and removal
operations use a matching prior dry-run without a fabric artifact.

Execution controls include typed input validation, semantic payload checks,
role-based filtering, deferred access-port configuration and dry-run/apply
matching. Fabric artifacts belong to the current server process, expire after
one hour and are consumed after a successful application. Multi-device
application is not an atomic transaction and does not provide automatic rollback.

Operator approval and a successful dry-run are different conditions. The agent
instructions require approval before the final Linux-client setup and ping
verification. T4 starts as a read-only investigation; correcting the diagnosed
fault requires subsequent approval. Saving an operational-memory lesson requires
separate approval of the proposed record.

## Setup

All commands assume a Linux shell opened in the directory containing this
README, `.mcp.json` and `litellm_config.yaml`. If the checkout contains the
project under `1tese/`, enter that directory first.

### Requirements

- Bash, Docker and Docker Compose, with Docker access for the current user.
- Containerlab and permission to deploy and destroy the lab with `sudo`.
- Locally available images `ceos:4.34.3.1M` and `alpine:latest`.
- Python 3.12, matching the backend Docker image.
- Claude Code, LiteLLM and credentials for the selected providers.

The cEOS image is not distributed in this repository. The topology uses
`image-pull-policy: Never`, so both lab images must exist before deployment.
`alpine:latest` is not pinned to a release. The recorded campaign used
Claude Code v2.1.62; the setup does not pin every dependency or reproduce an
identical historical environment.

Create and activate a host-side virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install "nornir==3.5.0" nornir-napalm "mcp[cli]==1.15.0" sse-starlette pytest
python3 -m pip install "litellm[proxy]"
```

These dependencies support the local Memory MCP and live validator as well as
the proxy. Build the backend image once, before the first startup:

```bash
docker compose -f nornir_mcp/docker-compose.yml build nornir-mcp
```

The build can download dependencies. Subsequent startup uses
`--no-build --pull never` for the backend container. The Dockerfile installs
dependencies directly; it does not install the Python package or use `uv.lock`.

### Credentials and Model Selection

Only three model routes are configured:

| Route | Role | Provider variable |
|---|---|---|
| `mimo-v2.5` | Main model in `settings.mimo.json` | `XIAOMI_API_KEY` |
| `deepseek-v4-flash` | Main model in `settings.deepseek.json` | `DEEPSEEK_API_KEY` |
| `glm-4.7-flash` | Auxiliary Haiku route in both presets | `ZAI_AUTH_TOKEN` |

The presets map both Sonnet and Opus to the selected main model. Mapping Haiku
to GLM does not mean that every file read is delegated to it. Provider endpoints
and request parameters are defined in [litellm_config.yaml](litellm_config.yaml).

[.env.example](.env.example) contains empty provider variables. For the helper's
relative credential location, copy it to the directory above the project:

```bash
cp -n .env.example ../.env
```

Fill in the selected main provider's key and the GLM token in that private
file. Do not commit credentials. The helper first checks
`/media/sf_Codigo_tese/.env`, then `$HOME/Codigo_tese/.env`, then the file above
its own directory; an existing file at an earlier location takes precedence.
The `admin/admin` credentials in the Nornir inventory are for this isolated lab.

Select one model preset. Review or back up existing user-wide settings before
replacing `~/.claude/settings.json`; merge the preset's `env` entries instead
if existing settings must be retained.

```bash
mkdir -p ~/.claude
cp settings.mimo.json ~/.claude/settings.json
# Alternatively: cp settings.deepseek.json ~/.claude/settings.json
cp -n .claude/settings.local.example.json .claude/settings.local.json
```

The local permission example is not loaded until copied. It permits selected
MCP tools and lab commands and asks before memory writes. It is not a complete
host sandbox or a guarantee that every accepted device command is read-only.

### Start and Stop

The helper currently assumes the VM path
`/media/sf_Codigo_tese/1tese/litellm_config.yaml` and the Claude Code executable
`/usr/local/bin/claude`. Adjust those paths in
[claude_aliases.sh](claude_aliases.sh) before using a different installation.

```bash
source ./claude_aliases.sh
bash start_environment.sh
claude
```

Confirm the startup prompt. The script starts the backend container, deploys
the topology and stops an existing LiteLLM process. Calling `claude` without
arguments then starts the proxy on port 4000 and launches the agent with
automatic updates disabled. The shell and its virtual environment must remain
active so the local MCP server can use the installed Python dependencies.

After closing the agent session:

```bash
bash stop_environment.sh
claudeq
```

The stop script destroys the lab and stops the backend container; `claudeq`
stops LiteLLM. Use these scripts on a dedicated lab host: they reset lab state
and terminate processes matching `litellm`.

## Operational Memory

The memory server stores operator-approved lessons in
`nornir_mcp/memory_mcp/data/episodes.json`. It does not save every observation
or detected problem automatically. When the memory server is available, the
agent instructions require a lookup before each phase that modifies the
fabric, using the device names, phase and intent context.

`search_device_quirks` returns compact applicable lessons. The agent must
combine them with live observations rather than treat them as current device
state. `save_episode` records a proposed lesson after separate approval;
duplicate active lessons reuse the existing episode. `list_memory_episodes`
and `get_memory_episode` provide read-only inspection of stored records.

The runtime store is private and is not published. An absent store is read as
empty and created when a lesson is saved. `MEMORY_MCP_STORE_PATH` selects an
alternative JSON file and must be exported before starting a new agent session.
Resetting Containerlab does not clear memory. The evaluation README explains
how to isolate memory and reuse the preserved M0 episode without editing it.

## Evaluation and Repository Layout

[tests/README.md](tests/README.md) documents T1-T4, the M0/M1 memory case,
post-run validation, unit tests and all seventeen recorded transcripts.
The live validator checks T1-T3. T4 is analysed from the complete transcript,
including diagnosis, approval, correction and the subsequent BGP check.

| Location | Contents |
|---|---|
| [CLAUDE.md](CLAUDE.md), [.claude/skills/](.claude/skills/) | Agent instructions and local skills |
| [.mcp.json](.mcp.json), model presets and proxy configuration | Client connections and model selection |
| [dc2-topology-frr.clab.yml](dc2-topology-frr.clab.yml), [configs/](configs/) | Source topology and initial switch configurations |
| [nornir_mcp/](nornir_mcp/) | Stdio backend, command generation and validation |
| [nornir_mcp/conf/](nornir_mcp/conf/) | Inventory, connection settings and command blacklist |
| [nornir_mcp/memory_mcp/](nornir_mcp/memory_mcp/) | Operational-memory implementation |
| [tests/](tests/) | Prompts, preparation scripts, validators and unit tests |
| [tests/results/](tests/results/) | Preserved transcripts, validation JSONs and raw token/cost records |

`clab-dc2-topology/` is generated runtime state, not the source topology.
The recorded evidence retains its filenames and contents. Current instructions
and skills include post-campaign changes, so this checkout is not a
byte-identical snapshot of the evaluation environment.

## Scope and Attribution

The prepared configuration operations target EOS/cEOS and the supplied lab.
The diagnostic command blacklist blocks selected commands, not every possible
state-changing command. Execution controls do not verify every statement in
an agent's report; explanations still need checking against tool outputs.
This is a research prototype, not a production deployment guarantee.

The backend's original MIT license and attribution are retained in
[nornir_mcp/LICENSE](nornir_mcp/LICENSE).
