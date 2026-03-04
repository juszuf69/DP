# grammar_types.py

class Terminal:
    def __init__(self, value: str):
        self.value = value

class NonTerminal:
    def __init__(self, value: str):
        self.value = value

class Rule:
    def __init__(self, A, B, C=None):
        if C is None:
            self.init_S(A, B)
        else:
            self.init_D(A, B, C)

    def init_S(self, nonterminal: NonTerminal, terminal: Terminal):
        self.type = 'SINGULAR'
        self.nonterminal = nonterminal
        self.terminal = terminal

    def init_D(self, nonterminal: NonTerminal, nonterminal2: NonTerminal, nonterminal3: NonTerminal):
        self.type = 'DOUBLE'
        self.nonterminal = nonterminal
        self.nonterminal2 = nonterminal2
        self.nonterminal3 = nonterminal3

class Grammar:
    def __init__(self, rules: list[Rule], N: list[NonTerminal], T: list[Terminal], S: NonTerminal, accepts_epsilon: bool = False):
        self.rules = rules
        self.NonTerminals = N
        self.Terminals = T
        self.startingSymbol = S
        self.accepts_epsilon = accepts_epsilon