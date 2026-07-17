"""Gate-based QRAM lookup oracles.

The central unitary is

    U_m |address>|data> = |address>|data XOR m[address]>.

Classical memory is compiled into X and multi-controlled-X gates.  This is a
useful QRAM *model* for study and small experiments; it is not a scalable
bucket-brigade QRAM device.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, floor, log2, pi, sqrt
from typing import Iterable, Sequence

from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import MCXGate
from qiskit.quantum_info import Statevector


BitWord = Sequence[int]
MemoryTable = Sequence[BitWord]


@dataclass(frozen=True)
class QRAMLayout:
    """Register sizes and the validated, immutable memory table."""

    address_width: int
    word_width: int
    memory: tuple[tuple[int, ...], ...]

    @property
    def entry_count(self) -> int:
        return len(self.memory)

    @property
    def logical_qubits(self) -> int:
        return self.address_width + self.word_width

    @classmethod
    def from_memory(cls, memory: MemoryTable) -> "QRAMLayout":
        if not memory:
            raise ValueError("memory must contain at least two words")
        raw_rows = tuple(tuple(word) for word in memory)
        if len(raw_rows) < 2 or len(raw_rows) & (len(raw_rows) - 1):
            raise ValueError("memory length must be a power of two and >= 2")
        if not raw_rows[0]:
            raise ValueError("each memory word must contain at least one bit")
        word_width = len(raw_rows[0])
        if any(len(row) != word_width for row in raw_rows):
            raise ValueError("all memory words must have the same width")
        if any(bit not in (0, 1) for row in raw_rows for bit in row):
            raise ValueError("memory values must contain only 0 and 1")
        rows = tuple(tuple(int(bit) for bit in row) for row in raw_rows)
        return cls(int(log2(len(rows))), word_width, rows)


def _append_mcx(
    circuit: QuantumCircuit, controls: Iterable, target
) -> None:
    """Append X, CX, or MCX depending on the number of controls."""

    control_list = list(controls)
    if not control_list:
        circuit.x(target)
    elif len(control_list) == 1:
        circuit.cx(control_list[0], target)
    else:
        circuit.append(MCXGate(len(control_list)), [*control_list, target])


def _select_address(
    circuit: QuantumCircuit, address_register: QuantumRegister, address: int
) -> None:
    """Turn an equality test for ``address`` into an all-ones control."""

    for bit_index, qubit in enumerate(address_register):
        if ((address >> bit_index) & 1) == 0:
            circuit.x(qubit)


def build_qram_oracle(
    memory: MemoryTable, *, name: str = "QRAM"
) -> QuantumCircuit:
    """Compile a classical bit table into a reversible QRAM lookup circuit.

    Address qubit 0 and data qubit 0 are the least-significant bits.  For each
    stored 1, an address-controlled X toggles the corresponding data qubit.
    Applying the returned circuit twice gives the identity.
    """

    layout = QRAMLayout.from_memory(memory)
    address = QuantumRegister(layout.address_width, "address")
    data = QuantumRegister(layout.word_width, "data")
    oracle = QuantumCircuit(address, data, name=name)

    for address_value, word in enumerate(layout.memory):
        if not any(word):
            continue
        _select_address(oracle, address, address_value)
        for bit_index, stored_bit in enumerate(word):
            if stored_bit:
                _append_mcx(oracle, address, data[bit_index])
        _select_address(oracle, address, address_value)
    return oracle


def basis_query_circuit(memory: MemoryTable, address_value: int) -> QuantumCircuit:
    """Prepare one address and load its word into the data register."""

    layout = QRAMLayout.from_memory(memory)
    if not 0 <= address_value < layout.entry_count:
        raise ValueError(f"address must be in [0, {layout.entry_count - 1}]")
    circuit = QuantumCircuit(layout.logical_qubits, name="basis_query")
    for bit_index in range(layout.address_width):
        if (address_value >> bit_index) & 1:
            circuit.x(bit_index)
    circuit.compose(build_qram_oracle(memory), inplace=True)
    return circuit


def uniform_query_circuit(memory: MemoryTable) -> QuantumCircuit:
    """Query every address coherently, entangling addresses and stored words."""

    layout = QRAMLayout.from_memory(memory)
    circuit = QuantumCircuit(layout.logical_qubits, name="uniform_query")
    circuit.h(range(layout.address_width))
    circuit.compose(build_qram_oracle(memory), inplace=True)
    return circuit


def decoded_probabilities(
    circuit: QuantumCircuit, layout: QRAMLayout, *, cutoff: float = 1e-12
) -> dict[tuple[int, int], float]:
    """Return probabilities keyed by conventional ``(address, word)`` ints.

    Decoding integer state indices avoids confusion over Qiskit's displayed
    bitstring order.  This function expects address qubits first and data
    qubits second, as produced by the builders in this module.
    """

    if circuit.num_clbits:
        raise ValueError("decoded_probabilities expects a circuit without measurements")
    if circuit.num_qubits != layout.logical_qubits:
        raise ValueError("circuit qubit count does not match layout")

    probabilities = Statevector.from_instruction(circuit).probabilities()
    address_mask = (1 << layout.address_width) - 1
    decoded: dict[tuple[int, int], float] = {}
    for state_index, probability in enumerate(probabilities):
        value = float(probability)
        if value <= cutoff:
            continue
        address_value = state_index & address_mask
        word_value = (state_index >> layout.address_width) & (
            (1 << layout.word_width) - 1
        )
        decoded[(address_value, word_value)] = value
    return decoded


def _mark_word(
    circuit: QuantumCircuit,
    data_qubits: Sequence,
    target_word: int,
) -> None:
    """Flip phase exactly when the data register equals ``target_word``."""

    for bit_index, qubit in enumerate(data_qubits):
        if ((target_word >> bit_index) & 1) == 0:
            circuit.x(qubit)
    circuit.h(data_qubits[-1])
    _append_mcx(circuit, data_qubits[:-1], data_qubits[-1])
    circuit.h(data_qubits[-1])
    for bit_index, qubit in enumerate(data_qubits):
        if ((target_word >> bit_index) & 1) == 0:
            circuit.x(qubit)


def _diffuse(circuit: QuantumCircuit, address_qubits: Sequence) -> None:
    """Apply inversion about the mean to the address register."""

    circuit.h(address_qubits)
    circuit.x(address_qubits)
    circuit.h(address_qubits[-1])
    _append_mcx(circuit, address_qubits[:-1], address_qubits[-1])
    circuit.h(address_qubits[-1])
    circuit.x(address_qubits)
    circuit.h(address_qubits)


def grover_reverse_lookup_circuit(
    memory: MemoryTable,
    target_word: int,
    *,
    iterations: int | None = None,
) -> QuantumCircuit:
    """Find addresses whose QRAM value equals ``target_word`` with Grover search.

    The QRAM is loaded, the requested word is phase-marked, and the QRAM is
    uncomputed before diffusion.  If ``iterations`` is omitted, the function
    uses the known number of matches in this educational classical table.
    """

    layout = QRAMLayout.from_memory(memory)
    if not 0 <= target_word < (1 << layout.word_width):
        raise ValueError(f"target_word must fit in {layout.word_width} bits")
    matches = sum(
        1
        for word in layout.memory
        if sum(bit << bit_index for bit_index, bit in enumerate(word)) == target_word
    )
    if matches == 0:
        raise ValueError("target_word is not present in memory")
    if iterations is None:
        theta = asin(sqrt(matches / layout.entry_count))
        iterations = max(1, floor(pi / (4 * theta)))
    if iterations < 1:
        raise ValueError("iterations must be >= 1")

    circuit = QuantumCircuit(layout.logical_qubits, name="reverse_lookup")
    addresses = list(range(layout.address_width))
    data = list(range(layout.address_width, layout.logical_qubits))
    qram = build_qram_oracle(memory)
    circuit.h(addresses)
    for _ in range(iterations):
        circuit.compose(qram, inplace=True)
        _mark_word(circuit, data, target_word)
        circuit.compose(qram.inverse(), inplace=True)
        _diffuse(circuit, addresses)
    return circuit
