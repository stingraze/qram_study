# QRAM for IBM Quantum (`qram_ibm.py`)

# Making a new repository of QRAM, using Perplexity Pro. (C)Tsubasa Kato 2026/11/21

Unary-iteration (QROM-style select-tree) QRAM circuit generator, classical reversible verifier, step-by-step gate debugger, and runner for local GPU/MPS simulation and IBM Quantum hardware via `qiskit-ibm-runtime` (`SamplerV2`).

## Circuit Layouts

Each layout uses `n` address qubits, `n` tree-ancilla qubits, and `d` data qubits (`2n + d` total). Empty subtrees are automatically pruned.

| Preset (`--size`) | Address (`n`) | Ancilla (`n`) | Data (`d`) | Capacity | Total Qubits | Typical Gates (Dense) |
|---|---:|---:|---:|---|---:|---:|
| `tiny` | 3 | 3 | 4 | 8 words x 4 bits | 10 | ~46 |
| `30` | 8 | 8 | 14 | 256 words x 14 bits | 30 | ~2,774 |
| `156` | 10 | 10 | 136 | 1,024 words x 136 bits | 156 | ~73,735 |

## Requirements

- **Classical verification & step tracing (`--where verify`):** Python 3.10+ and `numpy` only.
- **Local simulation (`--where aer-gpu` / `aer-mps`):** `qiskit` and `qiskit-aer` (or `qiskit-aer-gpu` for CUDA / cuStateVec).
- **IBM Quantum hardware (`--where ibm`):** `qiskit` and `qiskit-ibm-runtime`.

```bash
pip install numpy qiskit qiskit-aer-gpu qiskit-ibm-runtime
```

## Quick Start

### 1. Classical Verification & Step Debugger

```bash
# Readable 10-qubit trace with full register snapshots exported to JSON
python qram_ibm.py --size tiny --trace --trace-addr 5 --snapshots --json out.json

# 30-qubit arbitrary data verification
python qram_ibm.py --size 30 --mode arbitrary --where verify

# 156-qubit paged big-data verification (200 kB random payload)
python qram_ibm.py --size 156 --mode big --where verify --trace --max-steps 10 --json big156.json
```

### 2. Local Simulation (4 GB to 20 GB VRAM)

`--vram` sets the GPU memory budget in GB. The script computes the maximum single-precision statevector qubit count with 2x headroom (~28q at 4 GB, ~30q at 8–16 GB, ~31q at 20 GB) and automatically falls back to `matrix_product_state` (MPS) when the circuit exceeds the budget.

```bash
# 30-qubit statevector on GPU (requires ~8 GB+ VRAM for single precision)
python qram_ibm.py --size 30 --mode arbitrary --where aer-gpu --vram 8

# 156-qubit basis-state query via MPS
python qram_ibm.py --size 156 --mode big --where aer-mps --shots 256
```

### 3. IBM Quantum Hardware

Authentication uses `channel="ibm_quantum_platform"` with an IBM Cloud API key and instance CRN. Environment variables (`QISKIT_IBM_TOKEN`, `QISKIT_IBM_INSTANCE`) take precedence over a saved account.

```bash
# One-time: save credentials to ~/.qiskit/qiskit-ibm.json
export QISKIT_IBM_TOKEN="<your-api-key>"
export QISKIT_IBM_INSTANCE="<your-instance-crn>"
python qram_ibm.py --save-account

# List operational backends
python qram_ibm.py --list-backends

# Run on least-busy qualifying backend (or specify --backend <name>)
python qram_ibm.py --size 30 --mode arbitrary --where ibm --shots 4000 --json ibm30.json
python qram_ibm.py --size 156 --mode big --where ibm --backend <backend_name> --json ibm156.json
```

> **Hardware note:** A dense 156-qubit QRAM circuit contains ~74k logical gates before transpilation, which will be dominated by noise on current hardware. Validate with `--size 30` or sparse data first, and inspect the reported transpiled depth and 2-qubit gate count.

## How It Works

1. **Select (`select_1` / `select_0`):** Traverses the address bits MSB-first using `cx`, `ccx`, and `x` gates so `anc[k] = 1` iff the address matches the current length-(k+1) prefix.
2. **Store (`store`):** At the leaf level, `cx(anc[n-1], data[j])` copies each `1` bit of the addressed word into the data register.
3. **Uncompute (`uncompute`):** Clears every tree ancilla back to `|0>` in reverse order (`ancilla_clean=True`).
4. **Big Data (`--mode big`):** Packs an arbitrary byte payload (`--blob-bytes`, default 200,000 bytes) into `d`-bit words and splits them into pages of `2^n` words. Page selection is handled classically; each page compiles to one QRAM circuit.

## CLI Options

| Flag | Default | Description |
|---|---|---|
| `--size` | `30` | Circuit preset: `tiny`, `30`, or `156` |
| `--mode` | `arbitrary` | `arbitrary` (single page of random words) or `big` (paged byte blob) |
| `--where` | `verify` | `verify`, `aer-gpu`, `aer-mps`, or `ibm` |
| `--shots` | `2048` | Measurement shots for Aer / IBM |
| `--backend` | `None` | Specific IBM backend name (defaults to least busy) |
| `--vram` | `8` | GPU VRAM budget in GB for statevector auto-sizing |
| `--blob-bytes` | `200000` | Payload size in bytes for `--mode big` |
| `--trace` | off | Print step-by-step gate trace for one query |
| `--trace-addr` | `5` | Target address (or global word index in `big` mode) to trace |
| `--max-steps` | `60` | Maximum fired steps printed to stdout |
| `--all-steps` | off | Include gates that did not change any qubit in stdout trace |
| `--snapshots` | off | Include full `addr`/`anc`/`data` register strings after every step in JSON |
| `--mem-limit` | `None` | Cap the number of memory rows written to JSON |
| `--json` | `None` | Output path for fine-grained JSON results |
| `--save-account` | off | Save IBM credentials from environment variables |
| `--list-backends` | off | List operational IBM Quantum backends |

## JSON Output Schema

When `--json` is passed, the output contains:

- `config`: Layout parameters (`n_address`, `n_ancilla`, `data_bits`, `qubits`, `capacity_words`), `mode`, `where`, and timestamp.
- `memory`: Cell count, nonzero cell count, total stored `1` bits, and per-address rows (`addr`, `addr_bin`, `value_hex`, `value_bin`, `popcount`).
- `verification` *(arbitrary mode)*: `addresses_checked` and `mismatches`.
- `big_data` *(big mode)*: Payload size, `sha256`, word/page counts, 20 cross-page read checks, and traced page/index.
- `gates`: Total gate count, Toffoli/CNOT counts, and breakdowns by type, tree level, and phase (`select_1`, `select_0`, `store`, `uncompute`).
- `trace` *(when `--trace` is set)*: Address, expected vs. observed value, `ancilla_clean`, final registers, and per-step records (`step`, `gate`, `qubits`, `level`, `phase`, `why`, `changed`, `fired`, plus `state` if `--snapshots` is enabled).
- `circuit` & `execution` *(when `--where` is not `verify`)*: Pre-transpile circuit stats, IBM backend/job/transpilation metadata, shot counts, `top_outcome`, `correct_shots`, `fidelity_estimate`, and `top20` outcomes.
