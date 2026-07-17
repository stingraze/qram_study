"""Smallest useful example: four one-bit memory cells."""

from qram_learning import (
    QRAMLayout,
    basis_query_circuit,
    decoded_probabilities,
    uniform_query_circuit,
)


# Four classical bits addressed by two qubits: m[0..3] = 1, 0, 1, 1.
MEMORY = [[1], [0], [1], [1]]


def main() -> None:
    layout = QRAMLayout.from_memory(MEMORY)
    print("Four-bit educational QRAM")
    print("Address table:")
    for address, word in enumerate(MEMORY):
        print(f"  {address:02b} -> {word[0]}")

    address = 2
    query = basis_query_circuit(MEMORY, address)
    result = decoded_probabilities(query, layout)
    print(f"\nBasis query for address {address:02b}:")
    for (found_address, value), probability in result.items():
        print(f"  address={found_address:02b}, data={value:b}, p={probability:.3f}")

    coherent_query = uniform_query_circuit(MEMORY)
    coherent_result = decoded_probabilities(coherent_query, layout)
    print("\nUniform superposition query:")
    for (found_address, value), probability in sorted(coherent_result.items()):
        print(f"  |address={found_address:02b}, data={value:b}>: {probability:.3f}")

    print("\nCircuit:")
    print(query.draw(output="text"))


if __name__ == "__main__":
    main()

