# QRAM in Qiskit: 4-bit lesson to an 8-qubit search router

This project implements a small, explicit **gate-based QRAM lookup oracle**:

```text
U_m |address>|data> = |address>|data XOR m[address]>
```

It starts with four one-bit cells and expands to 16 four-bit cells used as a
search-index routing table. The larger example also performs a Grover reverse
lookup: given a shard ID, it amplifies the address of the corresponding query
bucket.

> Important: this is an educational circuit model in which a classical table
> is compiled into gates. It does not claim to implement scalable physical
> QRAM hardware, and its gate cost grows with the number of stored 1 bits.

## What is included

- `src/qram_learning/qram.py` - reusable QRAM compiler, query builders,
  statevector decoder, and Grover reverse lookup.
- `examples/01_four_bit_qram.py` - four stored bits, two address qubits, one
  data qubit.
- `examples/02_search_router_qram.py` - 16 x 4-bit routing table using eight
  logical qubits.
- `tests/test_qram.py` - lookup, coherence, reversibility, validation, and
  Grover tests.
- `output/pdf/QRAM_Python_Explanation.pdf` - illustrated, file-by-file explanation.

## Install and run

Python 3.10 or newer is required. From this project directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

python examples/01_four_bit_qram.py
python examples/02_search_router_qram.py
pytest -q
```

The examples use Qiskit's exact `Statevector`, so no cloud account, API token,
or optional Aer package is needed.

## Four stored bits

The table is:

| Address | Stored bit |
|---:|---:|
| `00` | `1` |
| `01` | `0` |
| `10` | `1` |
| `11` | `1` |

Two address qubits can represent four addresses. One data qubit receives the
selected bit. Preparing the addresses in superposition produces

```text
1/2 (|00>|1> + |01>|0> + |10>|1> + |11>|1>).
```

## Larger use case

The larger circuit maps 16 four-bit query-hash buckets to 16 search shard IDs.
It needs four address qubits and four data qubits, for eight logical qubits.
The script demonstrates:

1. a forward lookup, `bucket 1011 -> shard 1101`;
2. a coherent load/unload cycle;
3. Grover amplitude amplification to reverse-find bucket `1011` from shard
   `1101`;
4. a decomposition to generic one-qubit and CX gates for a rough resource
   snapshot.

The routing table is deliberately a permutation so every shard has one bucket.
Real routing metadata can replace `SHARD_IDS`, provided the table stays a power
of two in length and every word has the same width.

## Limits and hardware notes

- The circuit is read-only at run time; changing the table recompiles gates.
- The loader uses one multi-controlled X for each stored `1`.
- Multi-controlled gates decompose into many native operations and are
  noise-sensitive on current hardware.
- A basis query has no speed advantage over a classical array lookup. The
  educational value comes from coherent loading, uncomputation, and composing
  the oracle with algorithms such as Grover search.
- Large, fault-tolerant QRAM remains a hardware-architecture and error-correction
  challenge. This project stays intentionally small and auditable.

## Qiskit references

- [QuantumCircuit API](https://quantum.cloud.ibm.com/docs/api/qiskit/qiskit.circuit.QuantumCircuit)
- [Statevector API](https://quantum.cloud.ibm.com/docs/api/qiskit/qiskit.quantum_info.Statevector)
- [StatevectorSampler API](https://quantum.cloud.ibm.com/docs/api/qiskit/qiskit.primitives.StatevectorSampler)
