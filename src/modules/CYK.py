from domain.grammar_types import Grammar


def cyk_accepts(grammar: Grammar, word_tokens: list[str]) -> bool:
    """Return True iff the CNF grammar generates the tokenized word."""
    n = len(word_tokens)

    if n == 0:
        return getattr(grammar, "accepts_epsilon", False)

    # terminal_to_nonterm[a] = {A | A -> a}
    terminal_to_nonterm: dict[str, set[str]] = {}
    # pair_to_nonterm[(B, C)] = {A | A -> BC}
    pair_to_nonterm: dict[tuple[str, str], set[str]] = {}

    for rule in grammar.rules:
        A = rule.nonterminal.value
        if rule.type == "SINGULAR":
            a = rule.terminal.value
            if a not in terminal_to_nonterm:
                terminal_to_nonterm[a] = set()
            terminal_to_nonterm[a].add(A)
        else:
            key = (rule.nonterminal2.value, rule.nonterminal3.value)
            if key not in pair_to_nonterm:
                pair_to_nonterm[key] = set()
            pair_to_nonterm[key].add(A)

    # table[i][j] is set of nonterminals deriving tokens i..j (inclusive)
    table: list[list[set[str]]] = [[set() for _ in range(n)] for _ in range(n)]

    # length 1 spans
    for i in range(n):
        token = word_tokens[i]
        table[i][i] = set(terminal_to_nonterm.get(token, set()))

    # length >= 2 spans
    for span in range(2, n + 1):
        for i in range(0, n - span + 1):
            j = i + span - 1
            cell = table[i][j]

            for k in range(i, j):
                left_set = table[i][k]
                right_set = table[k + 1][j]
                if not left_set or not right_set:
                    continue

                for B in left_set:
                    for C in right_set:
                        cell.update(pair_to_nonterm.get((B, C), set()))

    return grammar.startingSymbol.value in table[0][n - 1]
