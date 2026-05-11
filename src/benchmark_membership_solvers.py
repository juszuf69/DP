import argparse
import csv
import logging
import sys
import time
from pathlib import Path

from pysat.formula import CNF
from pysat.solvers import Solver as PySatSolver

from CFG_2_SAT import CFG_2_SAT
from benchmark_sat_solvers import (
    _generate_words_with_java_jar,
    _split_grammar_blocks,
    _write_java_grammar_block_temp_file,
)
from modules.CYK import cyk_accepts
from modules.parser import parse_grammar_file_to_chomsky

logger = logging.getLogger("membership-benchmark")


def _build_row(
    solver: str,
    grammar_index: int,
    word: str,
    positive_or_negative: str,
    status: str,
    result: str,
    elapsed_ms: float,
    conversion_ms: float,
    solve_ms: float,
    stats: dict[str, int],
) -> dict[str, str]:
    return {
        "solver": solver,
        "grammar": str(grammar_index),
        "word": word,
        "word_length": str(0 if not word else len(word.split())),
        "positive_or_negative": positive_or_negative,
        "nonterminal_count": str(stats.get("nonterminal_count", 0)),
        "rule_count": str(stats.get("rule_count", 0)),
        "status": status,
        "result": result,
        "time_ms": f"{elapsed_ms:.3f}",
        "time_conversion_ms": f"{conversion_ms:.3f}",
        "time_solve_ms": f"{solve_ms:.3f}",
    }


def _grammar_stats(grammar) -> dict[str, int]:
    return {
        "nonterminal_count": len(grammar.NonTerminals),
        "rule_count": len(grammar.rules),
    }


def _run_sat_solver(grammar, word: str, sat_solver_name: str) -> tuple[str, str, float, float, float, dict[str, int]]:
    start = time.perf_counter()
    status = "ok"
    result = "REJECT"
    stats: dict[str, int] = {}
    conversion_ms = 0.0
    solve_ms = 0.0

    try:
        # Measure CNF conversion time
        conversion_start = time.perf_counter()
        cfg_sat = CFG_2_SAT(grammar, word, solve=False, save_dimacs=False, verbose=False)
        conversion_ms = (time.perf_counter() - conversion_start) * 1000.0
        stats = cfg_sat.get_stats()

        word_tokens = [] if not word.strip() else word.split()
        if not word_tokens:
            result = "ACCEPT" if getattr(grammar, "accepts_epsilon", False) else "REJECT"
        else:
            # Measure SAT solver time
            solve_start = time.perf_counter()
            cnf = CNF(from_clauses=cfg_sat.clauses)
            with PySatSolver(name=sat_solver_name, bootstrap_with=cnf.clauses) as solver:
                sat_result = solver.solve()
            solve_ms = (time.perf_counter() - solve_start) * 1000.0
            result = "ACCEPT" if sat_result else "REJECT"
    except Exception as exc:
        status = "error"
        result = type(exc).__name__
        logger.exception("SAT benchmark failed for word=%r", word)

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return status, result, elapsed_ms, conversion_ms, solve_ms, stats


def _run_cyk(grammar, word: str) -> tuple[str, str, float, dict[str, int]]:
    start = time.perf_counter()
    status = "ok"
    result = "REJECT"
    stats = _grammar_stats(grammar)

    try:
        word_tokens = [] if not word.strip() else word.split()
        accepts = cyk_accepts(grammar, word_tokens)
        result = "ACCEPT" if accepts else "REJECT"
    except Exception as exc:
        status = "error"
        result = type(exc).__name__
        logger.exception("CYK benchmark failed for word=%r", word)

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return status, result, elapsed_ms, stats


def benchmark_from_grammar_file(
    grammar_file: str,
    min_length: int,
    max_length: int,
    positive_count: int,
    negative_count: int,
    java_jar_path: str,
    sat_solver_name: str,
) -> list[dict[str, str]]:
    grammar_path = Path(grammar_file)
    grammars = parse_grammar_file_to_chomsky(grammar_file)
    java_grammar_path = grammar_path.parent.parent / "output" / "JavaGrammar" / f"{grammar_path.stem}.txt"

    if not java_grammar_path.exists():
        raise FileNotFoundError(f"Java grammar export not found: {java_grammar_path}")

    java_blocks = _split_grammar_blocks(java_grammar_path.read_text(encoding="utf-8", errors="ignore"))
    all_rows: list[dict[str, str]] = []

    for grammar_idx, grammar in enumerate(grammars, start=1):
        if grammar_idx > len(java_blocks):
            logger.warning("Skipping grammar=%s: missing Java grammar block", grammar_idx)
            continue

        temp_grammar_path = _write_java_grammar_block_temp_file(java_blocks[grammar_idx - 1])
        try:
            positive_words = _generate_words_with_java_jar(
                java_grammar_file=str(temp_grammar_path),
                min_length=min_length,
                max_length=max_length,
                target_count=positive_count,
                jar_path=java_jar_path,
                label="positive",
            )
            negative_words = _generate_words_with_java_jar(
                java_grammar_file=str(temp_grammar_path),
                min_length=min_length,
                max_length=max_length,
                target_count=negative_count,
                jar_path=java_jar_path,
                label="negative",
            )
        finally:
            temp_grammar_path.unlink(missing_ok=True)

        cases: list[tuple[str, str]] = [("positive", w) for w in positive_words]
        cases.extend(("negative", w) for w in negative_words)

        logger.info(
            "grammar=%s collected words: positive=%s negative=%s",
            grammar_idx,
            len(positive_words),
            len(negative_words),
        )

        for label, word in cases:
            sat_status, sat_result, sat_ms, sat_conversion_ms, sat_solve_ms, sat_stats = _run_sat_solver(grammar, word, sat_solver_name=sat_solver_name)
            all_rows.append(
                _build_row(
                    solver=f"sat:{sat_solver_name}",
                    grammar_index=grammar_idx,
                    word=word,
                    positive_or_negative=label,
                    status=sat_status,
                    result=sat_result,
                    elapsed_ms=sat_ms,
                    conversion_ms=sat_conversion_ms,
                    solve_ms=sat_solve_ms,
                    stats=sat_stats,
                )
            )

            cyk_status, cyk_result, cyk_ms, cyk_stats = _run_cyk(grammar, word)
            all_rows.append(
                _build_row(
                    solver="cyk",
                    grammar_index=grammar_idx,
                    word=word,
                    positive_or_negative=label,
                    status=cyk_status,
                    result=cyk_result,
                    elapsed_ms=cyk_ms,
                    conversion_ms=0.0,
                    solve_ms=cyk_ms,
                    stats=cyk_stats,
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
                "solver",
                "grammar",
                "word",
                "word_length",
                "positive_or_negative",
                "nonterminal_count",
                "rule_count",
                "status",
                "result",
                "time_ms",
                "time_conversion_ms",
                "time_solve_ms",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, str]]) -> None:
    print("solver,grammar,word_length,positive_or_negative,status,result,time_ms,word")
    for row in rows:
        print(
            f"{row['solver']},{row['grammar']},{row['word_length']},{row['positive_or_negative']},"
            f"{row['status']},{row['result']},{row['time_ms']},{row['word']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark SAT vs CYK membership solvers.")
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
    parser.add_argument(
        "--sat-solver",
        default="m22",
        help="PySAT backend for SAT rows (e.g. m22, g3, g4, mc).",
    )
    args = parser.parse_args()

    if args.min_length < 0 or args.max_length < args.min_length:
        print("Invalid length range. Require 0 <= min-length <= max-length.")
        return 1

    grammar_path = Path(args.grammar_file)
    if not grammar_path.exists():
        print(f"Missing grammar file: {args.grammar_file}")
        return 1

    java_jar = args.java_jar
    if java_jar is None:
        java_jar = str(Path(__file__).resolve().parent / "modules" / "WordGenerator.jar")

    if not Path(java_jar).exists():
        print(f"Missing Java JAR: {java_jar}")
        return 1

    log_file = grammar_path.parent.parent / "results" / grammar_path.stem / f"{grammar_path.stem}_membership_benchmark.log"
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

    logger.info("Membership benchmark started")
    logger.info("Grammar file: %s", grammar_path)
    logger.info("Java generator jar: %s", java_jar)
    logger.info("SAT solver: %s", args.sat_solver)

    try:
        rows = benchmark_from_grammar_file(
            grammar_file=args.grammar_file,
            min_length=args.min_length,
            max_length=args.max_length,
            positive_count=args.positive_count,
            negative_count=args.negative_count,
            java_jar_path=java_jar,
            sat_solver_name=args.sat_solver,
        )
    except Exception:
        logger.exception("Membership benchmark failed")
        return 1

    if not rows:
        print("No benchmark data produced.")
        return 1

    results_dir = grammar_path.parent.parent / "results" / grammar_path.stem
    results_dir.mkdir(parents=True, exist_ok=True)
    output_csv = results_dir / f"{grammar_path.stem}_membership_solver_benchmark_results.csv"

    write_csv(rows, output_csv)
    print_summary(rows)
    print(f"Results saved to: {output_csv}")
    logger.info("Membership benchmark finished successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
