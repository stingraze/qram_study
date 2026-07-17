import math

import pytest

from qram_learning import (
    QRAMLayout,
    basis_query_circuit,
    build_qram_oracle,
    decoded_probabilities,
    grover_reverse_lookup_circuit,
    uniform_query_circuit,
)


def bits(value: int, width: int) -> list[int]:
    return [(value >> index) & 1 for index in range(width)]


def test_four_bit_memory_basis_queries() -> None:
    memory = [[1], [0], [1], [1]]
    layout = QRAMLayout.from_memory(memory)
    for address, expected in enumerate([1, 0, 1, 1]):
        probabilities = decoded_probabilities(
            basis_query_circuit(memory, address), layout
        )
        assert probabilities == {(address, expected): pytest.approx(1.0)}


def test_uniform_query_entangles_every_address_with_its_value() -> None:
    memory = [[1], [0], [1], [1]]
    layout = QRAMLayout.from_memory(memory)
    probabilities = decoded_probabilities(uniform_query_circuit(memory), layout)
    assert probabilities == {
        (0, 1): pytest.approx(0.25),
        (1, 0): pytest.approx(0.25),
        (2, 1): pytest.approx(0.25),
        (3, 1): pytest.approx(0.25),
    }


def test_qram_is_self_inverse() -> None:
    memory = [bits(value, 2) for value in [0, 3, 1, 2]]
    layout = QRAMLayout.from_memory(memory)
    circuit = basis_query_circuit(memory, 3)
    circuit.compose(build_qram_oracle(memory), inplace=True)
    assert decoded_probabilities(circuit, layout) == {(3, 0): pytest.approx(1.0)}


def test_sixteen_by_four_lookup() -> None:
    values = [3, 12, 5, 1, 9, 6, 10, 4, 2, 15, 7, 13, 0, 8, 11, 14]
    memory = [bits(value, 4) for value in values]
    layout = QRAMLayout.from_memory(memory)
    for address, expected in enumerate(values):
        probabilities = decoded_probabilities(
            basis_query_circuit(memory, address), layout
        )
        assert probabilities == {(address, expected): pytest.approx(1.0)}


def test_grover_reverse_lookup_finds_unique_shard() -> None:
    values = [3, 12, 5, 1, 9, 6, 10, 4, 2, 15, 7, 13, 0, 8, 11, 14]
    memory = [bits(value, 4) for value in values]
    layout = QRAMLayout.from_memory(memory)
    probabilities = decoded_probabilities(
        grover_reverse_lookup_circuit(memory, target_word=13), layout
    )
    target_probability = sum(
        probability
        for (address, data), probability in probabilities.items()
        if address == 11 and data == 0
    )
    assert target_probability > 0.9
    assert math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-9)


@pytest.mark.parametrize(
    "memory",
    [[], [[0]], [[0], [1], [0]], [[0], [1, 0]], [[0], [2]]],
)
def test_invalid_memory_is_rejected(memory) -> None:
    with pytest.raises(ValueError):
        QRAMLayout.from_memory(memory)

