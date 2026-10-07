#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
DEFAULT_RESULTS_DIR = TESTS_DIR / "results"


def load_results(run_dir: Path) -> dict:
    results = {"T1": {}, "T2": {}, "T3": {}, "T4": {}}

    for test in ["T1", "T2", "T3"]:
        validation_file = run_dir / f"{test}_validation.json"
        if validation_file.exists():
            results[test].update(json.loads(validation_file.read_text(encoding="utf-8")))

    analysis_file = run_dir / "analysis.json"
    if analysis_file.exists():
        analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
        for test in ["T1", "T2", "T3", "T4"]:
            if test in analysis:
                results[test].update(analysis[test])

    return results


def format_value(value) -> str:
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a markdown evaluation report")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Directory with run results")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"No results directory found at {results_dir}.")
        return

    run_dirs = [item for item in results_dir.iterdir() if item.is_dir()]
    if not run_dirs:
        print(f"No run results found under {results_dir}.")
        return

    run_names = [item.name for item in run_dirs]
    all_data = {run.name: load_results(run) for run in run_dirs}

    print("# Evaluation Results Report\n")
    print("LLM execution was manual/supervised. Network-state validation and report aggregation were automated.\n")

    header = "| Scenario | Metric | " + " | ".join(run_names) + " |"
    separator = "|---|---|" + "|".join(["---"] * len(run_names)) + "|"
    print(header)
    print(separator)

    metrics_map = {
        "T1": [
            ("BGP Underlay Established", "bgp_underlay_established"),
            ("EVPN Established", "evpn_established"),
            ("Dataplane Ready", "dataplane_ready"),
            ("Client8 -> Client9", "client8_to_client9"),
            ("Client9 -> Client8", "client9_to_client8"),
            ("Client8 -> Gateway", "client8_to_gateway"),
            ("Client9 -> Gateway", "client9_to_gateway"),
            ("Workflow Compliance", "workflow_compliance"),
        ],
        "T2": [
            ("VLAN 20/VNI 10020 Ready", "vlan20_ready"),
            ("Client8 -> Client9", "client8_to_client9"),
            ("Client9 -> Client8", "client9_to_client8"),
            ("Client8 -> Gateway", "client8_to_gateway"),
            ("Client9 -> Gateway", "client9_to_gateway"),
            ("Old VNI Removed", "old_vni_removed"),
            ("Old VLAN Removed", "old_vlan_removed"),
            ("Migration Complete", "migration_complete"),
            ("Read State First", "read_state_first"),
            ("Workflow Compliance", "workflow_compliance"),
        ],
        "T3": [
            ("BLUE Intra-Tenant (c8<->c9)", "blue_intra_tenant_ok"),
            ("RED Intra-Tenant (c10<->c11)", "red_intra_tenant_ok"),
            ("Overlapping Gateway OK", "overlapping_gateway_ok"),
            ("Cross-Tenant Blocked", "cross_tenant_blocked"),
            ("Policy Compliance", "policy_compliance"),
            ("Workflow Compliance", "workflow_compliance"),
        ],
        "T4": [
            ("Root Cause Found", "root_cause_found"),
            ("Read Only Kept", "read_only_kept"),
            ("Clear Diagnosis", "clear_diagnosis"),
        ],
    }

    for scenario, metrics in metrics_map.items():
        for index, (display_name, key) in enumerate(metrics):
            row = [f"**{scenario}**" if index == 0 else "", display_name]
            for run_name in run_names:
                value = all_data[run_name].get(scenario, {}).get(key, "N/A")
                row.append(format_value(value))
            print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
