# CFG to SAT Toolkit

Author: Jozef Nyitrai, STU Slovakia

This repository is part of my Master thesis.

This repository encodes context-free grammar membership as SAT, writes the resulting instances as DIMACS CNF, solves them with multiple backends, and benchmarks the approach against CYK. It also includes a Java word generator, collected benchmark results, and plots generated from those results.

The bundled Java word generator is included for benchmarking, but it is not my work.

## Repository Goal

The project is built to answer a practical question: how well does a SAT-based membership encoding behave compared with a direct CYK implementation on real grammars and generated words?

The workflow is:

1. Parse a grammar file.
2. Convert the grammar to Chomsky normal form.
3. Encode a tokenized word as SAT.
4. Save the CNF as DIMACS and optionally solve it.
5. Generate benchmark words with the bundled Java generator.
6. Run solver benchmarks and generate plots from the collected CSV files.

The core SAT variable is:

$$
X_{A,i,j} = \text{``nonterminal } A \text{ derives substring } w_i \dots w_j''
$$

The SAT encoding mirrors the CYK recurrence, which is why the repository also includes a direct CYK implementation for comparison.

## Repository Layout

| Path | Purpose |
| --- | --- |
| [src/CFG_2_SAT.py](src/CFG_2_SAT.py) | Main SAT encoder and DIMACS writer |
| [src/modules/parser.py](src/modules/parser.py) | Grammar parsing, CNF conversion, and grammar export |
| [src/modules/CYK.py](src/modules/CYK.py) | Direct CYK membership checker |
| [src/benchmark_sat_solvers.py](src/benchmark_sat_solvers.py) | Benchmarks SAT solver backends on generated DIMACS instances |
| [src/benchmark_membership_solvers.py](src/benchmark_membership_solvers.py) | Benchmarks SAT membership against CYK |
| [src/generate_benchmark_diagrams.py](src/generate_benchmark_diagrams.py) | Builds plots from benchmark CSV files |
| [src/modules/WordGenerator.jar](src/modules/WordGenerator.jar) | Bundled Java word generator used by the benchmark scripts |
| [src/text/input/](src/text/input/) | Sample grammar inputs |
| [src/text/output/](src/text/output/) | Exported Java and CNF grammar text |
| [src/text/dimacs_outputs/](src/text/dimacs_outputs/) | DIMACS CNF output |
| [src/text/results/](src/text/results/) | Benchmark CSV and log output |
| [src/text/results/plots/](src/text/results/plots/) | Generated diagrams |
| [misc/word_generator/Generator_final/](misc/word_generator/Generator_final/) | Maven project used to build the generator JAR |

## Requirements

The project is Python-based and expects:

- Python 3.10 or newer
- Java 11 or newer for the bundled generator JAR
- `python-sat`
- `pycryptosat` for the optional extra SAT backend
- `pandas`, `matplotlib`, and `seaborn` for plot generation

Install everything from the project root:

```powershell
python -m pip install -r requirements.txt
```

The scripts are meant to be run from the `src` directory so their relative imports resolve correctly:

```powershell
cd src
```

## Grammar Format

Grammar files are plain text. A minimal example looks like this:

```text
terminal:
a b c

nonterminal:
S A B C

rules:
S - A B
A - a
B - A C
C - b
C - c

start:
S
```

Rules use `LHS - RHS` syntax. Words are tokenized by spaces, so `a b c` is a three-token word. Epsilon is written as `ε`.

Multiple grammars may live in the same file. Separate grammar blocks with a line containing `---`.

## Main Workflows

### Encode and solve one word

```python
from CFG_2_SAT import CFG_2_SAT
from modules.parser import parse_grammar_file_to_chomsky

grammars = parse_grammar_file_to_chomsky("text/input/g1.txt")
solver = CFG_2_SAT(grammars[0], "a a b", solve=True)

print(solver.dimacs_path)
print(solver.get_stats())
```

This parses the grammar, converts it to CNF, builds the SAT instance, writes the DIMACS file, and solves it immediately.

If you only want the DIMACS file:

```python
from CFG_2_SAT import CFG_2_SAT
from modules.parser import parse_grammar_file_to_chomsky

grammars = parse_grammar_file_to_chomsky("text/input/g2.txt")
solver = CFG_2_SAT(grammars[0], "a b c", solve=False)

print(solver.dimacs_path)
print(solver.get_stats())
```

### Benchmark SAT solvers

`benchmark_sat_solvers.py` generates positive and negative benchmark words with the Java generator, converts each case to DIMACS, and runs several SAT backends. The available PySAT backends depend on your local build; the script targets `g3`, `g4`, `gc3`, `gc4`, `m22`, `mc`, and `mgh`, plus `pycryptosat` when it is installed. If `--java-jar` is omitted, it uses the bundled `src/modules/WordGenerator.jar`.

```powershell
python benchmark_sat_solvers.py text/input/g1.txt --min-length 10 --max-length 20 --positive-count 10 --negative-count 10
```

You can point at a different JAR if needed:

```powershell
python benchmark_sat_solvers.py text/input/g1.txt --min-length 10 --max-length 20 --positive-count 10 --negative-count 10 --java-jar modules/WordGenerator.jar
```

### Benchmark membership against CYK

`benchmark_membership_solvers.py` uses the same generated words, then compares a SAT-based membership check against the direct CYK implementation. It also falls back to the bundled `src/modules/WordGenerator.jar` unless you override `--java-jar`.

```powershell
python benchmark_membership_solvers.py text/input/g1.txt --min-length 10 --max-length 20 --positive-count 10 --negative-count 10 --sat-solver m22
```

### Generate plots from results

`generate_benchmark_diagrams.py` scans the benchmark CSV files under `src/text/results/` and writes diagrams to `src/text/results/plots/`.

```powershell
python generate_benchmark_diagrams.py --results-root text/results --output-dir text/results/plots
```

If you want to force a specific membership CSV, pass `--membership-csv`.

## Outputs

### DIMACS output

Generated DIMACS files are written to:

- `src/text/dimacs_outputs/`
- `src/text/dimacs_outputs/benchmark_runs/<grammar_file_stem>/`

Each DIMACS file includes a short comment header with the grammar name, the word, and the encoding statistics.

### Benchmark CSV and logs

Benchmark runs write results and logs to:

- `src/text/results/<grammar_file_stem>/`

Typical files include the membership summary CSV, the length-range CSVs, and the matching log files produced by each benchmark run.

The SAT benchmark CSV includes solver name, grammar index, word, polarity, DIMACS path, formula size statistics, status, result, and runtime. The membership benchmark CSV includes the SAT and CYK rows for the same generated words.

### Plots

The repository already contains generated diagrams in [src/text/results/plots/](src/text/results/plots/):

- [01_sat_correlation_heatmap.png](src/text/results/plots/01_sat_correlation_heatmap.png)
- [02_sat_time_scatter_grid.png](src/text/results/plots/02_sat_time_scatter_grid.png)
- [03_sat_solver_by_word_length.png](src/text/results/plots/03_sat_solver_by_word_length.png)
- [04_sat_solver_median_runtime.png](src/text/results/plots/04_sat_solver_median_runtime.png)
- [05_cyk_vs_sat_median_runtime.png](src/text/results/plots/05_cyk_vs_sat_median_runtime.png)
- [06_cyk_vs_sat_by_word_length.png](src/text/results/plots/06_cyk_vs_sat_by_word_length.png)

These charts summarize SAT solver timing, solver comparisons by word length, and CYK versus SAT membership timing.

## Notes

- The bundled Java generator expects one grammar per input block. For multi-grammar files, the parser exports separate Java grammar blocks and the benchmark scripts process them one by one.
- The repository includes sample inputs such as `g1.txt`, `g2.txt`, `g3.txt`, `big_grammar.txt`, and `grammars.txt`.
- If `pycryptosat` is missing, the SAT benchmark still runs; the extra solver row is just skipped.
- Start with shorter word lengths before moving to larger benchmark ranges.
- The exported grammar files under `src/text/output/` are useful when you want to inspect exactly what the benchmark scripts are feeding into the generator and the CNF encoder.
