from pysat.formula import CNF
from pysat.solvers import Solver

def generate_variants(lists):
    if not lists:
        return [[]]
    
    result = []
    first = lists[0]
    rest = generate_variants(lists[1:])
    
    for item in first:
        for combination in rest:
            result.append([item] + combination)
    
    return result

class Terminal():
    def __init__(self, value:str):
        self.value = value

class NonTerminal():
    def __init__(self, value:str):
        self.value = value

class Rule():
    def __init__(self, A, B, C=None):
        if C is None:
            self.init_S(A,B)
        else:
            self.init_D(A,B,C)

    def init_S(self, nonterminal:NonTerminal, terminal:Terminal):
        self.type = 'SINGULAR'
        self.nonterminal = nonterminal
        self.terminal = terminal

    def init_D(self, nonterminal:NonTerminal, nonterminal2:NonTerminal, nonterminal3:NonTerminal):
        self.type = 'DOUBLE'
        self.nonterminal = nonterminal
        self.nonterminal2 = nonterminal2
        self.nonterminal3 = nonterminal3
    
    def print(self):
        if self.type == 'SINGULAR':
            print(self.nonterminal.value + ' -> ' + self.terminal.value)
        else:
            print(self.nonterminal.value + ' -> ' + self.nonterminal2.value + self.nonterminal3.value)


class CFG_2_SAT():
    def __init__(self, rules:list[Rule], N:list[NonTerminal], T:list[Terminal], S:NonTerminal, word:str):
        self.rules = rules
        self.NonTerminals = N
        self.Terminals = T
        self.startingSymbol = S
        self.word = word
        self.bools = self.init_bools()
        self.clauses = self.init_clauses()
        self.solve()
        

    def init_bools(self):
        '''
        Initialize a dictionarie of sets, where the keys are this form N,i,j, where i <= j <= len(word), and the values are (boolean_value, name).
        The first value will be used to store the boolean values of whether the nonterminal can generate the substring of the word from index i to index j,
        and the second value will be used to store the value name used in the SAT solver.
        '''
        # initialize a dictionary of sets, where the keys are this form N,i,j, where i <= j <= len(word), and the values are None
        bools = {}
        solver_name = 1
        for nonterminal in self.NonTerminals:
            for i in range(len(self.word)):
                for j in range(i,len(self.word)):
                    bools[nonterminal.value + ',' + str(i) + ',' + str(j)] = (None, solver_name)
                    solver_name += 1
        
        # set table[S,0,n-1] to true, where n is the length of the word (the starting symbol must generate the whole word)
        bools[self.startingSymbol.value + ',0,' + str(len(self.word)-1)] = (True, bools[self.startingSymbol.value + ',0,' + str(len(self.word)-1)][1])

        # if exists a rule A -> a, then set table[A,i,i] to true if word[i] == a
        for rule in self.rules:
            if rule.type == 'SINGULAR':
                for i in range(len(self.word)):
                    if self.word[i] == rule.terminal.value:
                        bools[rule.nonterminal.value + ',' + str(i) + ',' + str(i)] = (True, bools[rule.nonterminal.value + ',' + str(i) + ',' + str(i)][1])
        
        # set all other [i,i] values to false
        for nonterminal in self.NonTerminals:
            for i in range(len(self.word)):
                if bools[nonterminal.value + ',' + str(i) + ',' + str(i)][0] is None:
                    bools[nonterminal.value + ',' + str(i) + ',' + str(i)] = (False, bools[nonterminal.value + ',' + str(i) + ',' + str(i)][1])
        
        # if for nonterminal A, there is no rule A -> BC, then set all [A,i,j] values to false (since A cannot generate any substring of the word)
        for nonterminal in self.NonTerminals:
            has_double_rule = False
            for rule in self.rules:
                if rule.type == 'DOUBLE' and rule.nonterminal.value == nonterminal.value:
                    has_double_rule = True
                    break
            if not has_double_rule:
                for i in range(len(self.word)):
                    for j in range(i+1, len(self.word)):
                        bools[nonterminal.value + ',' + str(i) + ',' + str(j)] = (False, bools[nonterminal.value + ',' + str(i) + ',' + str(j)][1])
        return bools
    
    def init_clauses(self):
        '''
        Initialize a list of clauses, where each clause is a list of integers, and the integers are the solver names of the boolean variables in the bools dictionary.
        The clauses will be used to store the clauses that will be added to the SAT solver.
        '''
        clauses = []
        # add must be true clauses from self.bools (if a variable is set to true, then it must be true in the SAT solver)
        for key in self.bools:
            if self.bools[key][0] == True:
                clauses.append([self.bools[key][1]])
            elif self.bools[key][0] == False:
                clauses.append([-self.bools[key][1]])
        # add clauses for the double rules
        for rule in self.rules:
            if rule.type == 'DOUBLE':
                for i in range(len(self.word)):
                    for j in range(i + 1,len(self.word)):
                        and_clauses = []
                        for k in range(i, j):
                            opt_clause = []
                            opt_clause.append(self.bools[rule.nonterminal2.value + ',' + str(i) + ',' + str(k)][1])
                            opt_clause.append(self.bools[rule.nonterminal3.value + ',' + str(k+1) + ',' + str(j)][1])
                            and_clauses.append(opt_clause)
                        # from x0 => (x1 ^ x3) v (x2 ^ x4) to (-x0 v x1 v x2) ^ (-x0 v x3 v x4)
                        for or_clauses in generate_variants(and_clauses):
                            clauses.append([-self.bools[rule.nonterminal.value + ',' + str(i) + ',' + str(j)][1]] + or_clauses)
                        
        return clauses
    
    def solve(self):
        cnf = CNF(from_clauses=self.clauses)

        with Solver(bootstrap_with=cnf) as solver:
            if solver.solve():
                print('formula is satisfiable, word : ' + self.word + ' is generated by the grammar')
                self.print_derivation(solver.get_model())
            else:
                print('formula is unsatisfiable, word : ' + self.word + ' is not generated by the grammar')
    
    def print_table(self):
        for key in self.bools:
            print(key + ': ' + str(self.bools[key]))
    
    def print_derivation(self, model:list[int]):
        # get ferivation of the result from the model, by checking which variables are set to true in the model, and printing the corresponding nonterminal and substring of the word that it generates
        # start from the starting symbol and the whole word, and then recursively print the derivation for the nonterminals that are set to true in the model
        # from model set bools to true or false
        for key in self.bools:
            if self.bools[key][1] in model:
                self.bools[key] = (True, self.bools[key][1])
            else:
                self.bools[key] = (False, self.bools[key][1])
        
        def print_derivation_helper(nonterminal:NonTerminal, i:int, j:int, indent:str):
            if i > j:
                return
            if self.bools[nonterminal.value + ',' + str(i) + ',' + str(j)][0] == False:
                return
            print(indent + nonterminal.value + ' generates ' + self.word[i:j+1])
            for rule in self.rules:
                if rule.type == 'SINGULAR' and rule.nonterminal.value == nonterminal.value and rule.terminal.value == self.word[i]:
                    print(indent + '- ' + nonterminal.value + ' -> ' + rule.terminal.value)
                    return
                elif rule.type == 'DOUBLE' and rule.nonterminal.value == nonterminal.value:
                    for k in range(i, j):
                        if self.bools[rule.nonterminal2.value + ',' + str(i) + ',' + str(k)][0] == True and self.bools[rule.nonterminal3.value + ',' + str(k+1) + ',' + str(j)][0] == True:
                            print(indent + '- ' + nonterminal.value + ' -> ' + rule.nonterminal2.value + rule.nonterminal3.value)
                            print_derivation_helper(rule.nonterminal2, i, k, indent + '- ')
                            print_derivation_helper(rule.nonterminal3, k+1, j, indent + '- ')
                            return
        print_derivation_helper(self.startingSymbol, 0, len(self.word)-1, '- ')
     

# Grammar = aa(b,c)+
a = Terminal('a')
b = Terminal('b')
c = Terminal('c')
S = NonTerminal('S')
A = NonTerminal('A')
B = NonTerminal('B')
C = NonTerminal('C')
R1 = Rule(S,A,B)
R2 = Rule(A,a)
R3 = Rule(B,A,C)
R4 = Rule(C,C,C)
R5 = Rule(C,b)
R6 = Rule(C,c)
Rules:list[Rule] = []
Rules.append(R1)
Rules.append(R2)
Rules.append(R3)
Rules.append(R4)
Rules.append(R5)
Rules.append(R6)
N:list[NonTerminal] = []
N.append(S)
N.append(A)
N.append(B)
N.append(C)
CFG_2_SAT(Rules, N, [a,b,c], S, 'aabcbc')