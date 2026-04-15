import csv
import logging
import sys
import time
import shutil
import subprocess
import argparse
import tempfile
from pathlib import Path
from typing import Callable

from pysat.formula import CNF
from pysat.solvers import Solver as PySatSolver

from CFG_2_SAT import CFG_2_SAT
from modules.parser import parse_grammar_file_to_chomsky

logger = logging.getLogger("benchmark")

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
    stats: dict[str, int],
) -> dict[str, str]:
    return {
        "dimacs_file": str(dimacs_path),
        "solver": solver_name,
        "grammar": str(grammar_index),
        "word": word,
        "word_length": str(word_length),
        "positive_or_negative": positive_or_negative,
        "nonterminal_count": str(stats.get("nonterminal_count", 0)),
        "rule_count": str(stats.get("rule_count", 0)),
        "singular_rule_count": str(stats.get("singular_rule_count", 0)),
        "double_rule_count": str(stats.get("double_rule_count", 0)),
        "bool_variable_count": str(stats.get("bool_variable_count", 0)),
        "base_bool_variable_count": str(stats.get("base_bool_variable_count", 0)),
        "tseitin_variable_count": str(stats.get("tseitin_variable_count", 0)),
        "clause_count": str(stats.get("clause_count", 0)),
        "fixed_value_clause_count": str(stats.get("fixed_value_clause_count", 0)),
        "tseitin_clause_count": str(stats.get("tseitin_clause_count", 0)),
        "window_clause_count": str(stats.get("window_clause_count", 0)),
        "status": status,
        "result": result,
        "time_ms": f"{elapsed_ms:.3f}",
    }


def _solve_with_pysat(cnf: CNF, solver_name: str) -> tuple[str, str]:
    with PySatSolver(name=solver_name, bootstrap_with=cnf.clauses) as solver:
        return "ok", ("SAT" if solver.solve() else "UNSAT")


def _solve_with_pycryptosat(cnf: CNF) -> tuple[str, str]:
    if CryptoSolver is None:
        return "skipped", "missing-pycryptosat"

    solver = CryptoSolver()
    for clause in cnf.clauses:
        solver.add_clause(clause)

    sat_result, _ = solver.solve()
    return "ok", ("SAT" if sat_result else "UNSAT")


def _run_solver_inprocess(
    dimacs_path: Path,
    cnf: CNF,
    solver_name: str,
    solve_fn: Callable[[CNF], tuple[str, str]],
    grammar_index: int,
    word: str,
    word_length: int,
    positive_or_negative: str,
    stats: dict[str, int],
) -> dict[str, str]:
    start = time.perf_counter()
    status = "ok"
    result = ""

    logger.info("Running %s for grammar=%s word_length=%s", solver_name, grammar_index, word_length)

    try:
        status, result = solve_fn(cnf)
    except Exception as exc:
        status = "error"
        result = type(exc).__name__
        logger.exception("Solver %s failed for grammar=%s word=%r", solver_name, grammar_index, word)

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    logger.info("Finished %s status=%s result=%s time_ms=%.3f", solver_name, status, result, elapsed_ms)
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
        stats,
    )


def benchmark_dimacs_file(
    dimacs_path: Path,
    grammar_index: int,
    word: str,
    positive_or_negative: str,
    stats: dict[str, int],
) -> list[dict[str, str]]:
    logger.info("Benchmarking DIMACS %s", dimacs_path)
    cnf = CNF(from_file=str(dimacs_path))
    nv = 0
    nclauses = 0
    try:
        with open(dimacs_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("p cnf "):
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        nv = int(parts[2])
                        nclauses = int(parts[3])
                    break
    except Exception:
        pass
    logger.info("CNF size: variables=%s clauses=%s", nv, nclauses)
    rows: list[dict[str, str]] = []
    word_length = 0 if not word else len(word.split())

    for solver_name in PYSAT_SOLVER_NAMES:
        rows.append(
            _run_solver_inprocess(
                dimacs_path,
                cnf,
                f"pysat:{solver_name}",
                lambda current_cnf, name=solver_name: _solve_with_pysat(current_cnf, name),
                grammar_index,
                word,
                word_length,
                positive_or_negative,
                stats,
            )
        )

    rows.append(
        _run_solver_inprocess(
            dimacs_path,
            cnf,
            "pycryptosat",
            _solve_with_pycryptosat,
            grammar_index,
            word,
            word_length,
            positive_or_negative,
            stats,
        )
    )

    return rows


def _parse_java_generated_words(output_path: Path) -> list[str]:
    if not output_path.exists():
        return []

    words: list[str] = []
    in_generated = False

    for raw_line in output_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not in_generated:
            if line == "Generated words:":
                in_generated = True
            continue

        if line.startswith("Statistics:"):
            break
        if not line:
            continue
        if line.startswith("This grammar"):
            continue

        words.append(line)

    return words


def _generate_words_with_java_jar(
    java_grammar_file: str,
    min_length: int,
    max_length: int,
    target_count: int,
    jar_path: str,
    label: str,
) -> list[str]:
    if target_count <= 0:
        return []

    grammar_path = Path(java_grammar_file).resolve()
    jar = Path(jar_path).resolve()
    if not jar.exists():
        return []

    cwd = jar.parent
    output_path = cwd / "output.txt"
    seen: set[str] = set()
    words: list[str] = []
    logger.info("Using Java word generator jar for %s words: %s", label, jar)

    # Retry with larger repetition counts when duplicates are produced.
    for attempt in range(3):
        repetitions = max(target_count * (4 + attempt * 2), target_count + 20)
        logger.info(
            "Java generation attempt %s/%s for %s words (target=%s, min_length=%s, max_length=%s, repetitions=%s)",
            attempt + 1,
            3,
            label,
            target_count,
            min_length,
            max_length,
            repetitions,
        )
        command = [
            "java",
            "-jar",
            str(jar),
            str(grammar_path),
            str(min_length),
            str(max_length),
            str(repetitions),
            label,
        ]

        try:
            completed = subprocess.run(command, cwd=str(cwd), check=True, capture_output=True, text=True, timeout=180)
            if completed.stdout:
                logger.debug("Java generator stdout:\n%s", completed.stdout)
            if completed.stderr:
                logger.debug("Java generator stderr:\n%s", completed.stderr)
        except Exception as exc:
            logger.warning("Java generator attempt failed: %s", exc)
            continue

        for word in _parse_java_generated_words(output_path):
            length = 0 if not word else len(word.split())
            if length < min_length or length > max_length:
                continue
            if word in seen:
                continue

            seen.add(word)
            words.append(word)
            if len(words) >= target_count:
                return words

    return words


def _split_grammar_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []

    for raw_line in text.splitlines():
        if raw_line.strip() == "---":
            block = "\n".join(current).strip()
            if block:
                blocks.append(block)
            current = []
            continue
        current.append(raw_line)

    tail = "\n".join(current).strip()
    if tail:
        blocks.append(tail)

    return blocks


def _write_java_grammar_block_temp_file(grammar_block: str) -> Path:
    # The Java generator expects exactly one grammar per input file.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as tmp:
        tmp.write(grammar_block.strip() + "\n")
        return Path(tmp.name)


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
    base_dir = grammar_file.parent.parent / "dimacs_outputs" / "benchmark_runs" / grammar_file.stem
    base_dir.mkdir(parents=True, exist_ok=True)
    target = base_dir / f"g{grammar_index}_{positive_or_negative}_w{word_index}.cnf"
    shutil.copyfile(dimacs_path, target)
    return target


def benchmark_from_grammar_file(
    grammar_file: str,
    min_length: int = 10,
    max_length: int = 18,
    positive_count: int = 10,
    negative_count: int = 10,
    java_jar_path: str | None = None,
) -> list[dict[str, str]]:
    if java_jar_path is None:
        raise ValueError("Java-only benchmark mode requires --java-jar.")

    grammar_path = Path(grammar_file)
    logger.info("Loading grammars from %s", grammar_path)
    grammars = parse_grammar_file_to_chomsky(grammar_file)
    java_grammar_path = grammar_path.parent.parent / "output" / "JavaGrammar" / f"{grammar_path.stem}.txt"
    all_rows: list[dict[str, str]] = []

    java_grammar_blocks: list[str] = []
    if java_grammar_path.exists():
        java_grammar_blocks = _split_grammar_blocks(java_grammar_path.read_text(encoding="utf-8", errors="ignore"))
    else:
        logger.warning("Java grammar export not found at %s; no words will be generated", java_grammar_path)
    logger.info("Parsed %s grammar(s); Java-only generator mode is enabled", len(grammars))

    for grammar_idx, grammar in enumerate(grammars, start=1):
        logger.info("Starting grammar %s/%s", grammar_idx, len(grammars))
        pos_words: list[str] = []
        neg_words: list[str] = []
        if grammar_idx <= len(java_grammar_blocks):
            temp_grammar_path = _write_java_grammar_block_temp_file(java_grammar_blocks[grammar_idx - 1])
            try:
                pos_words = _generate_words_with_java_jar(
                    java_grammar_file=str(temp_grammar_path),
                    min_length=min_length,
                    max_length=max_length,
                    target_count=positive_count,
                    jar_path=java_jar_path,
                    label="positive",
                )
                neg_words = _generate_words_with_java_jar(
                    java_grammar_file=str(temp_grammar_path),
                    min_length=min_length,
                    max_length=max_length,
                    target_count=negative_count,
                    jar_path=java_jar_path,
                    label="negative",
                )
            finally:
                temp_grammar_path.unlink(missing_ok=True)
            logger.info("Java generator produced %s positive words", len(pos_words))
            logger.info("Java generator produced %s negative words", len(neg_words))
        else:
            logger.warning(
                "Missing Java grammar block for grammar index %s (available=%s); skipping this grammar",
                grammar_idx,
                len(java_grammar_blocks),
            )

        if len(pos_words) < positive_count:
            logger.warning(
                "Java generator produced only %s/%s positive words for grammar=%s",
                len(pos_words),
                positive_count,
                grammar_idx,
            )
        if len(neg_words) < negative_count:
            logger.warning(
                "Java generator produced only %s/%s negative words for grammar=%s",
                len(neg_words),
                negative_count,
                grammar_idx,
            )

        cases: list[tuple[str, str]] = [("positive", w) for w in pos_words]
        cases.extend(("negative", w) for w in neg_words)

        for word_idx, (label, word) in enumerate(cases, start=1):
            cfg_sat = CFG_2_SAT(grammar, word, solve=False)
            if cfg_sat.dimacs_path is None:
                logger.warning("No DIMACS produced for grammar=%s word=%r", grammar_idx, word)
                continue
            stats = cfg_sat.get_stats()

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
                    stats=stats,
                )
            )

    return all_rows


def write_csv(rows: list[dict[str, str]], output_csv: Path) -> None:
    if not rows:
        return

    logger.info("Writing %s benchmark rows to %s", len(rows), output_csv)

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
                "nonterminal_count",
                "rule_count",
                "singular_rule_count",
                "double_rule_count",
                "bool_variable_count",
                "base_bool_variable_count",
                "tseitin_variable_count",
                "clause_count",
                "fixed_value_clause_count",
                "tseitin_clause_count",
                "window_clause_count",
                "status",
                "result",
                "time_ms",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, str]]) -> None:
    print("solver,grammar,word_length,positive_or_negative,nonterminal_count,rule_count,bool_variable_count,clause_count,status,result,time_ms,file")
    for row in rows:
        print(
            f"{row['solver']},{row['grammar']},{row['word_length']},{row['positive_or_negative']},"
            f"{row['nonterminal_count']},{row['rule_count']},{row['bool_variable_count']},{row['clause_count']},"
            f"{row['status']},{row['result']},{row['time_ms']},{row['dimacs_file']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark SAT solvers on CFG->SAT DIMACS instances.")
    parser.add_argument("grammar_file", help="Path to grammar file.")
    parser.add_argument("--min-length", type=int, default=10, help="Minimal generated word length.")
    parser.add_argument("--max-length", type=int, default=18, help="Maximal generated word length.")
    parser.add_argument("--positive-count", type=int, default=10, help="Positive words per grammar.")
    parser.add_argument("--negative-count", type=int, default=10, help="Negative words per grammar.")
    parser.add_argument(
        "--java-jar",
        default=None,
        help="Java generator JAR used for both positive and negative word generation.",
    )
    args = parser.parse_args()

    if args.min_length < 0 or args.max_length < args.min_length:
        print("Invalid length range. Require 0 <= min-length <= max-length.")
        return 1

    grammar_file = args.grammar_file
    grammar_path = Path(grammar_file)
    if not grammar_path.exists():
        print(f"Missing grammar file: {grammar_file}")
        return 1

    java_jar = args.java_jar
    if java_jar is None:
        java_jar = str(Path(__file__).resolve().parent / "modules" / "WordGenerator.jar")

    if not Path(java_jar).exists():
        print(f"Missing Java JAR: {java_jar}")
        return 1

    log_file = grammar_path.parent.parent / "results" / grammar_path.stem / f"{grammar_path.stem}_benchmark.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )
    logger.info("Benchmark started")
    logger.info("Grammar file: %s", grammar_path)
    logger.info("Log file: %s", log_file)
    logger.info("Length range: %s..%s positive=%s negative=%s", args.min_length, args.max_length, args.positive_count, args.negative_count)
    if args.java_jar:
        logger.info("Java generator jar: %s", java_jar)
    else:
        logger.info("Java generator jar: %s (default)", java_jar)

    try:
        all_rows = benchmark_from_grammar_file(
            grammar_file,
            min_length=args.min_length,
            max_length=args.max_length,
            positive_count=args.positive_count,
            negative_count=args.negative_count,
            java_jar_path=java_jar,
        )
    except Exception:
        logger.exception("Benchmark failed")
        return 1

    if not all_rows:
        print("No benchmark data produced.")
        return 1

    results_dir = grammar_path.parent.parent / "results" / grammar_path.stem
    results_dir.mkdir(parents=True, exist_ok=True)
    output_csv = results_dir / f"{grammar_path.stem}_solver_benchmark_results.csv"
    write_csv(all_rows, output_csv)
    print_summary(all_rows)
    print(f"Results saved to: {output_csv}")
    logger.info("Benchmark finished successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
