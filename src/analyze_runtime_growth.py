from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {
    "solver",
    "grammar",
    "word_length",
    "time_ms",
    "positive_or_negative",
    "clause_count",
    "bool_variable_count",
}

SAT_SOLVER_PREFIX = "pysat:"


def discover_csv_files(results_root: Path) -> list[Path]:
    return sorted(results_root.glob("**/*.csv"))


def load_sat_benchmark_data(results_root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for csv_path in discover_csv_files(results_root):
        try:
            frame = pd.read_csv(csv_path)
        except Exception:
            continue

        if not REQUIRED_COLUMNS.issubset(frame.columns):
            continue

        frame = frame.copy()
        frame["source_file"] = str(csv_path)
        frame["benchmark_set"] = csv_path.parent.name
        frame["grammar"] = pd.to_numeric(frame["grammar"], errors="coerce")
        frame["word_length"] = pd.to_numeric(frame["word_length"], errors="coerce")
        frame["time_ms"] = pd.to_numeric(frame["time_ms"], errors="coerce")
        frame["clause_count"] = pd.to_numeric(frame["clause_count"], errors="coerce")
        frame["bool_variable_count"] = pd.to_numeric(frame["bool_variable_count"], errors="coerce")
        frame["positive_or_negative"] = frame["positive_or_negative"].astype(str)
        frame["solver"] = frame["solver"].astype(str)

        frames.append(frame)

    if not frames:
        raise SystemExit(f"No SAT benchmark CSV files with required columns were found under: {results_root}")

    df = pd.concat(frames, ignore_index=True)
    df = df[df["solver"].str.startswith(SAT_SOLVER_PREFIX, na=False)]
    df = df[df["time_ms"].notna() & df["word_length"].notna() & df["grammar"].notna()]
    df = df[df["word_length"] >= 0]
    df["grammar"] = df["grammar"].astype(int)
    df["word_length"] = df["word_length"].astype(int)
    return df


def _pearson_correlation(x: pd.Series, y: pd.Series) -> float:
    if len(x) < 2:
        return float("nan")
    if x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
        return float("nan")
    return float(x.corr(y, method="pearson"))


def _linear_fit(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    if len(x) < 2:
        return float("nan"), float("nan")
    if x.nunique(dropna=True) < 2:
        return float("nan"), float("nan")
    slope, intercept = np.polyfit(x.to_numpy(dtype=float), y.to_numpy(dtype=float), 1)
    return float(slope), float(intercept)


def _analyze_groups(df: pd.DataFrame, group_cols: Iterable[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for keys, group in df.groupby(list(group_cols), dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)

        word_length = group["word_length"].dropna()
        time_ms = group["time_ms"].dropna()
        if len(word_length) != len(time_ms):
            aligned = group[["word_length", "time_ms"]].dropna()
            word_length = aligned["word_length"]
            time_ms = aligned["time_ms"]

        slope, intercept = _linear_fit(word_length, time_ms)
        pearson_r = _pearson_correlation(word_length, time_ms)

        row: dict[str, object] = {
            "measurements": int(len(group)),
            "min_word_length": int(word_length.min()) if len(word_length) else np.nan,
            "max_word_length": int(word_length.max()) if len(word_length) else np.nan,
            "mean_time_ms": float(time_ms.mean()) if len(time_ms) else np.nan,
            "median_time_ms": float(time_ms.median()) if len(time_ms) else np.nan,
            "pearson_r": pearson_r,
            "slope_ms_per_token": slope,
            "intercept_ms": intercept,
        }

        for col, value in zip(group_cols, keys, strict=False):
            row[col] = value

        rows.append(row)

    result = pd.DataFrame(rows)
    sort_cols = ["slope_ms_per_token"] + [col for col in group_cols]
    result = result.sort_values(sort_cols, ascending=[False] + [True] * len(group_cols), na_position="last")
    return result.reset_index(drop=True)


def _format_table(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    float_cols = ["mean_time_ms", "median_time_ms", "pearson_r", "slope_ms_per_token", "intercept_ms"]
    for col in float_cols:
        if col in formatted.columns:
            formatted[col] = formatted[col].map(lambda value: f"{value:.4f}" if pd.notna(value) else "NaN")
    return formatted


def _print_summary(grammar_table: pd.DataFrame, all_sat_df: pd.DataFrame) -> None:
    overall_r = _pearson_correlation(all_sat_df["word_length"], all_sat_df["time_ms"])
    print()
    print("Overall SAT correlation (all grammars and all SAT solvers):")
    print(f"  Pearson r = {overall_r:.4f}")

    top_3 = grammar_table.head(3)
    bottom_3 = grammar_table.tail(3)

    print()
    print("Top 3 grammars by slope:")
    print(top_3[["benchmark_set", "grammar", "slope_ms_per_token", "pearson_r"]].to_string(index=False))

    print()
    print("Bottom 3 grammars by slope:")
    print(bottom_3[["benchmark_set", "grammar", "slope_ms_per_token", "pearson_r"]].to_string(index=False))

    big_grammar_rows = grammar_table[grammar_table["benchmark_set"].str.contains("big_grammar", case=False, na=False)]
    if big_grammar_rows.empty:
        print()
        print("big_grammar: not found in the analyzed tables")
    else:
        big_grammar = big_grammar_rows.iloc[0]
        rank = int(big_grammar_rows.index[0]) + 1
        in_top_3 = rank <= 3
        print()
        print(f"big_grammar slope rank: {rank} (top 3: {'yes' if in_top_3 else 'no'})")
        print(f"big_grammar slope: {big_grammar['slope_ms_per_token']:.4f} ms/token")

    slopes = grammar_table["slope_ms_per_token"].dropna()
    if len(slopes) >= 2:
        spread = float(slopes.max() - slopes.min())
        std = float(slopes.std(ddof=0))
        print()
        print("Heterogeneity check:")
        print(f"  slope range = {spread:.4f} ms/token")
        print(f"  slope std   = {std:.4f} ms/token")
        print(
            "  Interpretation: a wide slope spread together with a low overall correlation "
            "supports the idea that heterogeneous grammar structures dilute the global signal."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze SAT benchmark runtime growth by word length.")
    parser.add_argument(
        "--results-root",
        default=str(Path(__file__).resolve().parent / "text" / "results"),
        help="Root directory containing the benchmark CSV files.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "text" / "results" / "runtime_growth"),
        help="Directory where analysis CSV files will be written.",
    )
    args = parser.parse_args()

    results_root = Path(args.results_root)
    if not results_root.exists():
        raise SystemExit(f"Results root does not exist: {results_root}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_sat_benchmark_data(results_root)

    grammar_table = _analyze_groups(df, ["benchmark_set", "grammar"]) 
    grammar_solver_table = _analyze_groups(df, ["benchmark_set", "grammar", "solver"])

    grammar_csv = output_dir / "grammar_runtime_growth_by_word_length.csv"
    grammar_solver_csv = output_dir / "grammar_solver_runtime_growth_by_word_length.csv"

    grammar_table.to_csv(grammar_csv, index=False)
    grammar_solver_table.to_csv(grammar_solver_csv, index=False)

    print(f"Saved grammar-level analysis to: {grammar_csv}")
    print(f"Saved grammar+solver analysis to: {grammar_solver_csv}")

    print()
    print("Grammar-level table (top 10 rows):")
    print(_format_table(grammar_table.head(10)).to_string(index=False))

    print()
    print("Grammar+solver table (top 10 rows):")
    print(_format_table(grammar_solver_table.head(10)).to_string(index=False))

    _print_summary(grammar_table, df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
