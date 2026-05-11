from __future__ import annotations

import argparse
from pathlib import Path


def _load_plot_dependencies():
    try:
        import matplotlib.pyplot as plt  # type: ignore
        import numpy as np  # type: ignore
        import pandas as pd  # type: ignore
        import seaborn as sns  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "Missing plotting dependencies. Install with: "
            "python -m pip install pandas matplotlib seaborn numpy"
        ) from exc

    return pd, plt, sns, np


def _discover_csvs(results_root: Path) -> list[Path]:
    return sorted(results_root.glob("**/*.csv"))


def _read_csv_if_has_columns(pd, path: Path, required_columns: set[str]):
    try:
        frame = pd.read_csv(path)
    except Exception:
        return None

    if required_columns.issubset(set(frame.columns)):
        frame["source_file"] = str(path)
        return frame

    return None


def _load_sat_dataset(pd, csv_files: list[Path]):
    required = {
        "solver",
        "time_ms",
        "word_length",
        "nonterminal_count",
        "bool_variable_count",
        "clause_count",
    }
    frames = []

    for csv_path in csv_files:
        if "membership" in csv_path.name.lower():
            continue
        frame = _read_csv_if_has_columns(pd, csv_path, required)
        if frame is not None:
            frames.append(frame)

    if not frames:
        return None

    sat_df = pd.concat(frames, ignore_index=True)
    text_columns = {
        "dimacs_file",
        "solver",
        "word",
        "positive_or_negative",
        "status",
        "result",
        "source_file",
    }
    for column in sat_df.columns:
        if column in text_columns:
            continue
        sat_df[column] = pd.to_numeric(sat_df[column], errors="coerce")

    sat_df = sat_df[sat_df["status"].astype(str).str.lower() == "ok"]
    sat_df = sat_df.dropna(subset=["time_ms", "word_length", "nonterminal_count", "bool_variable_count", "clause_count"])
    return sat_df


def _load_membership_dataset(pd, csv_files: list[Path], explicit_path: Path | None):
    required = {
        "solver",
        "time_ms",
        "word_length",
        "nonterminal_count",
        "status",
    }

    if explicit_path is not None:
        frame = _read_csv_if_has_columns(pd, explicit_path, required)
        if frame is None:
            raise SystemExit(f"Membership CSV is missing required columns: {explicit_path}")
        df = frame
    else:
        frames = []
        for csv_path in csv_files:
            if "membership" not in csv_path.name.lower():
                continue
            frame = _read_csv_if_has_columns(pd, csv_path, required)
            if frame is not None:
                frames.append(frame)

        if not frames:
            return None

        df = pd.concat(frames, ignore_index=True)

    df["time_ms"] = pd.to_numeric(df["time_ms"], errors="coerce")
    df["word_length"] = pd.to_numeric(df["word_length"], errors="coerce")
    df["nonterminal_count"] = pd.to_numeric(df["nonterminal_count"], errors="coerce")
    # Convert new timing columns if they exist
    if "time_conversion_ms" in df.columns:
        df["time_conversion_ms"] = pd.to_numeric(df["time_conversion_ms"], errors="coerce")
    else:
        df["time_conversion_ms"] = 0.0
    if "time_solve_ms" in df.columns:
        df["time_solve_ms"] = pd.to_numeric(df["time_solve_ms"], errors="coerce")
    else:
        df["time_solve_ms"] = df["time_ms"]
    
    df = df[df["status"].astype(str).str.lower() == "ok"]
    df = df.dropna(subset=["time_ms", "word_length", "nonterminal_count"])
    return df


def _plot_sat_correlations(sat_df, output_dir: Path, plt, sns):
    corr_cols = list(sat_df.select_dtypes(include="number").columns)
    corr_df = sat_df[corr_cols].corr(numeric_only=True)

    plt.figure(figsize=(max(10, len(corr_cols) * 0.7), max(8, len(corr_cols) * 0.6)))
    sns.heatmap(corr_df, annot=True, cmap="coolwarm", fmt=".2f", square=True, vmin=-1, vmax=1, center=0)
    plt.title("SAT Data Correlation Heatmap")
    plt.tight_layout()
    plt.savefig(output_dir / "01_sat_correlation_heatmap.png", dpi=180)
    plt.close()

    # Separate big_grammar from other grammars
    big_grammar_files = sat_df[sat_df["source_file"].str.contains("big_grammar", case=False, na=False)]
    other_grammars = sat_df[~sat_df["source_file"].str.contains("big_grammar", case=False, na=False)]

    scatter_specs = [
        ("nonterminal_count", "Time vs Nonterminals"),
        ("word_length", "Time vs Word Length"),
        ("bool_variable_count", "Time vs Variables"),
        ("clause_count", "Time vs Clauses"),
    ]

    # Plot 1: Big Grammar
    if not big_grammar_files.empty:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        for axis, (x_col, title) in zip(axes.flatten(), scatter_specs):
            sns.scatterplot(
                data=big_grammar_files,
                x=x_col,
                y="time_ms",
                hue="solver",
                alpha=0.7,
                s=50,
                ax=axis,
                palette="Set2",
            )
            axis.set_title(title)
            axis.set_ylabel("Solve Time (ms)")
            axis.legend(title="Solver", fontsize=8)

        fig.suptitle("SAT Solve Time Relationships (big_grammar)", y=1.00)
        fig.tight_layout()
        fig.savefig(output_dir / "02a_sat_scatter_big_grammar.png", dpi=180, bbox_inches="tight")
        plt.close(fig)

    # Plot 2: Other Grammars
    if not other_grammars.empty:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        for axis, (x_col, title) in zip(axes.flatten(), scatter_specs):
            sns.scatterplot(
                data=other_grammars,
                x=x_col,
                y="time_ms",
                hue="solver",
                alpha=0.7,
                s=50,
                ax=axis,
                palette="husl",
            )
            axis.set_title(title)
            axis.set_ylabel("Solve Time (ms)")
            axis.legend(title="Solver", fontsize=8)

        fig.suptitle("SAT Solve Time Relationships (other grammars)", y=1.00)
        fig.tight_layout()
        fig.savefig(output_dir / "02b_sat_scatter_other_grammars.png", dpi=180, bbox_inches="tight")
        plt.close(fig)


def _plot_sat_solver_comparison(sat_df, output_dir: Path, plt, sns):
    summary = (
        sat_df.groupby("solver", as_index=False)["time_ms"]
        .median()
        .sort_values("time_ms")
    )

    by_length = (
        sat_df.groupby(["solver", "word_length"], as_index=False)["time_ms"]
        .median()
        .sort_values("word_length")
    )

    plt.figure(figsize=(12, 6))
    sns.lineplot(data=by_length, x="word_length", y="time_ms", hue="solver", marker="o")
    plt.title("SAT Solver Median Runtime by Word Length")
    plt.xlabel("Word Length")
    plt.ylabel("Median Solve Time (ms)")
    plt.legend(title="Solver")
    plt.tight_layout()
    plt.savefig(output_dir / "03_sat_solver_by_word_length.png", dpi=180)
    plt.close()

    plt.figure(figsize=(10, 6))
    sns.barplot(data=summary, x="solver", y="time_ms", hue="solver", palette="Blues_r", legend=False)
    plt.title("SAT Solver Median Runtime")
    plt.xlabel("SAT Solver")
    plt.ylabel("Median Solve Time (ms)")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(output_dir / "04_sat_solver_median_runtime.png", dpi=180)
    plt.close()


def _plot_sat_vs_cyk(membership_df, output_dir: Path, plt, sns):
    compare_df = membership_df[membership_df["solver"].str.startswith("sat:") | (membership_df["solver"] == "cyk")].copy()
    if compare_df.empty:
        return

    compare_df["family"] = compare_df["solver"].apply(lambda s: "sat" if str(s).startswith("sat:") else "cyk")

    overall = (
        compare_df.groupby("family", as_index=False)["time_ms"]
        .median()
        .sort_values("time_ms")
    )

    plt.figure(figsize=(8, 6))
    sns.barplot(data=overall, x="family", y="time_ms", hue="family", palette="Set2", legend=False)
    plt.title("CYK vs SAT Median Runtime")
    plt.xlabel("Algorithm")
    plt.ylabel("Median Solve Time (ms)")
    plt.tight_layout()
    plt.savefig(output_dir / "05_cyk_vs_sat_median_runtime.png", dpi=180)
    plt.close()

    by_length = (
        compare_df.groupby(["family", "word_length"], as_index=False)["time_ms"]
        .median()
        .sort_values("word_length")
    )

    plt.figure(figsize=(10, 6))
    sns.lineplot(data=by_length, x="word_length", y="time_ms", hue="family", marker="o", linewidth=2)
    plt.title("CYK vs SAT Median Runtime by Word Length")
    plt.xlabel("Word Length")
    plt.ylabel("Median Solve Time (ms)")
    plt.legend(title="Algorithm")
    plt.tight_layout()
    plt.savefig(output_dir / "06_cyk_vs_sat_by_word_length.png", dpi=180)
    plt.close()


def _plot_time_breakdown(membership_df, output_dir: Path, plt, sns, np):
    """Plot time breakdown: conversion vs solver time by word length"""
    compare_df = membership_df[membership_df["solver"].str.startswith("sat:") | (membership_df["solver"] == "cyk")].copy()
    if compare_df.empty:
        return

    compare_df["family"] = compare_df["solver"].apply(lambda s: "sat" if str(s).startswith("sat:") else "cyk")

    # For SAT: aggregate conversion and solver times
    # For CYK: all time is "solver" time (conversion_ms is 0)
    by_length_family = (
        compare_df.groupby(["family", "word_length"], as_index=False)[["time_conversion_ms", "time_solve_ms"]]
        .median()
        .sort_values("word_length")
    )

    # Create stacked bar chart
    fig, ax = plt.subplots(figsize=(12, 6))

    families = by_length_family["family"].unique()
    word_lengths = sorted(by_length_family["word_length"].unique())

    x = np.arange(len(word_lengths))
    width = 0.35

    for i, family in enumerate(sorted(families)):
        family_data = by_length_family[by_length_family["family"] == family]
        conversion_times = []
        solve_times = []

        for wl in word_lengths:
            row = family_data[family_data["word_length"] == wl]
            if not row.empty:
                conversion_times.append(row["time_conversion_ms"].values[0])
                solve_times.append(row["time_solve_ms"].values[0])
            else:
                conversion_times.append(0)
                solve_times.append(0)

        offset = width * (i - 0.5)
        ax.bar(x + offset, conversion_times, width, label=f"{family} (conversion)", alpha=0.8)
        ax.bar(x + offset, solve_times, width, bottom=conversion_times, label=f"{family} (solve)", alpha=0.8)

    ax.set_xlabel("Word Length")
    ax.set_ylabel("Time (ms)")
    ax.set_title("SAT Conversion vs Solver Time Breakdown by Word Length")
    ax.set_xticks(x)
    ax.set_xticklabels(word_lengths)
    ax.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(output_dir / "07_time_breakdown_conversion_vs_solver.png", dpi=180)
    plt.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate benchmark diagrams for SAT solvers and CYK/SAT comparisons.")
    parser.add_argument(
        "--results-root",
        default="text/results",
        help="Root directory where benchmark CSV files are stored.",
    )
    parser.add_argument(
        "--membership-csv",
        default=None,
        help="Optional explicit membership CSV path (contains cyk and sat:* rows).",
    )
    parser.add_argument(
        "--output-dir",
        default="text/results/plots",
        help="Directory where generated images will be saved.",
    )
    args = parser.parse_args()

    pd, plt, sns, np = _load_plot_dependencies()
    sns.set_theme(style="whitegrid")

    results_root = Path(args.results_root)
    if not results_root.exists():
        raise SystemExit(f"Results root does not exist: {results_root}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_files = _discover_csvs(results_root)
    if not csv_files:
        raise SystemExit(f"No CSV files found under: {results_root}")

    membership_path = Path(args.membership_csv) if args.membership_csv else None

    sat_df = _load_sat_dataset(pd, csv_files)
    membership_df = _load_membership_dataset(pd, csv_files, membership_path)

    if sat_df is None:
        raise SystemExit("Could not find SAT benchmark CSV files with variable/clause columns.")

    _plot_sat_correlations(sat_df, output_dir, plt, sns)
    _plot_sat_solver_comparison(sat_df, output_dir, plt, sns)

    if membership_df is not None:
        _plot_sat_vs_cyk(membership_df, output_dir, plt, sns)
        _plot_time_breakdown(membership_df, output_dir, plt, sns, np)

    generated = sorted(p.name for p in output_dir.glob("*.png"))
    print("Generated diagrams:")
    for name in generated:
        print(f"- {name}")
    print(f"Output directory: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
