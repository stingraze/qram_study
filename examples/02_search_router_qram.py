"""Eight-qubit QRAM use case: query-bucket to search-shard routing."""

from qiskit import transpile

from qram_learning import (
    QRAMLayout,
    basis_query_circuit,
    build_qram_oracle,
    decoded_probabilities,
    grover_reverse_lookup_circuit,
)


# 16 query-hash buckets, each mapped to a 4-bit search shard ID.
# Bit arrays are least-significant bit first, matching Qiskit qubit indices.
SHARD_IDS = [3, 12, 5, 1, 9, 6, 10, 4, 2, 15, 7, 13, 0, 8, 11, 14]
MEMORY = [[(value >> bit) & 1 for bit in range(4)] for value in SHARD_IDS]


def main() -> None:
    layout = QRAMLayout.from_memory(MEMORY)
    bucket = 11
    query = basis_query_circuit(MEMORY, bucket)
    result = decoded_probabilities(query, layout)
    ((found_bucket, shard_id), probability), = result.items()

    print("Search-index routing QRAM")
    print(
        f"bucket={found_bucket:04b} -> shard={shard_id:04b} "
        f"({shard_id}), p={probability:.3f}"
    )

    target_shard = 13
    reverse = grover_reverse_lookup_circuit(MEMORY, target_shard)
    reverse_result = decoded_probabilities(reverse, layout)
    address_probabilities: dict[int, float] = {}
    for (address, data), state_probability in reverse_result.items():
        assert data == 0  # QRAM was uncomputed before every diffusion step.
        address_probabilities[address] = address_probabilities.get(address, 0.0) + state_probability
    ranked = sorted(address_probabilities.items(), key=lambda item: item[1], reverse=True)
    print(f"\nGrover reverse lookup for shard {target_shard:04b}:")
    for address, state_probability in ranked[:5]:
        print(f"  bucket={address:04b}, p={state_probability:.4f}")

    oracle = build_qram_oracle(MEMORY)
    compiled = transpile(oracle, basis_gates=["u", "cx"], optimization_level=1)
    print("\nResource snapshot (simulator-independent decomposition):")
    print(f"  logical qubits: {layout.logical_qubits}")
    print(f"  oracle depth before decomposition: {oracle.depth()}")
    print(f"  decomposed depth: {compiled.depth()}")
    print(f"  decomposed operations: {dict(compiled.count_ops())}")


if __name__ == "__main__":
    main()

