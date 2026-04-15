# CFG to SAT Toolkit

## Terminology

- CHNF = Chomsky Normal Form for grammars.
- CNF = Conjunctive Normal Form for SAT formulas.

## What This Project Does

This repository turns context-free grammar membership into SAT, writes the instance as DIMACS CNF, solves it with several SAT backends, and benchmarks the results.

The pipeline is:

1. Read a grammar file.
2. Convert the grammar to CHNF.
3. Encode a tokenized word as a SAT formula.
4. Save the formula as DIMACS CNF.
5. Optionally solve it immediately.
6. Run SAT solver benchmarks on Java-generated positive and negative words.

## Core Algorithm

### Membership problem

Given a grammar $G = (N, T, P, S)$ and a word $w = w_0\,w_1\,\dots\,w_{n-1}$, the code decides whether $w \in L(G)$.

### Why CHNF is needed

The SAT encoding assumes only these production shapes:

- $A \rightarrow a$
- $A \rightarrow BC$
- optionally $S \rightarrow \varepsilon$

So arbitrary CFGs are converted to CHNF first.

### CHNF conversion steps

The parser performs the standard normalization steps:

1. Add a fresh start symbol.
2. Remove epsilon productions, keeping start epsilon when needed.
3. Remove unit productions.
4. Remove useless symbols.
5. Replace terminals inside longer rules with helper nonterminals.
6. Binarize long rules.

### SAT encoding

The main boolean variable is:

$$
X_{A,i,j} = \text{``nonterminal } A \text{ derives substring } w_i \dots w_j''
$$

The encoding adds:

1. A base truth assignment for terminal spans.
2. A true literal for the start symbol over the full span when the word is in the language.
3. Tseitin clauses for binary rules and split points.

The resulting SAT formula is equivalent to the CYK recurrence, which is why the code can cross-check SAT output with CYK.

### Complexity

For word length $n$ and $|N|$ nonterminals, the base table has $|N| \cdot n(n+1)/2$ entries, and the binary rule expansion grows cubically with span length. That is the expected complexity class for CNF grammar membership.

## Main Files

- [src/CFG_2_SAT.py](src/CFG_2_SAT.py): main SAT encoder and DIMACS writer.
- [src/modules/parser.py](src/modules/parser.py): grammar parsing and CHNF conversion.
- [src/modules/CYK.py](src/modules/CYK.py): membership check used for validation.
- [src/benchmark_sat_solvers.py](src/benchmark_sat_solvers.py): benchmark runner and CSV export.
- [src/domain/grammar_types.py](src/domain/grammar_types.py): simple data classes for terminals, nonterminals, rules, and grammars.
- [src/modules/WordGenerator.jar](src/modules/WordGenerator.jar): Java generator used by the benchmark flow.

## Supporting Modules

### [src/domain/grammar_types.py](src/domain/grammar_types.py)

Defines the in-memory grammar model:

- `Terminal`
- `NonTerminal`
- `Rule`
- `Grammar`

### [src/modules/parser.py](src/modules/parser.py)

Responsibilities:

- Parse plain-text grammar files.
- Support multiple grammars in one file, separated by `---`.
- Convert each grammar to CHNF.
- Export two text representations:
  - Java grammar format in `src/text/output/JavaGrammar/`
  - CHNF grammar format in `src/text/output/Chomsky/`

### [src/CFG_2_SAT.py](src/CFG_2_SAT.py)

Responsibilities:

- Build the SAT table for a word.
- Create DIMACS CNF clauses.
- Save the DIMACS file into `src/text/dimacs_outputs/`.
- Optionally solve the formula with PySAT.
- Print a derivation when the instance is satisfiable.

### [src/modules/CYK.py](src/modules/CYK.py)

Implements standard CYK membership checking on the CHNF grammar. The SAT encoder uses it to verify that SAT and CYK agree.

### [src/benchmark_sat_solvers.py](src/benchmark_sat_solvers.py)

Runs the benchmark pipeline:

- loads grammars,
- uses the Java generator to produce positive and negative benchmark words,
- builds DIMACS files,
- runs multiple solvers,
- writes CSV and log output.

## Grammar File Format

Grammar files are plain text. Example:

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

Rules use `LHS - RHS` syntax.

Notes:

- Multiple grammars can live in one file.
- Separate grammar blocks with a line containing `---`.
- Epsilon is written as `ε`.
- Words are tokenized by spaces, for example `a b c`.

## Requirements

The code is Python-based and expects:

- Python 3.10 or newer
- `python-sat`
- `pycryptosat` for the optional extra solver backend
- Java runtime if you want to use the bundled word generator JAR

Install from the project root:

```powershell
python -m pip install -r requirements.txt
```

## Setup

The scripts are written to run from the `src` directory.

```powershell
cd src
```

## Usage


### 1. Generate and solve a DIMACS instance

```python
from CFG_2_SAT import CFG_2_SAT
from modules.parser import parse_grammar_file_to_chomsky

grammars = parse_grammar_file_to_chomsky("text/input/g1.txt")
solver = CFG_2_SAT(grammars[0], "a a b", solve=True)

print(solver.dimacs_path)
print(solver.get_stats())
```

This parses the grammar, converts it to CHNF, builds the SAT encoding, writes the DIMACS file, and solves it immediately.

### 2. Generate DIMACS without solving

```python
from CFG_2_SAT import CFG_2_SAT
from modules.parser import parse_grammar_file_to_chomsky

grammars = parse_grammar_file_to_chomsky("text/input/g2.txt")
solver = CFG_2_SAT(grammars[0], "a b c", solve=False)

print(solver.dimacs_path)
print(solver.get_stats())
```

This is the same encoding path, but it stops after saving the DIMACS file.

### 3. Run the benchmark

The benchmark uses the Java generator for both positive and negative words. If `--java-jar` is omitted, it uses the default JAR in `src/modules/WordGenerator.jar`.

```powershell
python benchmark_sat_solvers.py text/input/g1.txt --min-length 10 --max-length 20 --positive-count 10 --negative-count 10
```

If you want to point at a different JAR:

```powershell
python benchmark_sat_solvers.py text/input/g1.txt --min-length 10 --max-length 20 --positive-count 10 --negative-count 10 --java-jar modules/WordGenerator.jar
```

### 4. Run the benchmark on a multi-grammar file

```powershell
python benchmark_sat_solvers.py text/input/grammars.txt --min-length 10 --max-length 20 --positive-count 10 --negative-count 10
```

The parser splits grammar blocks by `---`, exports each one separately, and the benchmark processes them one by one.

## Output Locations

### DIMACS

Generated files are written under:

- `src/text/dimacs_outputs/`
- `src/text/dimacs_outputs/benchmark_runs/<grammar_file_stem>/`

Each DIMACS file includes a comment header with grammar, word, and stats.

### Benchmark results

Benchmark CSV files and logs are written under:

- `src/text/results/<grammar_file_stem>/`

The CSV contains solver name, grammar index, word, polarity, formula size, status, result, and runtime.

## Practical Notes

1. Start with short lengths before larger benchmark ranges.
2. Use the generated Java grammar exports if you need to inspect what the benchmark is running.
3. Compare SAT and CYK output when debugging a grammar or word.
4. For benchmark runs, the Java generator is the only word source used.
