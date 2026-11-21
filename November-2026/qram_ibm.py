"""
qram_ibm.py -- Unary-iteration QRAM (QROM-style select tree) for IBM Quantum, with step debugger + JSON.
 Layout: n address + n tree-ancilla + d data qubits
   tiny: n=3,d=4 (10q, for reading traces) | 30: n=8,d=14 | 156: n=10,d=136
"""
import argparse, math, hashlib, os, bisect, json, time
import numpy as np

SPECS = {"tiny": dict(n=3, d=4), "30": dict(n=8, d=14), "156": dict(n=10, d=136)}

class Layout:
    def __init__(s, n, d):
        s.n, s.d = n, d
        s.addr = list(range(n)); s.anc = list(range(n, 2 * n)); s.data = list(range(2 * n, 2 * n + d))
        s.N = 2 * n + d; s.meta = []
    def name(s, q):
        return f"addr[{q}]" if q < s.n else (f"anc[{q-s.n}]" if q < 2*s.n else f"data[{q-2*s.n}]")

def build_gates(words, n, d):
    """Returns (Layout, gates); L.meta[i] = dict describing gate i (level, prefix, phase)."""
    L, g = Layout(n, d), []
    keys = sorted(k for k, v in words.items() if v)
    def has(lo, hi):
        i = bisect.bisect_left(keys, lo); return i < len(keys) and keys[i] < hi
    def E(t, **m): g.append(t); L.meta.append(m)
    def pfx(level, lo): return format(lo >> (n - level), f"0{level}b") if level else ""
    def leaf(addr, c, level):
        v = words.get(addr, 0)
        for j in range(d):
            if (v >> (d - 1 - j)) & 1:
                E(("cx", c, L.data[j]), level=level, phase="store", cell=addr,
                  why=f"cell {addr} (bin {addr:0{n}b}) has bit {j}=1 -> copy into data[{j}] if this cell selected")
    def rec(level, lo, ctrl):
        span = 1 << (n - level)
        if not has(lo, lo + span): return
        a, anc = L.addr[level], L.anc[level]; half = span >> 1; p = pfx(level, lo)
        if ctrl is None: E(("cx", a, anc), level=level, phase="select_1", why=f"anc[{level}] = addr[{level}]  (subtree prefix '{p}1')")
        else:            E(("ccx", ctrl, a, anc), level=level, phase="select_1", why=f"anc[{level}] = ctrl AND addr[{level}]  (prefix '{p}1')")
        if has(lo + half, lo + span):
            leaf(lo + half, anc, level) if level == n - 1 else rec(level + 1, lo + half, anc)
        if ctrl is None: E(("x", anc), level=level, phase="select_0", why=f"anc[{level}] = NOT addr[{level}]  (prefix '{p}0')")
        else:            E(("cx", ctrl, anc), level=level, phase="select_0", why=f"anc[{level}] ^= ctrl -> ctrl AND NOT addr[{level}]  (prefix '{p}0')")
        if has(lo, lo + half):
            leaf(lo, anc, level) if level == n - 1 else rec(level + 1, lo, anc)
        if ctrl is None:
            E(("x", anc), level=level, phase="uncompute", why=f"undo NOT on anc[{level}]")
            E(("cx", a, anc), level=level, phase="uncompute", why=f"clear anc[{level}] back to |0>")
        else:
            E(("cx", ctrl, anc), level=level, phase="uncompute", why=f"undo xor on anc[{level}]")
            E(("ccx", ctrl, a, anc), level=level, phase="uncompute", why=f"clear anc[{level}] back to |0>")
    rec(0, 0, None)
    return L, g

def init_state(L, addr):
    s = [0] * L.N
    for i in range(L.n): s[L.addr[i]] = (addr >> (L.n - 1 - i)) & 1
    return s

def apply(s, t):
    if t[0] == "x": s[t[1]] ^= 1
    elif t[0] == "cx": s[t[2]] ^= s[t[1]]
    else: s[t[3]] ^= s[t[1]] & s[t[2]]

def regs(L, s):
    j = lambda qs: "".join(str(s[q]) for q in qs)
    return {"addr": j(L.addr), "anc": j(L.anc), "data": j(L.data)}

def classical_query(L, gates, addr):
    s = init_state(L, addr)
    for t in gates: apply(s, t)
    assert all(s[q] == 0 for q in L.anc), "ancilla not clean"
    return int("".join(str(s[q]) for q in L.data), 2)

def trace_query(L, gates, addr, expected=None, snapshots=False):
    """Step-by-step execution record for one basis-state query."""
    s = init_state(L, addr); steps = []
    for i, t in enumerate(gates):
        before = list(s); apply(s, t)
        ch = [L.name(q) for q in range(L.N) if before[q] != s[q]]
        m = L.meta[i] if i < len(L.meta) else {}
        rec = {"step": i, "gate": t[0], "qubits": [L.name(q) for q in t[1:]], "level": m.get("level"),
               "phase": m.get("phase"), "why": m.get("why"), "changed": ch, "fired": bool(ch)}
        if "cell" in m: rec["cell"] = m["cell"]
        if snapshots: rec["state"] = regs(L, s)
        steps.append(rec)
    got = int("".join(str(s[q]) for q in L.data), 2)
    return {"address": addr, "address_bin": format(addr, f"0{L.n}b"), "expected": expected, "got": got,
            "match": (expected is None) or got == expected, "ancilla_clean": all(s[q] == 0 for q in L.anc),
            "final": regs(L, s), "steps": steps}

def print_trace(L, tr, max_steps=60, only_fired=True):
    print(f"\n=== TRACE addr={tr['address']} (bin {tr['address_bin']}) ===")
    print(f"initial: addr={tr['address_bin']} anc={'0'*L.n} data={'0'*L.d}")
    shown = 0
    for st in tr["steps"]:
        if only_fired and not st["fired"]: continue
        if shown >= max_steps: print(f"... ({len(tr['steps'])} total steps; use --max-steps to show more)"); break
        shown += 1
        print(f"#{st['step']:>5} {st['gate']:<3} {','.join(st['qubits']):<28} L{st['level']} [{st['phase']}] changed={st['changed']}\n        {st['why']}")
    print(f"final: addr={tr['final']['addr']} anc={tr['final']['anc']} data={tr['final']['data']}")
    print(f"result: got={tr['got']} expected={tr['expected']} match={tr['match']} ancilla_clean={tr['ancilla_clean']}")

def memory_report(words, n, d, limit=None):
    items = sorted(words.items())
    rows = [{"addr": a, "addr_bin": format(a, f"0{n}b"), "value_hex": format(v, f"0{(d+3)//4}x"), "value_bin": format(v, f"0{d}b"),
             "popcount": bin(v).count("1")} for a, v in items[:limit]]
    return {"cells": len(words), "nonzero_cells": sum(1 for v in words.values() if v),
            "stored_one_bits": sum(bin(v).count("1") for v in words.values()), "rows": rows, "truncated": limit is not None and len(items) > limit}

def gate_stats(L, g):
    by_type, by_level, by_phase = {}, {}, {}
    for i, t in enumerate(g):
        by_type[t[0]] = by_type.get(t[0], 0) + 1
        m = L.meta[i]; lv = str(m.get("level")); by_level[lv] = by_level.get(lv, 0) + 1
        ph = m.get("phase"); by_phase[ph] = by_phase.get(ph, 0) + 1
    return {"total": len(g), "by_type": by_type, "by_level": by_level, "by_phase": by_phase,
            "toffoli_count": by_type.get("ccx", 0), "cnot_count": by_type.get("cx", 0)}

def to_qiskit(L, gates, prep_addr=None, superpose=False, measure=True):
    from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
    ra, rn, rd = QuantumRegister(L.n, "addr"), QuantumRegister(L.n, "anc"), QuantumRegister(L.d, "data")
    qc = QuantumCircuit(ra, rn, rd, name=f"QRAM_{L.N}q"); q = list(ra) + list(rn) + list(rd)
    if superpose: qc.h(ra)
    elif prep_addr is not None:
        for i in range(L.n):
            if (prep_addr >> (L.n - 1 - i)) & 1: qc.x(q[L.addr[i]])
    qc.barrier()
    for t in gates:
        if t[0] == "x": qc.x(q[t[1]])
        elif t[0] == "cx": qc.cx(q[t[1]], q[t[2]])
        else: qc.ccx(q[t[1]], q[t[2]], q[t[3]])
    qc.barrier()
    if measure:
        ca, cd = ClassicalRegister(L.n, "ca"), ClassicalRegister(L.d, "cd")
        qc.add_register(ca, cd); qc.measure(ra, ca); qc.measure(rd, cd)
    return qc

def decode(bitstr, n, d):
    b = bitstr.replace(" ", ""); return int(b[d:], 2), int(b[:d], 2)

def max_sv_qubits(vram_gb, single=True):
    return int(math.floor(math.log2(vram_gb * 2**30 / (8 if single else 16) / 2)))

def run_aer_statevector(qc, shots=2048, vram_gb=8, single=True):
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    assert qc.num_qubits <= max_sv_qubits(vram_gb, single), "exceeds VRAM budget"
    prec = "single" if single else "double"
    try: sim = AerSimulator(method="statevector", device="GPU", precision=prec, cuStateVec_enable=True)
    except Exception: sim = AerSimulator(method="statevector", precision=prec)
    return sim.run(transpile(qc, sim), shots=shots).result().get_counts()

def run_aer_mps(qc, shots=256):
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    sim = AerSimulator(method="matrix_product_state")
    return sim.run(transpile(qc, sim), shots=shots).result().get_counts()

def ibm_save_account(token, instance=None):
    from qiskit_ibm_runtime import QiskitRuntimeService
    QiskitRuntimeService.save_account(channel="ibm_quantum_platform", token=token, instance=instance, set_as_default=True, overwrite=True)

def ibm_connect():
    from qiskit_ibm_runtime import QiskitRuntimeService
    tok, inst = os.environ.get("QISKIT_IBM_TOKEN"), os.environ.get("QISKIT_IBM_INSTANCE")
    if tok: return QiskitRuntimeService(channel="ibm_quantum_platform", token=tok, instance=inst)
    return QiskitRuntimeService()

def ibm_list_backends(min_qubits=1):
    for b in ibm_connect().backends(simulator=False, operational=True, min_num_qubits=min_qubits):
        print(f"{b.name:20s} {b.num_qubits:4d}q  pending_jobs={b.status().pending_jobs}")

def run_ibm(qc, backend_name=None, shots=4000, opt=3, info=None):
    from qiskit import transpile
    from qiskit_ibm_runtime import SamplerV2
    svc = ibm_connect()
    be = svc.backend(backend_name) if backend_name else svc.least_busy(operational=True, simulator=False, min_num_qubits=qc.num_qubits)
    tq = transpile(qc, be, optimization_level=opt); ops = dict(tq.count_ops())
    twoq = sum(v for k, v in ops.items() if k in ("cz", "ecr", "cx"))
    print(f"[IBM] {be.name}: depth={tq.depth()} 2q-gates={twoq}")
    job = SamplerV2(mode=be).run([tq], shots=shots)
    print("[IBM] job id:", job.job_id(), "(waiting for result...)")
    if info is not None: info.update(backend=be.name, job_id=job.job_id(), transpiled_depth=tq.depth(), transpiled_ops=ops, transpiled_2q=twoq)
    return job.result()[0].data

def arbitrary_data(n, d, seed=7):
    rng = np.random.default_rng(seed)
    return {a: int.from_bytes(rng.bytes((d + 7) // 8), "big") & ((1 << d) - 1) for a in range(1 << n)}

def big_data_pages(blob, n, d):
    bits = "".join(f"{b:08b}" for b in blob); bits += "0" * (-len(bits) % d)
    words = [int(bits[i:i + d], 2) for i in range(0, len(bits), d)]; P = 1 << n
    return [{i: w for i, w in enumerate(words[p:p + P])} for p in range(0, len(words), P)], len(words)

class PagedQRAM:
    def __init__(s, blob, n, d):
        s.n, s.d = n, d; s.pages, s.nwords = big_data_pages(blob, n, d); s.built = {}
    def _get(s, idx):
        p, a = divmod(idx, 1 << s.n)
        if p not in s.built: s.built[p] = build_gates(s.pages[p], s.n, s.d)
        return p, s.built[p], a
    def circuit(s, idx, superpose=False):
        p, (L, g), a = s._get(idx); return to_qiskit(L, g, prep_addr=a, superpose=superpose)
    def classical_read(s, idx):
        p, (L, g), a = s._get(idx); return classical_query(L, g, a)

def demo(args):
    n, d = SPECS[args.size]["n"], SPECS[args.size]["d"]
    out = {"config": {"size": args.size, "n_address": n, "n_ancilla": n, "data_bits": d, "qubits": 2*n+d, "capacity_words": 1 << n,
                      "mode": args.mode, "where": args.where, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}}
    qaddr = args.trace_addr if args.trace_addr is not None else 5 % (1 << n)
    if args.mode == "arbitrary":
        words = arbitrary_data(n, d); L, g = build_gates(words, n, d); page = 0; local_addr = qaddr
        bad = [a for a in range(1 << n) if classical_query(L, g, a) != words[a]]
        out["memory"] = memory_report(words, n, d, args.mem_limit)
        out["verification"] = {"addresses_checked": 1 << n, "mismatches": bad}
        print(f"[verify] {1<<n} addresses x {d} bits, mismatches={len(bad)}, qubits={L.N}, gates={len(g)}")
        exp = words[local_addr]
    else:
        blob = os.urandom(args.blob_bytes); pq = PagedQRAM(blob, n, d)
        idx = qaddr % pq.nwords; page, (L, g), local_addr = pq._get(idx)
        words = pq.pages[page]; exp = words.get(local_addr, 0)
        rng = np.random.default_rng(1).integers(0, pq.nwords, 20); bits = "".join(f"{b:08b}" for b in blob); bits += "0" * (-len(bits) % d)
        ok = [bool(pq.classical_read(int(i)) == int(bits[i*d:(i+1)*d], 2)) for i in rng]
        out["big_data"] = {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(), "words": pq.nwords, "pages": len(pq.pages),
                           "words_per_page": 1 << n, "read_checks": [{"global_index": int(i), "page": int(i) >> n, "ok": o} for i, o in zip(rng, ok)],
                           "traced_global_index": idx, "traced_page": page}
        out["memory"] = memory_report(words, n, d, args.mem_limit)
        print(f"[big] {len(blob)} B -> {pq.nwords} words -> {len(pq.pages)} pages; 20 random reads ok={all(ok)}; tracing page {page}")
    out["gates"] = gate_stats(L, g)
    print(f"[gates] {out['gates']['total']} total | Toffoli={out['gates']['toffoli_count']} CNOT={out['gates']['cnot_count']} | by level={out['gates']['by_level']}")
    if args.trace:
        tr = trace_query(L, g, local_addr, exp, snapshots=args.snapshots)
        print_trace(L, tr, args.max_steps, only_fired=not args.all_steps); out["trace"] = tr
    if args.where != "verify":
        qc = to_qiskit(L, g, prep_addr=local_addr)
        out["circuit"] = {"qubits": qc.num_qubits, "depth": qc.depth(), "ops": dict(qc.count_ops())}
        print(f"[circuit] {out['circuit']}")
        info = {}
        if args.where == "aer-gpu":
            counts = run_aer_statevector(qc, args.shots, args.vram) if qc.num_qubits <= max_sv_qubits(args.vram) else run_aer_mps(qc, args.shots)
        elif args.where == "aer-mps": counts = run_aer_mps(qc, args.shots)
        else: counts = run_ibm(qc, args.backend, args.shots, info=info).join_data().get_counts()
        tot = sum(counts.values()); best = max(counts, key=counts.get); a, v = decode(best, L.n, L.d)
        ok_shots = sum(c for k, c in counts.items() if decode(k, L.n, L.d) == (local_addr, exp))
        out["execution"] = {**info, "shots": tot, "distinct_outcomes": len(counts), "expected_addr": local_addr, "expected_data": exp,
                            "top_outcome": {"addr": a, "data": v, "prob": counts[best] / tot},
                            "correct_shots": ok_shots, "fidelity_estimate": ok_shots / tot,
                            "top20": [{"addr": decode(k, L.n, L.d)[0], "data": decode(k, L.n, L.d)[1], "count": c} for k, c in sorted(counts.items(), key=lambda x: -x[1])[:20]]}
        print(f"[result] top addr={a} data==expected:{v == exp} p={counts[best]/tot:.3f}  correct-shot fraction={ok_shots/tot:.3f}")
    if args.json:
        with open(args.json, "w") as f: json.dump(out, f, indent=1)
        print(f"[json] wrote {args.json} ({os.path.getsize(args.json)} bytes)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", choices=SPECS, default="30")
    ap.add_argument("--mode", choices=["arbitrary", "big"], default="arbitrary")
    ap.add_argument("--where", choices=["verify", "aer-gpu", "aer-mps", "ibm"], default="verify")
    ap.add_argument("--shots", type=int, default=2048)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--vram", type=float, default=8)
    ap.add_argument("--trace", action="store_true", help="step-by-step gate trace of one query")
    ap.add_argument("--trace-addr", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--all-steps", action="store_true", help="also show gates that changed nothing")
    ap.add_argument("--snapshots", action="store_true", help="store full register state after every step in JSON")
    ap.add_argument("--mem-limit", type=int, default=None, help="max memory rows in JSON")
    ap.add_argument("--blob-bytes", type=int, default=200000)
    ap.add_argument("--json", default=None, help="write fine-grained results to this JSON file")
    ap.add_argument("--save-account", action="store_true")
    ap.add_argument("--list-backends", action="store_true")
    a = ap.parse_args()
    if a.save_account:
        ibm_save_account(os.environ["QISKIT_IBM_TOKEN"], os.environ.get("QISKIT_IBM_INSTANCE")); print("saved"); raise SystemExit
    if a.list_backends: ibm_list_backends(); raise SystemExit
    demo(a)
