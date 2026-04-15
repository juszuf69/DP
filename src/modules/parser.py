# parser.py
from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

from domain.grammar_types import Terminal, NonTerminal, Rule, Grammar

EPS_ALIASES = {"ε"}

# ---------------------------
# Helpers: parsing
# ---------------------------

_SECTION_NAMES = {"terminal", "terminals", "nonterminal", "nonterminals", "rules", "start"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_input_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.exists():
        return candidate

    fallback = _project_root() / "src" / "text" / "input" / path
    if fallback.exists():
        return fallback

    raise FileNotFoundError(f"Input grammar file not found: {path}")


def _export_output_paths(input_path: Path) -> tuple[Path, Path]:
    output_root = _project_root() / "src" / "text" / "output"
    java_dir = output_root / "JavaGrammar"
    chomsky_dir = output_root / "Chomsky"

    filename = input_path.stem + ".txt"
    return java_dir / filename, chomsky_dir / filename


def _rhs_to_text(rhs: List[str]) -> str:
    if len(rhs) == 1 and rhs[0] == "ε":
        return "ε"
    return " ".join(rhs)


def _serialize_raw_cfg(
    terminals: Set[str],
    nonterminals: Set[str],
    start: str,
    productions: Dict[str, List[List[str]]],
) -> str:
    lines: List[str] = []
    lines.append("terminal:")
    lines.append(", ".join(sorted(terminals)))
    lines.append("")
    lines.append("nonterminal:")
    lines.append(", ".join(sorted(nonterminals)))
    lines.append("")
    lines.append("start:")
    lines.append(start)
    lines.append("")
    lines.append("rules:")

    for lhs in sorted(productions.keys()):
        for rhs in productions[lhs]:
            lines.append(f"{lhs} - {_rhs_to_text(rhs)}")

    return "\n".join(lines).strip() + "\n"


def _serialize_java_cfg(
    terminals: Set[str],
    start: str,
    productions: Dict[str, List[List[str]]],
) -> str:
    lines: List[str] = []
    for terminal in sorted(terminals):
        lines.append(f"%token {terminal}")

    lines.append("")
    lines.append(f"%start {start}")
    lines.append("%%")

    ordered_lhs = [start] if start in productions else []
    ordered_lhs.extend([lhs for lhs in productions.keys() if lhs != start])

    for lhs in ordered_lhs:
        rhs_list = productions[lhs]
        if not rhs_list:
            continue

        for idx, rhs in enumerate(rhs_list):
            rhs_text = "" if (len(rhs) == 1 and rhs[0] == "ε") else " ".join(rhs)
            prefix = f"{lhs}: " if idx == 0 else " | "
            lines.append(prefix + rhs_text)

    lines.append("%%")
    return "\n".join(lines).strip() + "\n"


def _serialize_cnf_cfg(
    terminals: Set[str],
    nonterminals: Set[str],
    start: str,
    cnf_productions: Dict[str, Set[Tuple[str, ...]]],
) -> str:
    lines: List[str] = []
    lines.append("terminal:")
    lines.append(", ".join(sorted(terminals)))
    lines.append("")
    lines.append("nonterminal:")
    lines.append(", ".join(sorted(nonterminals)))
    lines.append("")
    lines.append("start:")
    lines.append(start)
    lines.append("")
    lines.append("rules:")

    for lhs in sorted(cnf_productions.keys()):
        for rhs in sorted(cnf_productions[lhs]):
            if len(rhs) == 0:
                rhs_text = "ε"
            else:
                rhs_text = " ".join(rhs)
            lines.append(f"{lhs} - {rhs_text}")

    return "\n".join(lines).strip() + "\n"


def _write_export_files(
    input_path: Path,
    raw_grammars: List[Tuple[Set[str], Set[str], str, Dict[str, List[List[str]]]]],
    cnf_blocks: List[Tuple[Set[str], Set[str], str, Dict[str, Set[Tuple[str, ...]]]]],
) -> None:
    java_output_path, chomsky_output_path = _export_output_paths(input_path)
    java_output_path.parent.mkdir(parents=True, exist_ok=True)
    chomsky_output_path.parent.mkdir(parents=True, exist_ok=True)

    java_blocks: List[str] = []
    for terminals, _nonterminals, start, productions in raw_grammars:
        java_blocks.append(_serialize_java_cfg(terminals, start, productions).rstrip())

    chomsky_blocks: List[str] = []
    for terminals, nonterminals, start, cnf_productions in cnf_blocks:
        chomsky_blocks.append(_serialize_cnf_cfg(terminals, nonterminals, start, cnf_productions).rstrip())

    java_output_path.write_text("\n\n---\n\n".join(java_blocks).strip() + "\n", encoding="utf-8")
    chomsky_output_path.write_text("\n\n---\n\n".join(chomsky_blocks).strip() + "\n", encoding="utf-8")

def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].strip()

def _split_csv(line: str) -> List[str]:
    # Preserve standalone comma as a valid terminal while still supporting comma-separated lists.
    out: List[str] = []
    for chunk in line.split():
        piece = chunk.strip()
        if not piece:
            continue
        if piece == ",":
            out.append(",")
            continue
        if "," in piece:
            out.extend([x for x in piece.split(",") if x])
            continue
        out.append(piece)
    return out

def _split_grammar_blocks(text: str) -> List[str]:
    """
    Split input text into multiple grammar blocks by separator lines like '---'.
    Empty blocks are ignored.
    """
    blocks: List[str] = []
    current: List[str] = []

    for raw in text.splitlines():
        if re.match(r"^\s*---\s*$", raw):
            block = "\n".join(current).strip()
            if block:
                blocks.append(block)
            current = []
            continue
        current.append(raw)

    tail = "\n".join(current).strip()
    if tail:
        blocks.append(tail)

    return blocks

def _read_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {k: [] for k in ["terminal", "nonterminal", "rules", "start"]}
    current: Optional[str] = None

    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue

        m = re.match(r"^\s*([A-Za-z]+)\s*:\s*(.*)$", line)
        if m:
            name = m.group(1).lower()
            payload = m.group(2).strip()
            if name not in _SECTION_NAMES:
                raise ValueError(f"Unknown section '{name}:'")

            if name.startswith("term"):
                current = "terminal"
            elif name.startswith("nonterm"):
                current = "nonterminal"
            else:
                current = name

            if payload:
                sections[current].append(payload)
            continue

        if current is None:
            raise ValueError(f"Line outside any section: {raw}")
        sections[current].append(line)

    return sections

def _tokenize_rhs(rhs_raw: str, nonterminals: Set[str], terminals: Set[str]) -> List[str]:
    """
    Tokenize RHS.
    1) If RHS has spaces -> split by spaces.
    2) If RHS exactly matches one declared terminal or nonterminal -> return it as one token.
    3) Otherwise fallback to greedy tokenization (legacy support).
    """
    rhs_raw = rhs_raw.strip()
    if not rhs_raw:
        raise ValueError("Empty RHS.")

    if rhs_raw in EPS_ALIASES:
        return [rhs_raw]

    if " " in rhs_raw:
        return [tok for tok in rhs_raw.split() if tok]

    # IMPORTANT: whole RHS may itself be one terminal/nonterminal
    if rhs_raw in terminals or rhs_raw in nonterminals:
        return [rhs_raw]

    # Legacy fallback: greedy match longest declared symbol first
    symbols_sorted = sorted(nonterminals | terminals, key=len, reverse=True)
    out: List[str] = []
    i = 0
    while i < len(rhs_raw):
        matched = None
        for sym in symbols_sorted:
            if rhs_raw.startswith(sym, i):
                matched = sym
                break
        if matched:
            out.append(matched)
            i += len(matched)
        else:
            raise ValueError(f"Cannot tokenize RHS '{rhs_raw}' near position {i}")
    return out

def _parse_cfg_text_raw(text: str) -> Tuple[Set[str], Set[str], str, Dict[str, List[List[str]]]]:
    """
    Parse TXT into raw CFG:
      terminals: set[str]
      nonterminals: set[str]
      start: str
      productions: dict[A] = list of rhs lists, each rhs is list[str]
    RHS elements are symbol strings (terminal or nonterminal).
    """
    sections = _read_sections(text)

    terminals_list: List[str] = []
    for l in sections["terminal"]:
        terminals_list.extend(_split_csv(l))
    terminals = set(terminals_list)

    nonterminals_list: List[str] = []
    for l in sections["nonterminal"]:
        nonterminals_list.extend(_split_csv(l))
    nonterminals = set(nonterminals_list)

    if not terminals:
        raise ValueError("Missing/empty terminal section.")
    if not nonterminals:
        raise ValueError("Missing/empty nonterminal section.")

    # start symbol
    if sections["start"]:
        start = sections["start"][0].strip()
    else:
        start = "S" if "S" in nonterminals else nonterminals_list[0]

    if start not in nonterminals:
        raise ValueError(f"Start symbol '{start}' not in declared nonterminals.")

    # rules
    pattern = r'^\s*(<[^>\s]+>|[A-Za-z0-9_áéőúűöüóíľščťžý]+)\s*-\s*(.+?)\s*$'
    productions: Dict[str, List[List[str]]] = {A: [] for A in nonterminals}

    for line in sections["rules"]:
        m = re.match(pattern, line)
        if not m:
            raise ValueError(f"Bad rule syntax: '{line}' (expected: LHS - RHS)")
        lhs, rhs_raw = m.group(1), m.group(2)

        if lhs not in nonterminals:
            raise ValueError(f"LHS '{lhs}' not in declared nonterminals.")

        rhs = _tokenize_rhs(rhs_raw, nonterminals, terminals)

        # epsilon accepted in these forms:
        if len(rhs) == 1 and rhs[0] in EPS_ALIASES:
            productions[lhs].append(["ε"])
        else:
            productions[lhs].append(rhs)

    return terminals, nonterminals, start, productions

def parse_cfg_file_raw_many(path: str) -> List[Tuple[Set[str], Set[str], str, Dict[str, List[List[str]]]]]:
    """
    Parse one file containing one or more CFGs separated by lines containing '---'.
    Returns one raw CFG tuple per grammar block.
    """
    input_path = _resolve_input_path(path)
    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = _split_grammar_blocks(text)
    if not blocks:
        raise ValueError(f"No grammar definitions found in file: {path}")

    out: List[Tuple[Set[str], Set[str], str, Dict[str, List[List[str]]]]] = []
    for i, block in enumerate(blocks):
        try:
            out.append(_parse_cfg_text_raw(block))
        except Exception as exc:
            raise ValueError(f"Failed to parse grammar #{i + 1} in '{path}': {exc}") from exc

    return out

def parse_cfg_file_raw(path: str, grammar_index: int = 0) -> Tuple[Set[str], Set[str], str, Dict[str, List[List[str]]]]:
    """
    Backward-compatible single-grammar parser.
    If file contains multiple grammars separated by '---', select one by index.
    """
    grammars = parse_cfg_file_raw_many(path)
    if grammar_index < 0 or grammar_index >= len(grammars):
        raise IndexError(
            f"grammar_index {grammar_index} out of range for file '{path}' containing {len(grammars)} grammars"
        )
    return grammars[grammar_index]


# ---------------------------
# CNF conversion (CFG -> CNF)
# ---------------------------

def cfg_to_cnf(
    terminals: Set[str],
    nonterminals: Set[str],
    start: str,
    productions: Dict[str, List[List[str]]],
) -> Tuple[Set[str], Set[str], str, Dict[str, Set[Tuple[str, ...]]]]:
    """
    Output CNF grammar as:
      Pcnf[A] = set of rhs tuples
    rhs tuples are:
      (a,) for terminal a
      (B,C) for two nonterminals
      () for epsilon only allowed for start (if language includes epsilon)
    """

    T = set(terminals)
    N = set(nonterminals)

    # normalize productions into set-of-tuples representation
    P: Dict[str, Set[Tuple[str, ...]]] = {A: set() for A in N}
    for A, rhss in productions.items():
        for rhs in rhss:
            if len(rhs) == 1 and rhs[0] == "ε":
                P[A].add(())  # epsilon
            else:
                P[A].add(tuple(rhs))

    # 1) Add new start S0 -> S
    new_start = "S0"
    while new_start in N:
        new_start += "0"
    N.add(new_start)
    P[new_start] = {(start,)}
    start = new_start

    # 2) Remove epsilon productions (keep start->ε if needed)
    nullable: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for A, rhss in P.items():
            if A in nullable:
                continue
            for rhs in rhss:
                if rhs == ():
                    nullable.add(A)
                    changed = True
                    break
                if all(sym in nullable for sym in rhs):
                    nullable.add(A)
                    changed = True
                    break

    newP: Dict[str, Set[Tuple[str, ...]]] = {A: set() for A in N}
    for A, rhss in P.items():
        for rhs in rhss:
            if rhs == ():
                continue
            # drop nullable symbols in all combinations
            positions = [i for i, s in enumerate(rhs) if s in nullable]
            for mask in range(1 << len(positions)):
                drop = {positions[j] for j in range(len(positions)) if (mask >> j) & 1}
                out = tuple(sym for i, sym in enumerate(rhs) if i not in drop)
                if out == ():
                    if A == start:
                        newP[A].add(())
                else:
                    newP[A].add(out)
    P = newP

    # 3) Remove unit productions A -> B
    def unit_closure(A: str) -> Set[str]:
        stack = [A]
        seen = {A}
        while stack:
            X = stack.pop()
            for rhs in P.get(X, set()):
                if len(rhs) == 1 and rhs[0] in N:
                    Y = rhs[0]
                    if Y not in seen:
                        seen.add(Y)
                        stack.append(Y)
        return seen

    unit_map = {A: unit_closure(A) for A in N}
    newP = {A: set() for A in N}
    for A in N:
        for B in unit_map[A]:
            for rhs in P.get(B, set()):
                if len(rhs) == 1 and rhs[0] in N:
                    continue
                newP[A].add(rhs)
    P = newP

    # 4) Remove useless symbols (generating + reachable)
    generating: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for A, rhss in P.items():
            if A in generating:
                continue
            for rhs in rhss:
                if rhs == ():
                    generating.add(A)
                    changed = True
                    break
                ok = True
                for s in rhs:
                    if s in N and s not in generating:
                        ok = False
                        break
                    if s in T:
                        continue
                    if s not in N and s not in T:
                        ok = False
                        break
                if ok:
                    generating.add(A)
                    changed = True
                    break

    reachable: Set[str] = {start}
    stack = [start]
    while stack:
        A = stack.pop()
        for rhs in P.get(A, set()):
            for s in rhs:
                if s in N and s not in reachable:
                    reachable.add(s)
                    stack.append(s)

    N = generating & reachable
    P = {A: {rhs for rhs in rhss if all((s in T) or (s in N) for s in rhs)}
         for A, rhss in P.items() if A in N}

    # 5) Replace terminals in RHS length >= 2 with helper nonterminals
    term_nt: Dict[str, str] = {}

    def get_term_nt(t: str) -> str:
        if t in term_nt:
            return term_nt[t]
        base = f"T_{t}"
        name = base
        k = 0
        while name in N:
            k += 1
            name = f"{base}_{k}"
        term_nt[t] = name
        N.add(name)
        # IMPORTANT: don't modify P while iterating over it; add these later
        return name

    # Snapshot of current productions
    P_items_snapshot = list(P.items())

    newP = {A: set() for A in N}  # N currently contains old NTs only
    pending_term_rules: List[Tuple[str, Tuple[str, ...]]] = []  # (NT, (t,))

    for A, rhss in P_items_snapshot:
        for rhs in rhss:
            if len(rhs) <= 1:
                newP[A].add(rhs)
                continue
            out = []
            for s in rhs:
                if s in T:
                    nt_for_t = get_term_nt(s)
                    out.append(nt_for_t)
                    pending_term_rules.append((nt_for_t, (s,)))
                else:
                    out.append(s)
            newP[A].add(tuple(out))

    # Now add the helper terminal rules safely
    for nt_name, rhs in pending_term_rules:
        if nt_name not in newP:
            newP[nt_name] = set()
        newP[nt_name].add(rhs)

    P = newP

    # 6) Binarize: break length > 2 into binary chain

    def fresh_nt(prefix: str) -> str:
        i = 0
        name = f"{prefix}{i}"
        while name in N:
            i += 1
            name = f"{prefix}{i}"
        N.add(name)
        return name

    P_items_snapshot = list(P.items())

    newP = {A: set() for A in N}
    for A, rhss in P_items_snapshot:
        for rhs in rhss:
            if len(rhs) <= 2:
                newP[A].add(rhs)
            else:
                symbols = list(rhs)
                prev = A
                for i in range(len(symbols) - 2):
                    X = fresh_nt(prefix=f"{A}_BIN_")
                    if X not in newP:
                        newP[X] = set()
                    newP[prev].add((symbols[i], X))
                    prev = X
                newP[prev].add((symbols[-2], symbols[-1]))

    P = newP

    # Final filter: CNF form only
    cnfP: Dict[str, Set[Tuple[str, ...]]] = {}
    for A, rhss in P.items():
        good: Set[Tuple[str, ...]] = set()
        for rhs in rhss:
            if rhs == ():
                if A == start:
                    good.add(rhs)
            elif len(rhs) == 1 and rhs[0] in T:
                good.add(rhs)
            elif len(rhs) == 2 and rhs[0] in N and rhs[1] in N:
                good.add(rhs)
        if good:
            cnfP[A] = good

    return T, N, start, cnfP


# ---------------------------
# Build YOUR Grammar object
# ---------------------------

def build_grammar_objects(
    terminals: Set[str],
    nonterminals: Set[str],
    start: str,
    cnfP: Dict[str, Set[Tuple[str, ...]]],
) -> Grammar:
    T_obj: Dict[str, Terminal] = {t: Terminal(t) for t in terminals}
    N_obj: Dict[str, NonTerminal] = {n: NonTerminal(n) for n in nonterminals}

    rules: List[Rule] = []
    for A, rhss in cnfP.items():
        for rhs in rhss:
            if rhs == ():
                # epsilon rule: we DON'T turn this into a Rule object,
                # because your SAT encoding doesn't represent empty substrings.
                continue
            if len(rhs) == 1:
                a = rhs[0]
                rules.append(Rule(N_obj[A], T_obj[a]))
            else:
                B, C = rhs
                rules.append(Rule(N_obj[A], N_obj[B], N_obj[C]))

    accepts_epsilon = (() in cnfP.get(start, set()))

    N_list = [N_obj[n] for n in sorted(nonterminals)]
    T_list = [T_obj[t] for t in sorted(terminals)]

    return Grammar(rules, N_list, T_list, N_obj[start], accepts_epsilon=accepts_epsilon)


# ---------------------------
# Public function you import
# ---------------------------

def parse_grammar_file_to_chomsky(path: str) -> List[Grammar]:
    """
    Parse all grammars from file and convert each to Chomsky normal form.
    """
    out: List[Grammar] = []
    input_path = _resolve_input_path(path)
    raw_grammars = parse_cfg_file_raw_many(str(input_path))
    cnf_blocks: List[Tuple[Set[str], Set[str], str, Dict[str, Set[Tuple[str, ...]]]]] = []

    source_total = len(raw_grammars)
    for idx, (T, N, start, P) in enumerate(raw_grammars):
        T2, N2, start2, cnfP = cfg_to_cnf(T, N, start, P)
        cnf_blocks.append((T2, N2, start2, cnfP))
        grammar = build_grammar_objects(T2, N2, start2, cnfP)
        grammar.source_path = str(input_path)
        grammar.source_total = source_total
        if source_total > 1:
            grammar.source_index = idx
        out.append(grammar)

    _write_export_files(input_path, raw_grammars, cnf_blocks)
    return out
