import csv
import sys
import time
import shutil
from pathlib import Path
from typing import Callable

from pysat.formula import CNF
from pysat.solvers import Solver as PySatSolver

from CFG_2_SAT import CFG_2_SAT, parse_input_file_to_chomsky
from generate_benchmark_words import generate_words_from_grammar

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


def _make_row(
    dimacs_path: Path,
    solver_name: str,
    status: str,
    result: str,
    elapsed_ms: float,
    grammar_index: int,
    word: str,
    word_length: int,
    positive_or_negative: str,
) -> dict[str, str]:
    return {
        "dimacs_file": str(dimacs_path),
        "solver": solver_name,
        "grammar": str(grammar_index),
        "word": word,
        "word_length": str(word_length),
        "positive_or_negative": positive_or_negative,
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


def _run_solver(
    dimacs_path: Path,
    cnf: CNF,
    solver_name: str,
    solve_fn: Callable[[CNF], tuple[str, str]],
    grammar_index: int,
    word: str,
    word_length: int,
    positive_or_negative: str,
) -> dict[str, str]:
    start = time.perf_counter()
    status = "ok"
    result = ""

    try:
        status, result = solve_fn(cnf)
    except Exception as exc:
        status = "error"
        result = type(exc).__name__

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return _make_row(
        dimacs_path,
        solver_name,
        status,
        result,
        elapsed_ms,
        grammar_index,
        word,
        word_length,
        positive_or_negative,
    )


def benchmark_dimacs_file(
    dimacs_path: Path,
    grammar_index: int,
    word: str,
    positive_or_negative: str,
) -> list[dict[str, str]]:
    cnf = CNF(from_file=str(dimacs_path))
    rows: list[dict[str, str]] = []
    word_length = 0 if not word else len(word.split())

    for solver_name in PYSAT_SOLVER_NAMES:
        rows.append(
            _run_solver(
                dimacs_path,
                cnf,
                f"pysat:{solver_name}",
                lambda current_cnf, name=solver_name: _solve_with_pysat(current_cnf, name),
                grammar_index,
                word,
                word_length,
                positive_or_negative,
            )
        )

    rows.append(_run_solver(dimacs_path, cnf, "z3", _solve_with_z3, grammar_index, word, word_length, positive_or_negative))
    rows.append(_run_solver(dimacs_path, cnf, "pycosat", _solve_with_pycosat, grammar_index, word, word_length, positive_or_negative))
    rows.append(_run_solver(dimacs_path, cnf, "pycryptosat", _solve_with_pycryptosat, grammar_index, word, word_length, positive_or_negative))

    return rows


def _generate_up_to_words(
    grammar,
    negative: bool,
    target_count: int,
    min_length: int,
    seed: int | None,
) -> list[str]:
    """
    Generate up to target_count words. If target is not possible, fallback to the biggest feasible count.
    """
    for count in range(target_count, -1, -1):
        try:
            return generate_words_from_grammar(
                grammar=grammar,
                min_length=min_length,
                count=count,
                negative=negative,
                seed=seed,
                max_tries=50000,
            )
        except ValueError:
            continue
    return []


def _copy_dimacs_for_case(
    dimacs_path: Path,
    grammar_file: Path,
    grammar_index: int,
    positive_or_negative: str,
    word_index: int,
) -> Path:
    """
    Keep a unique DIMACS file per (grammar, word, polarity) benchmark case.
    """
    base_dir = grammar_file.parent / "dimacs_outputs" / "benchmark_runs" / grammar_file.stem
    base_dir.mkdir(parents=True, exist_ok=True)
    target = base_dir / f"g{grammar_index}_{positive_or_negative}_w{word_index}.cnf"
    shutil.copyfile(dimacs_path, target)
    return target


def benchmark_from_grammar_file(
    grammar_file: str,
    min_length: int = 10,
    positive_count: int = 10,
    negative_count: int = 10,
    seed: int | None = None,
) -> list[dict[str, str]]:
    if not seed:
        seed = int(time.time())
    grammar_path = Path(grammar_file)
    grammars = parse_input_file_to_chomsky(grammar_file)
    all_rows: list[dict[str, str]] = []

    for grammar_idx, grammar in enumerate(grammars, start=1):
        pos_words = _generate_up_to_words(
            grammar=grammar,
            negative=False,
            target_count=positive_count,
            min_length=min_length,
            seed=None if seed is None else seed + grammar_idx * 1000 + 1,
        )
        neg_words = _generate_up_to_words(
            grammar=grammar,
            negative=True,
            target_count=negative_count,
            min_length=min_length,
            seed=None if seed is None else seed + grammar_idx * 1000 + 2,
        )

        cases: list[tuple[str, str]] = [("positive", w) for w in pos_words]
        cases.extend(("negative", w) for w in neg_words)

        for word_idx, (label, word) in enumerate(cases, start=1):
            cfg_sat = CFG_2_SAT(grammar, word, solve=False)
            if cfg_sat.dimacs_path is None:
                continue

            case_dimacs = _copy_dimacs_for_case(
                Path(cfg_sat.dimacs_path),
                grammar_path,
                grammar_idx,
                label,
                word_idx,
            )
            all_rows.extend(
                benchmark_dimacs_file(
                    case_dimacs,
                    grammar_index=grammar_idx,
                    word=word,
                    positive_or_negative=label,
                )
            )

    return all_rows


def write_csv(rows: list[dict[str, str]], output_csv: Path) -> None:
    if not rows:
        return

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "dimacs_file",
                "solver",
                "grammar",
                "word",
                "word_length",
                "positive_or_negative",
                "status",
                "result",
                "time_ms",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, str]]) -> None:
    print("solver,grammar,word_length,positive_or_negative,status,result,time_ms,file")
    for row in rows:
        print(
            f"{row['solver']},{row['grammar']},{row['word_length']},{row['positive_or_negative']},"
            f"{row['status']},{row['result']},{row['time_ms']},{row['dimacs_file']}"
        )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python src/benchmark_sat_solvers.py <grammar_file>")
        return 1

    grammar_file = sys.argv[1]
    grammar_path = Path(grammar_file)
    if not grammar_path.exists():
        print(f"Missing grammar file: {grammar_file}")
        return 1

    all_rows = benchmark_from_grammar_file(grammar_file)

    if not all_rows:
        print("No benchmark data produced.")
        return 1

    results_dir = grammar_path.parent / "results" / grammar_path.stem
    results_dir.mkdir(parents=True, exist_ok=True)
    output_csv = results_dir / f"{grammar_path.stem}_solver_benchmark_results.csv"
    write_csv(all_rows, output_csv)
    print_summary(all_rows)
    print(f"Results saved to: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
