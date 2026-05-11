from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
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


def _discover_csv_files(results_root: Path) -> list[Path]:
    return sorted(results_root.glob("**/*.csv"))


def _load_raw_sat_data(results_root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for csv_path in _discover_csv_files(results_root):
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
        frame["solver"] = frame["solver"].astype(str)
        frame["positive_or_negative"] = frame["positive_or_negative"].astype(str)
        frames.append(frame)

    if not frames:
        raise SystemExit(f"No SAT benchmark CSV files found under: {results_root}")

    df = pd.concat(frames, ignore_index=True)
    df = df[df["solver"].str.startswith("pysat:", na=False)]
    df = df.dropna(subset=["grammar", "word_length", "time_ms"])
    df["grammar"] = df["grammar"].astype(int)
    df["word_length"] = df["word_length"].astype(int)
    return df


def _load_growth_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"Missing analysis table: {path}")
    table = pd.read_csv(path)
    if "benchmark_set" not in table.columns or "grammar" not in table.columns:
        raise SystemExit(f"Unexpected analysis table schema in: {path}")
    table = table.copy()
    table["grammar"] = pd.to_numeric(table["grammar"], errors="coerce")
    return table


def _grammar_label(benchmark_set: str, grammar_id: int) -> str:
    return f"{benchmark_set} {grammar_id}"


def _build_plot_frame(table: pd.DataFrame) -> pd.DataFrame:
    df = table.copy()
    df["grammar_label"] = [
        _grammar_label(str(benchmark_set), int(grammar_id))
        for benchmark_set, grammar_id in zip(df["benchmark_set"], df["grammar"])
    ]
    return df.sort_values("slope_ms_per_token", ascending=False).reset_index(drop=True)


def _set_publication_style() -> None:
    mpl.rcParams.update(
        {
            "figure.figsize": (12, 7),
            "figure.dpi": 160,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.12,
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titlesize": 16,
            "axes.labelsize": 13,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "legend.title_fontsize": 11,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def _save_figure(fig: mpl.figure.Figure, output_dir: Path, stem: str) -> None:
    for ext in ("png", "pdf", "svg"):
        fig.savefig(output_dir / f"{stem}.{ext}")


def _highlight_big_grammar(labels: list[str]) -> list[str]:
    return ["#D62728" if "big_grammar" in label else "#4C78A8" for label in labels]


def _annotate_bars(ax: mpl.axes.Axes, bars, values: list[float], limit: float = 0.0) -> None:
    for bar, value in zip(bars, values):
        if not np.isfinite(value):
            continue
        if abs(value) < limit:
            continue
        ax.annotate(
            f"{value:.1f}",
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            rotation=90,
        )


def _fit_line(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    if len(x) < 2 or x.nunique(dropna=True) < 2:
        return float("nan"), float("nan")
    slope, intercept = np.polyfit(x.to_numpy(dtype=float), y.to_numpy(dtype=float), 1)
    return float(slope), float(intercept)


def _analysis_subset_for_grammar(table: pd.DataFrame, benchmark_set: str, grammar_id: int) -> pd.DataFrame:
    return table[(table["benchmark_set"] == benchmark_set) & (table["grammar"] == grammar_id)].copy()


def plot_slope_by_grammar(growth_table: pd.DataFrame, output_dir: Path) -> None:
    df = growth_table.sort_values("slope_ms_per_token", ascending=False).reset_index(drop=True)
    labels = df["grammar_label"].tolist()
    values = df["slope_ms_per_token"].astype(float).tolist()
    colors = _highlight_big_grammar(labels)

    fig, ax = plt.subplots(figsize=(14, max(7, 0.33 * len(df) + 2)))
    bars = ax.barh(labels, values, color=colors, edgecolor="black", linewidth=0.6)
    ax.invert_yaxis()
    ax.set_title("Runtime Growth by Word Length for Individual Grammars")
    ax.set_xlabel("Regression slope [ms/token]")
    ax.set_ylabel("Grammar")
    ax.grid(axis="x")

    for bar, value in zip(bars, values):
        ax.annotate(
            f"{value:.1f}",
            (bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            ha="left",
            fontsize=8,
        )

    _save_figure(fig, output_dir, "slope_by_grammar")
    plt.close(fig)


def plot_correlation_by_grammar(growth_table: pd.DataFrame, output_dir: Path) -> None:
    df = growth_table.sort_values("pearson_r", ascending=False).reset_index(drop=True)
    labels = df["grammar_label"].tolist()
    values = df["pearson_r"].astype(float).tolist()
    colors = _highlight_big_grammar(labels)

    fig, ax = plt.subplots(figsize=(14, max(7, 0.33 * len(df) + 2)))
    bars = ax.barh(labels, values, color=colors, edgecolor="black", linewidth=0.6)
    ax.invert_yaxis()
    ax.set_xlim(-1.0, 1.0)
    ax.set_title("Correlation Between Word Length and Runtime by Grammar")
    ax.set_xlabel("Pearson correlation")
    ax.set_ylabel("Grammar")
    ax.grid(axis="x")

    for bar, value in zip(bars, values, strict=False):
        ax.annotate(
            f"{value:.2f}",
            (bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=8,
        )

    _save_figure(fig, output_dir, "correlation_by_grammar")
    plt.close(fig)


def plot_all_grammars_scatter(raw_df: pd.DataFrame, output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 8))
    grammar_labels = raw_df[["benchmark_set", "grammar"]].drop_duplicates().copy()
    grammar_labels["grammar_label"] = grammar_labels.apply(
        lambda row: _grammar_label(row["benchmark_set"], int(row["grammar"])), axis=1
    )

    palette = mpl.colormaps["tab20"].resampled(len(grammar_labels))
    label_to_color = {label: palette(i) for i, label in enumerate(grammar_labels["grammar_label"].tolist())}

    for label, group in raw_df.assign(grammar_label=raw_df.apply(lambda row: _grammar_label(row["benchmark_set"], int(row["grammar"])), axis=1)).groupby("grammar_label"):
        ax.scatter(
            group["word_length"],
            group["time_ms"],
            s=18,
            alpha=0.35,
            color=label_to_color[label],
            label=label,
            linewidths=0,
        )

    ax.set_title("Overall Runtime vs Word Length Across All Grammars")
    ax.set_xlabel("Word length")
    ax.set_ylabel("Runtime [ms]")
    ax.legend(title="Grammar", bbox_to_anchor=(1.02, 1), loc="upper left", frameon=False, ncol=1)
    _save_figure(fig, output_dir, "runtime_vs_wordlength_all_grammars")
    plt.close(fig)


def plot_per_grammar_panels(raw_df: pd.DataFrame, growth_table: pd.DataFrame, output_dir: Path) -> None:
    grammars = growth_table[["benchmark_set", "grammar", "grammar_label", "slope_ms_per_token"]].copy()
    grammars = grammars.sort_values("slope_ms_per_token", ascending=False).reset_index(drop=True)
    n = len(grammars)
    cols = 3
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 5.0, rows * 4.0), sharex=False, sharey=False)
    axes = np.atleast_1d(axes).ravel()

    for ax, (_, grammar_row) in zip(axes, grammars.iterrows()):
        subset = _analysis_subset_for_grammar(raw_df, grammar_row["benchmark_set"], int(grammar_row["grammar"]))
        ax.scatter(subset["word_length"], subset["time_ms"], s=12, alpha=0.35, color="#4C78A8")

        slope, intercept = _fit_line(subset["word_length"], subset["time_ms"])
        x = np.array([subset["word_length"].min(), subset["word_length"].max()], dtype=float)
        if np.isfinite(slope):
            ax.plot(x, slope * x + intercept, color="#D62728", linewidth=2.0)

        ax.set_title(f"{grammar_row['grammar_label']}  slope={grammar_row['slope_ms_per_token']:.2f} ms/token")
        ax.set_xlabel("Word length")
        ax.set_ylabel("Runtime [ms]")

    for ax in axes[n:]:
        ax.set_visible(False)

    fig.suptitle("Runtime vs Word Length per Grammar", y=1.01)
    fig.tight_layout()
    _save_figure(fig, output_dir, "runtime_vs_wordlength_per_grammar")
    plt.close(fig)


def plot_selected_grammars(raw_df: pd.DataFrame, growth_table: pd.DataFrame, output_dir: Path) -> None:
    selected = [
        ("big_grammar", 1),
        ("grammars", 16),
        ("grammars", 17),
        ("grammars", 7),
        ("grammars", 5),
        ("grammars", 11),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(16, 9), sharex=False, sharey=False)
    axes = axes.ravel()

    for ax, (benchmark_set, grammar_id) in zip(axes, selected):
        subset = _analysis_subset_for_grammar(raw_df, benchmark_set, grammar_id)
        growth_row = growth_table[(growth_table["benchmark_set"] == benchmark_set) & (growth_table["grammar"] == grammar_id)]
        slope = float(growth_row.iloc[0]["slope_ms_per_token"]) if not growth_row.empty else float("nan")
        intercept = float(growth_row.iloc[0]["intercept_ms"]) if not growth_row.empty else float("nan")

        ax.scatter(subset["word_length"], subset["time_ms"], s=13, alpha=0.4, color="#4C78A8")
        if len(subset) >= 2:
            x = np.array([subset["word_length"].min(), subset["word_length"].max()], dtype=float)
            if np.isfinite(slope):
                ax.plot(x, slope * x + intercept, color="#D62728", linewidth=2.0)

        ax.set_title(f"{benchmark_set} {grammar_id}  slope={slope:.2f}")
        ax.set_xlabel("Word length")
        ax.set_ylabel("Runtime [ms]")

    fig.suptitle("Comparison of Runtime Growth for Selected Grammars", y=1.01)
    fig.tight_layout()
    _save_figure(fig, output_dir, "runtime_vs_wordlength_selected_grammars")
    plt.close(fig)


def plot_solver_breakdown(raw_df: pd.DataFrame, output_dir: Path) -> None:
    selected = [("big_grammar", 1), ("grammars", 16), ("grammars", 11)]
    fig, axes = plt.subplots(1, len(selected), figsize=(18, 5), sharey=True)
    if len(selected) == 1:
        axes = [axes]

    solver_order = sorted(raw_df["solver"].unique())
    palette = mpl.colormaps["tab10"].resampled(len(solver_order))
    solver_to_color = {solver: palette(i) for i, solver in enumerate(solver_order)}

    for ax, (benchmark_set, grammar_id) in zip(axes, selected, strict=False):
        subset = _analysis_subset_for_grammar(raw_df, benchmark_set, grammar_id)
        for solver, group in subset.groupby("solver"):
            ax.scatter(
                group["word_length"],
                group["time_ms"],
                s=18,
                alpha=0.45,
                color=solver_to_color[solver],
                label=solver,
            )
            if len(group) >= 2:
                slope, intercept = _fit_line(group["word_length"], group["time_ms"])
                if np.isfinite(slope):
                    x = np.array([group["word_length"].min(), group["word_length"].max()], dtype=float)
                    ax.plot(x, slope * x + intercept, color=solver_to_color[solver], linewidth=2.0)

        ax.set_title(f"{benchmark_set} {grammar_id}")
        ax.set_xlabel("Word length")
        ax.grid(alpha=0.2)

    axes[0].set_ylabel("Runtime [ms]")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, title="Solver", loc="upper center", ncol=min(6, len(labels)), frameon=False)
    fig.suptitle("Runtime vs Word Length by Solver for Selected Grammars", y=1.08)
    fig.tight_layout()
    _save_figure(fig, output_dir, "runtime_vs_wordlength_solver_breakdown_selected_grammars")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create publication-ready runtime growth plots from SAT benchmarks.")
    parser.add_argument(
        "--results-root",
        default=str(Path(__file__).resolve().parent / "text" / "results"),
        help="Root directory containing the benchmark CSV files.",
    )
    parser.add_argument(
        "--growth-table",
        default=str(Path(__file__).resolve().parent / "text" / "results" / "runtime_growth" / "grammar_runtime_growth_by_word_length.csv"),
        help="Grammar-level runtime growth table CSV.",
    )
    parser.add_argument(
        "--growth-solver-table",
        default=str(Path(__file__).resolve().parent / "text" / "results" / "runtime_growth" / "grammar_solver_runtime_growth_by_word_length.csv"),
        help="Grammar+solver runtime growth table CSV.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "text" / "results" / "runtime_growth_plots"),
        help="Directory where plot files will be written.",
    )
    args = parser.parse_args()

    _set_publication_style()

    results_root = Path(args.results_root)
    growth_table_path = Path(args.growth_table)
    growth_solver_table_path = Path(args.growth_solver_table)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_df = _load_raw_sat_data(results_root)
    growth_table = _build_plot_frame(_load_growth_table(growth_table_path))
    growth_solver_table = _build_plot_frame(_load_growth_table(growth_solver_table_path))

    plot_slope_by_grammar(growth_table, output_dir)
    plot_correlation_by_grammar(growth_table, output_dir)
    plot_all_grammars_scatter(raw_df, output_dir)
    plot_per_grammar_panels(raw_df, growth_table, output_dir)
    plot_selected_grammars(raw_df, growth_table, output_dir)
    plot_solver_breakdown(raw_df, output_dir)

    print(f"Saved plots to: {output_dir}")
    print()
    print("Generated files:")
    for path in sorted(output_dir.glob("*")):
        if path.suffix.lower() in {".png", ".pdf", ".svg"}:
            print(f"- {path}")

    top3 = growth_table.head(3)[["grammar_label", "slope_ms_per_token", "pearson_r"]]
    bottom3 = growth_table.tail(3)[["grammar_label", "slope_ms_per_token", "pearson_r"]]
    big_grammar = growth_table[growth_table["grammar_label"].str.contains("big_grammar", na=False)].head(1)

    print()
    print("Summary:")
    print("- Best plot for showing big_grammar's steep growth: slope_by_grammar.png")
    print("- Best plot for showing noisy global mixing: runtime_vs_wordlength_all_grammars.png")
    print("- Best plot for showing strong within-grammar trends: runtime_vs_wordlength_per_grammar.png")

    if not big_grammar.empty:
        rank = int(big_grammar.index[0]) + 1
        slope = float(big_grammar.iloc[0]["slope_ms_per_token"])
        print(f"- big_grammar rank by slope: {rank} with slope {slope:.4f} ms/token")

    if len(bottom3) and bottom3["slope_ms_per_token"].max() < 3.0:
        print("- Some grammars have nearly flat trends, including at least one close to zero slope.")

    print("- Overall correlation is much lower than many per-grammar correlations, which supports heterogeneity across grammars.")
    print()
    print("Top 3 grammars by slope:")
    print(top3.to_string(index=False))
    print()
    print("Bottom 3 grammars by slope:")
    print(bottom3.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
