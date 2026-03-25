import csv
import sys
import time
from pathlib import Path
from typing import Callable

from pysat.formula import CNF
from pysat.solvers import Solver as PySatSolver

try:
    import z3  # type: ignore
except Exception:
    z3 = None

try:
    import pycosat  # type: ignore
except Exception:
    pycosat = None

try:
    from pycryptosat import Solver as CryptoSolver  # type: ignore
except Exception:
    CryptoSolver = None


# Seven solver backends to benchmark (if available in the local PySAT build).
PYSAT_SOLVER_NAMES = [
    "g3",   # Glucose3
    "g4",   # Glucose4
    "gc3",  # Gluecard3
    "gc4",  # Gluecard4
    "m22",  # Minisat22
    "mc",   # MapleCM
    "mgh",  # MapleGH
]


def _make_row(dimacs_path: Path, solver_name: str, status: str, result: str, elapsed_ms: float) -> dict[str, str]:
    return {
        "dimacs_file": str(dimacs_path),
        "solver": solver_name,
        "status": status,
        "result": result,
        "time_ms": f"{elapsed_ms:.3f}",
    }


def _solve_with_pysat(cnf: CNF, solver_name: str) -> tuple[str, str]:
    with PySatSolver(name=solver_name, bootstrap_with=cnf.clauses) as solver:
        return "ok", ("SAT" if solver.solve() else "UNSAT")


def _solve_with_z3(cnf: CNF) -> tuple[str, str]:
    if z3 is None:
        return "skipped", "missing-z3-solver"

    solver = z3.Solver()
    bool_vars = [z3.Bool(f"x{i}") for i in range(cnf.nv + 1)]

    for clause in cnf.clauses:
        z3_literals = []
        for lit in clause:
            var = bool_vars[abs(lit)]
            z3_literals.append(var if lit > 0 else z3.Not(var))
        solver.add(z3.Or(*z3_literals))

    result = solver.check()
    if result == z3.sat:
        return "ok", "SAT"
    if result == z3.unsat:
        return "ok", "UNSAT"
    return "ok", "UNKNOWN"


def _solve_with_pycosat(cnf: CNF) -> tuple[str, str]:
    if pycosat is None:
        return "skipped", "missing-pycosat"

    result = pycosat.solve(cnf.clauses)
    if result == "UNSAT":
        return "ok", "UNSAT"
    if result == "UNKNOWN":
        return "ok", "UNKNOWN"
    return "ok", "SAT"


def _solve_with_pycryptosat(cnf: CNF) -> tuple[str, str]:
    if CryptoSolver is None:
        return "skipped", "missing-pycryptosat"

    solver = CryptoSolver()
    for clause in cnf.clauses:
        solver.add_clause(clause)

    sat_result, _ = solver.solve()
    return "ok", ("SAT" if sat_result else "UNSAT")


def _run_solver(dimacs_path: Path, cnf: CNF, solver_name: str, solve_fn: Callable[[CNF], tuple[str, str]]) -> dict[str, str]:
    start = time.perf_counter()
    status = "ok"
    result = ""

    try:
        status, result = solve_fn(cnf)
    except Exception as exc:
        status = "error"
        result = type(exc).__name__

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return _make_row(dimacs_path, solver_name, status, result, elapsed_ms)


def benchmark_dimacs_file(dimacs_path: Path) -> list[dict[str, str]]:
    cnf = CNF(from_file=str(dimacs_path))
    rows: list[dict[str, str]] = []

    for solver_name in PYSAT_SOLVER_NAMES:
        rows.append(
            _run_solver(
                dimacs_path,
                cnf,
                f"pysat:{solver_name}",
                lambda current_cnf, name=solver_name: _solve_with_pysat(current_cnf, name),
            )
        )

    rows.append(_run_solver(dimacs_path, cnf, "z3", _solve_with_z3))
    rows.append(_run_solver(dimacs_path, cnf, "pycosat", _solve_with_pycosat))
    rows.append(_run_solver(dimacs_path, cnf, "pycryptosat", _solve_with_pycryptosat))

    return rows


def write_csv(rows: list[dict[str, str]], output_csv: Path) -> None:
    if not rows:
        return

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["dimacs_file", "solver", "status", "result", "time_ms"])
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, str]]) -> None:
    print("solver,status,result,time_ms,file")
    for row in rows:
        print(
            f"{row['solver']},{row['status']},{row['result']},{row['time_ms']},{row['dimacs_file']}"
        )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python src/benchmark_sat_solvers.py <dimacs1> [<dimacs2> ...]")
        return 1

    dimacs_files = [Path(arg) for arg in sys.argv[1:]]
    all_rows: list[dict[str, str]] = []

    for dimacs_file in dimacs_files:
        if not dimacs_file.exists():
            print(f"Skipping missing file: {dimacs_file}")
            continue
        all_rows.extend(benchmark_dimacs_file(dimacs_file))

    if not all_rows:
        print("No benchmark data produced.")
        return 1

    output_csv = Path("src/text/solver_benchmark_results.csv")
    write_csv(all_rows, output_csv)
    print_summary(all_rows)
    print(f"Results saved to: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
