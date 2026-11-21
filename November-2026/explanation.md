# Technical Explanation: Unary-Iteration QRAM (`qram_ibm.py`)

This document explains the circuit architecture, gate-generation algorithm, data paging model, verification logic, and simulation/hardware tradeoffs implemented in `qram_ibm.py`.

## 1. Why Unary-Iteration (QROM) Instead of Bucket-Brigade QRAM

A bucket-brigade QRAM routes quantum addresses through a binary tree of quantum switches, requiring `O(2^n)` routing qubits. Even for `n = 8` (256 words), a bucket-brigade tree exceeds 156 qubits.

`qram_ibm.py` instead uses a **unary-iteration (QROM select-tree)** architecture:

- **Qubit count:** `2n + d` (`n` address qubits, `n` tree-ancilla qubits, `d` data qubits).
- **Tradeoff:** Qubit count scales linearly with address width `n`, while gate count scales with the number of nonzero stored words (`O(M * d)` for `M` nonzero entries).

| Preset | `n` (Address) | `n` (Ancilla) | `d` (Data) | Total Qubits | Capacity |
|---|---:|---:|---:|---:|---|
| `tiny` | 3 | 3 | 4 | 10 | 8 words x 4 bits |
| `30` | 8 | 8 | 14 | 30 | 256 words x 14 bits |
| `156` | 10 | 10 | 136 | 156 | 1,024 words x 136 bits |

## 2. Register Layout and Bit Ordering

The circuit allocates three contiguous registers:

1. `addr[0 .. n-1]` — Address register, stored **MSB-first** (`addr[0]` is the most significant bit).
2. `anc[0 .. n-1]` — One reusable ancilla per level of the binary address tree.
3. `data[0 .. d-1]` — Output data register, initialized to `|0...0>`, where the addressed word is XORed in.

When measured in Qiskit (`ca` for `addr`, `cd` for `data`), Qiskit formats bitstrings with the last-added classical register on the left (`cd ca`). The `decode(bitstr, n, d)` helper splits the concatenated bitstring into `data` (first `d` chars) and `addr` (remaining `n` chars).

## 3. How the Select-Tree Algorithm Works (`build_gates`)

`build_gates(words, n, d)` performs a depth-first traversal of the binary address space `[0, 2^n)`.

### Sparse Subtree Pruning
Before descending into any interval `[lo, lo + span)`, the builder checks `has(lo, lo + span)` using binary search (`bisect_left`) over sorted nonzero keys. If a subtree contains only zeros, no gates are emitted for it.

### Four Phases per Tree Node
At tree level `L` with address qubit `a = addr[L]`, ancilla `anc = anc[L]`, and parent control `ctrl` (`None` at the root `L = 0`):

1. **`select_1` (right child, bit = 1):**
   - Root: `cx(a, anc)` sets `anc = a`.
   - Deeper levels: `ccx(ctrl, a, anc)` sets `anc = ctrl AND a`.
   - Recurse into the upper half `[lo + half, lo + span)` (or emit leaf CNOTs if `L == n - 1`).
2. **`select_0` (left child, bit = 0):**
   - Root: `x(anc)` flips `anc` to `NOT a`.
   - Deeper levels: `cx(ctrl, anc)` XORs `ctrl` into `anc`, turning `ctrl AND a` into `ctrl AND (NOT a)`.
   - Recurse into the lower half `[lo, lo + half)` (or emit leaf CNOTs if `L == n - 1`).
3. **`store` (leaf level `L == n - 1`):**
   - For each bit `j` where the stored word has a `1`, emit `cx(anc[n-1], data[j])`.
   - Because `anc[n-1] == 1` only for the unique leaf matching `addr`, only that cell's bits are XORed into `data`.
4. **`uncompute` (cleanup):**
   - Undo `select_0` (`x(anc)` or `cx(ctrl, anc)`).
   - Undo `select_1` (`cx(a, anc)` or `ccx(ctrl, a, anc)`).
   - Every ancilla returns strictly to `|0>`, preventing entanglement between `anc` and `addr`/`data`.

## 4. Step-by-Step Walkthrough (`tiny`, Address `5 = 101`)

For `n = 3, d = 4` with input `addr = 101`, `anc = 000`, `data = 0000`:

1. **Level 0 (`select_1`):** `cx(addr[0], anc[0])` fires because `addr[0] = 1` -> `anc = 100` (prefix `'1'`).
2. **Level 1 (`select_1`):** `ccx(anc[0], addr[1], anc[1])` does **not** fire because `addr[1] = 0`. The `'11'` subtree is traversed with `anc[1] = 0`, so none of its gates change any qubit.
3. **Level 1 (`select_0`):** `cx(anc[0], anc[1])` fires -> `anc = 110` (prefix `'10'`).
4. **Level 2 (`select_1`):** `ccx(anc[1], addr[2], anc[2])` fires because `anc[1] = 1` and `addr[2] = 1` -> `anc = 111` (prefix `'101'`, cell 5).
5. **Leaf (`store`):** `cx(anc[2], data[j])` fires for every `1` bit of cell 5 (e.g., `1111`), writing the word into `data`.
6. **Uncompute:** `anc[2]`, `anc[1]`, and `anc[0]` are cleared in reverse order back to `000`, leaving `addr = 101, anc = 000, data = 1111`.

Because the circuit is linear over quantum states, preparing `addr` in a superposition (`superpose=True` via Hadamard gates) applies the same mapping simultaneously to all basis states:

`sum_i alpha_i |i>_addr |0>_anc |0>_data  ->  sum_i alpha_i |i>_addr |0>_anc |D[i]>_data`

## 5. Paged Big-Data Model (`PagedQRAM`)

A single QRAM circuit holds `2^n` words of `d` bits (e.g., `1024 * 136 bits = 17.4 kB` per page for the 156-qubit layout). To handle larger payloads (`--mode big`, default 200 kB):

1. `big_data_pages` converts the raw byte stream to bits, zero-pads to a multiple of `d`, and packs it into `d`-bit integers.
2. Words are partitioned into pages of `2^n` words (`divmod(global_index, 2^n)` yields `(page, local_addr)`).
3. **Classical outer loop, quantum inner lookup:** Page selection is classical, and each page is compiled on demand into its own QRAM gate list and cached in `PagedQRAM.built`.

## 6. Classical Verifier, Step Debugger, and JSON Output

- **Exact classical verifier (`classical_query`):** Because `x`, `cx`, and `ccx` are classical reversible (Toffoli) gates, any basis-state query can be simulated in `O(gates)` bit operations regardless of qubit count. This verifies all `2^n` addresses and asserts `ancilla_clean=True` without needing a statevector.
- **Step debugger (`trace_query`):** Records every gate's index, type, named qubits, tree level, phase, human-readable explanation (`why`), changed qubits, and whether it fired. Passing `--snapshots` also saves the full `addr`/`anc`/`data` bitstrings after each step.
- **JSON export (`--json`):** Writes `config`, `memory`, `verification` or `big_data`, `gates` (counts by type, level, and phase), `trace`, `circuit`, and `execution` (including `fidelity_estimate` and `top20` outcomes).

## 7. Local VRAM Sizing and IBM Quantum Execution

- **GPU statevector (`--where aer-gpu`):** `max_sv_qubits(vram_gb, single=True)` computes `floor(log2(vram_gb * 2^30 / 8 / 2))` (8 bytes per `complex64` amplitude with 2x headroom).
  - 4 GB VRAM -> up to 28 qubits
  - 8–16 GB VRAM -> up to 29–30 qubits
  - 20 GB VRAM -> up to 31 qubits
  - If the circuit exceeds the budget, the script automatically falls back to Aer's `matrix_product_state` (MPS) simulator.
- **156-qubit simulation (`--where aer-mps`):** For a single basis-state address, the state stays a product state (bond dimension 1), so MPS executes cleanly even at 156 qubits.
- **IBM Quantum (`--where ibm`):** Connects via `QiskitRuntimeService(channel="ibm_quantum_platform")`, transpiles at `optimization_level=3`, logs transpiled depth and 2-qubit gate count (`cz`/`ecr`/`cx`), and submits via `SamplerV2`. Because a dense 156-qubit QROM has ~74k logical gates (mostly leaf CNOTs and Toffolis), noise will dominate on current hardware unless the stored page is sparse.
