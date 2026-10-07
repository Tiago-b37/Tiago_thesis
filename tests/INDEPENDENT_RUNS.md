# Independent Evaluation Runs

T1, T2, T3, and T4 are separate experiments. Do not execute the full sequence
against the same persistent lab state:

- T2 removes VLAN 10/VNI 10010.
- T3 requires VLAN 10/VNI 10010 in its prepared baseline.
- T4 requires the healthy baseline plus exactly one controlled eBGP fault.

Start each normal execution with empty operational memory and use a unique
`RUN_LABEL`. M1 is the separate memory-reuse condition. Network reset does not
reset memory; `tests/README.md` documents independent memory files.

## T1 - Clean Zero-to-Hero

Start from a clean Containerlab deployment. Do not apply `prepare_baseline.sh`,
because constructing that baseline is the purpose of T1.

```bash
cd /media/sf_Codigo_tese/1tese
RUN_LABEL=mimo_v2_5_t1_run1
./start_environment.sh
```

Run only `T1_ZERO_TO_HERO`, approve the final endpoint verification when asked,
and then validate and stop the lab:

```bash
python3 tests/validate_results.py T1 --run "$RUN_LABEL"
./stop_environment.sh
```

## T2 or T3 - Fresh Prepared Baseline

For each individual T2 or T3 run, start a fresh lab and apply the deterministic
baseline:

```bash
./start_environment.sh
bash tests/prepare_baseline.sh
```

Run only the selected prompt and its validator:

```bash
python3 tests/validate_results.py T2 --run "$RUN_LABEL"
# or, in a different fresh experiment:
python3 tests/validate_results.py T3 --run "$RUN_LABEL"
./stop_environment.sh
```

Never run T3 immediately after T2 without restoring the baseline.

## T4 - Fresh Baseline and Controlled Fault

```bash
./start_environment.sh
bash tests/prepare_baseline.sh
bash tests/inject_fault_t4.sh
```

Run `T4_TROUBLESHOOTING` as a read-only investigation. In the recorded campaign,
the operator replied `yes apply` after the diagnosis to authorise correction;
dry-run/apply and BGP checks followed. Any memory write requires separate
approval. Review the complete transcript, including both diagnosis and
authorised correction, and save it before stopping the environment.
