# Evaluation and Recorded Evidence

This directory contains the supervised evaluation workflows, lab-preparation
scripts, post-run validator and preserved evidence. See the
[main README](../README.md) for installation, model presets and MCP startup.
All commands below run from the project directory, not from inside `tests/`.

## Scenarios and Campaign

| Scenario | Starting state | Requested outcome |
|---|---|---|
| T1 - Initial provisioning | Clean lab | eBGP underlay, leaf-to-leaf EVPN, VXLAN and VLAN 10/VNI 10010 with client connectivity |
| T2 - Tenant migration | Fresh T1-equivalent baseline | VLAN 20/VNI 10020 on 10.20.20.0/24, working client connectivity and old VLAN 10/VNI 10010 removed |
| T3 - Tenant isolation | Fresh T1-equivalent baseline | BLUE and RED use 10.10.10.0/24 in separate VRFs, with internal connectivity and cross-tenant isolation |
| T4 - Fault diagnosis and approved correction | Fresh baseline with injected remote-AS mismatch | Read-only diagnosis, followed by an approved correction and BGP verification |

The recorded campaign contains sixteen normal executions: two repetitions per
model and scenario for MiMo and DeepSeek. M0 is one of the normal DeepSeek T4
executions, not another run. M1 is the additional memory-reuse execution,
bringing the total to seventeen. R1/R2 are repetitions within a model and
scenario, not controlled pairs between models.

The analysis considers network results, discovery and configuration decisions,
recovery from rejected calls and process compliance. Two repetitions per case
do not establish statistical reliability. The recorded runs used a fixed setup;
the current checkout includes post-campaign changes as noted in the main README.

## Files

| File | Purpose |
|---|---|
| [test_prompts.yaml](test_prompts.yaml), [prompts/](prompts/) | Scenario definitions and matching plain-text prompts |
| [prepare_baseline.sh](prepare_baseline.sh) | Deterministic T1-equivalent baseline for T2-T4 |
| [reset_lab.sh](reset_lab.sh) | Destroy and redeploy the network lab |
| [inject_fault_t4.sh](inject_fault_t4.sh) | Set leaf1's remote AS toward spine1 to 65200 instead of 65000 |
| [validate_results.py](validate_results.py) | Post-run network and endpoint checks for T1-T3 |
| [generate_report.py](generate_report.py) | Aggregate saved validation JSONs and optional annotations |
| [memory_episode_m0.json](memory_episode_m0.json) | Preserved M0 episode for the M1 reuse case |
| [results/](results/) | Original transcripts, supporting validation records and raw token/cost output |

## Prepare an Independent Execution

Every normal execution needs a fresh network state, a new agent session and
empty operational memory. T2 removes the tenant required by T3's baseline,
so do not run T1-T4 sequentially against one persistent lab state.

Use a separate directory for new results and a unique label for each run:

```bash
RESULTS_DIR="$(mktemp -d -t 1tese-results.XXXXXX)"
RUN_LABEL=mimo_t1_r1
```

Keep `RESULTS_DIR` when collecting several new runs and change `RUN_LABEL` for
each execution. Before opening each normal agent session, create a new empty
memory file:

```bash
export MEMORY_MCP_STORE_PATH="$(mktemp -t 1tese-memory-normal.XXXXXX)"
printf '{"version":1,"episodes":[]}\n' > "$MEMORY_MCP_STORE_PATH"
```

The MCP process inherits this variable at startup. Exporting it after the
session has opened does not change that process's store. Network reset does
not reset memory. These temporary files leave the default active store and
the published evidence untouched.

Load the chosen model preset and helper as described in the main README.
The examples below assume the previous lab has been stopped. If resetting
an already-running lab instead, `sudo bash tests/reset_lab.sh` redeploys only
the network; it does not start the backend or create a new memory/session.

## Run T1

T1 builds the fabric from its initial configurations. Do not apply the
baseline script first.

```bash
bash start_environment.sh
claude
```

Send [T1_ZERO_TO_HERO.txt](prompts/T1_ZERO_TO_HERO.txt). Approve the final
Linux-client setup and ping verification when requested. Save the complete
transcript and close the agent session before running the separate validator:

```bash
python3 tests/validate_results.py T1 --run "$RUN_LABEL" --results-dir "$RESULTS_DIR"
```

## Run T2 or T3

Prepare a fresh baseline for each execution, after choosing a new run label
and empty memory file:

```bash
bash start_environment.sh
bash tests/prepare_baseline.sh
claude
```

The baseline script configures the underlay, overlay, VXLAN and the BLUE tenant,
then checks BGP and connectivity. If it reports failure, stop and resolve the
baseline problem before starting an evaluated execution.

Send either [T2_VLAN_MIGRATION.txt](prompts/T2_VLAN_MIGRATION.txt) or
[T3_OVERLAPPING_TENANTS.txt](prompts/T3_OVERLAPPING_TENANTS.txt), not both.
Approve endpoint verification when requested, save the transcript and close
the session. Run the matching validator:

```bash
python3 tests/validate_results.py T2 --run "$RUN_LABEL" --results-dir "$RESULTS_DIR"
# For a separate T3 execution:
python3 tests/validate_results.py T3 --run "$RUN_LABEL" --results-dir "$RESULTS_DIR"
```

## Run T4

Start with a fresh baseline and inject the controlled fault before opening
the agent session:

```bash
bash start_environment.sh
bash tests/prepare_baseline.sh
bash tests/inject_fault_t4.sh
claude
```

The injection changes the remote AS configured on leaf1-dc2 for its directly
connected spine1-dc2 neighbour. It does not shut down the physical link.

Send [T4_TROUBLESHOOTING.txt](prompts/T4_TROUBLESHOOTING.txt). This initial
request prohibits configuration changes. Review the read-only diagnosis
before authorising a correction. In all four normal recorded T4 executions,
the operator replied `yes apply`; dry-run/apply and a BGP check followed.
Approval to save a memory episode is a separate decision.

`validate_results.py` has no T4 command. Review T4 from the tool outputs and
complete transcript: the root cause, supporting factual details, absence of
configuration before approval, correction after approval and final BGP state.
A correct diagnosis does not imply that every supporting report statement is
correct.

## M0/M1 Operational-Memory Case

M0 is the normal DeepSeek T4 execution in which an approved lesson was stored.
Its saved episode is preserved separately in [memory_episode_m0.json](memory_episode_m0.json).
For a new M1-style execution, prepare the same fresh baseline and fault as T4.
Before opening the new agent session, use a disposable copy of that episode:

```bash
export MEMORY_MCP_STORE_PATH="$(mktemp -t 1tese-memory-m1.XXXXXX)"
cp tests/memory_episode_m0.json "$MEMORY_MCP_STORE_PATH"
claude
```

Keep the T4 prompt unchanged. In the recorded M1, the lookup occurred after
the diagnosis and `yes apply`, before the network change. The test demonstrates
storage and retrieval during the correction workflow, not an improvement in
the initial diagnosis. The published example is never loaded automatically.

After each execution, save its transcript, close the session and stop the lab
and proxy before preparing the next independent run:

```bash
bash stop_environment.sh
claudeq
```

## Post-Run Validation and Review

The live validator writes `<RESULTS_DIR>/<RUN_LABEL>/Tn_validation.json`.
It does not execute the language model or assess workflow compliance from a
transcript automatically.

| Scenario | Implemented checks |
|---|---|
| T1 | BGP/EVPN summaries, tenant dataplane readiness, client8/client9 pings in both directions and their gateway pings |
| T2 | Replacement tenant readiness and bidirectional client/gateway connectivity, plus absence of old VLAN/VNI entries on both leaves |
| T3 | Bidirectional intra-tenant pings, a gateway probe in each VRF, BLUE-to-RED and RED-to-BLUE probes, and L3VNI-to-VRF bindings on both leaves |

T3's `policy_compliance` combines these five groups: BLUE reachability,
RED reachability, gateway reachability, cross-tenant blocking and L3VNI bindings.
A blocked probe requires parsed 100% packet loss, not merely a command error.
The T2 removal parser treats unreadable JSON as an empty mapping, so its removal
flags need checking against the actual tool outputs when those are incomplete.
These checks cover the implemented cases, not every possible network policy.

Workflow compliance, approval boundaries and report accuracy require transcript
review. For new runs, optional annotations can be stored alongside the validation
JSON in `<RESULTS_DIR>/<RUN_LABEL>/analysis.json`, for example:

```json
{
  "T1": {"workflow_compliance": true},
  "T2": {"read_state_first": true, "workflow_compliance": true},
  "T3": {"workflow_compliance": true},
  "T4": {
    "root_cause_found": true,
    "read_only_kept": true,
    "clear_diagnosis": true
  }
}
```

This illustrates the accepted structure, not an annotation of the recorded
runs. Set only fields supported by the actual review. No `analysis.json` files
are supplied in the preserved evidence set.

```bash
python3 tests/generate_report.py --results-dir "$RESULTS_DIR"
```

The report aggregates available JSON fields. It does not reconstruct all
transcript decisions, correction details, report inaccuracies or provider costs.
Using the default results directory instead reads the preserved JSON checks,
not a complete per-run dataset for the whole campaign.

## Recorded Transcripts

All seventeen transcripts are under [results/full_runs_all_parameters/](results/full_runs_all_parameters/).
Their filenames and contents are retained as recorded evidence.

| Model | Evaluation case | Transcript |
|---|---|---|
| MiMo | T1 R1 | [MiMo T1R1.txt](results/full_runs_all_parameters/MiMo%20T1R1.txt) |
| MiMo | T1 R2 | [MiMo T1R2.txt](results/full_runs_all_parameters/MiMo%20T1R2.txt) |
| MiMo | T2 R1 | [MiMo T2R1.txt](results/full_runs_all_parameters/MiMo%20T2R1.txt) |
| MiMo | T2 R2 | [MiMo T2R2.txt](results/full_runs_all_parameters/MiMo%20T2R2.txt) |
| MiMo | T3 R1 | [MiMo T3R1.txt](results/full_runs_all_parameters/MiMo%20T3R1.txt) |
| MiMo | T3 R2 | [MiMo T3R2.txt](results/full_runs_all_parameters/MiMo%20T3R2.txt) |
| MiMo | T4 R1 | [MiMo T4R1.txt](results/full_runs_all_parameters/MiMo%20T4R1.txt) |
| MiMo | T4 R2 | [MiMo T4R2.txt](results/full_runs_all_parameters/MiMo%20T4R2.txt) |
| DeepSeek | T1 R1 | [DeepSeek T1R1.txt](results/full_runs_all_parameters/DeepSeek%20T1R1.txt) |
| DeepSeek | T1 R2 | [DeepSeek T1R2.txt](results/full_runs_all_parameters/DeepSeek%20T1R2.txt) |
| DeepSeek | T2 R1 | [DeepSeek T2R1.txt](results/full_runs_all_parameters/DeepSeek%20T2R1.txt) |
| DeepSeek | T2 R2 | [DeepSeek T2R2.txt](results/full_runs_all_parameters/DeepSeek%20T2R2.txt) |
| DeepSeek | T3 R1 | [DeepSeek T3R1.txt](results/full_runs_all_parameters/DeepSeek%20T3R1.txt) |
| DeepSeek | T3 R2 | [DeepSeek T3R2.txt](results/full_runs_all_parameters/DeepSeek%20T3R2.txt) |
| DeepSeek | T4 R1 / M0 | [DeepSeek T4R1_createEp.txt](results/full_runs_all_parameters/DeepSeek%20T4R1_createEp.txt) |
| DeepSeek | M1, with the stored episode | [DeepSeek T4R2_withEP.txt](results/full_runs_all_parameters/DeepSeek%20T4R2_withEP.txt) |
| DeepSeek | T4 R2, without the episode | [DeepSeek T4R3noEp.txt](results/full_runs_all_parameters/DeepSeek%20T4R3noEp.txt) |

DeepSeek's T4 filenames follow chronological execution order. `withEP` is M1;
`R3noEp` is the second normal T4 repetition, not a third normal repetition.
For that last execution the episode was removed from the active JSON store,
kept separately and restored afterwards. M1 follows the same diagnosis/approval
boundary as the four normal T4 runs.

## Saved JSONs and Costs

Seven JSON files are preserved as supporting network-state checks. They do not
provide one validation record per official execution, and their names alone do
not establish a complete model/run chronology.

| Folder | Saved records |
|---|---|
| [results/T1run1/](results/T1run1/) | `T1_validation.json` |
| [results/T2run1/](results/T2run1/) | `T1_validation.json`, `T2_validation.json` |
| [results/T2run1deep/](results/T2run1deep/) | `T2_validation.json` |
| [results/T3run1/](results/T3run1/) | `T3_validation.json` |
| [results/T4antes/](results/T4antes/) | `T1_validation.json` |
| [results/T4run1/](results/T4run1/) | `T1_validation.json` |

The T1-format records in T2/T4 folders remain in their original locations.
A T1 record does not replace T2 validation or T4 transcript review. The BGP
flag is false in `T4antes` and true in `T4run1`; these support the state checks,
not the full diagnosis and correction analysis.

[results/costs](results/costs) preserves raw token and cost output. Claude Code's
reported amounts are not the recalculated provider costs used in the thesis.
Recalculation needs the applicable input, cache and output tariffs and the
counts attributed to each model; the raw evidence is not replaced with those
estimates. The M0 JSON similarly preserves the stored lesson without expanding
its shortened text or loading it into the active memory automatically.

## Unit Tests

These tests use in-memory doubles or temporary memory files. They do not
connect to the lab or modify device state:

```bash
python3 -m pytest tests/test_core_guards.py tests/test_payload_guards.py \
  tests/test_nornir_task_state.py \
  nornir_mcp/memory_mcp/tests -q
```
