#!/usr/bin/env python3
"""minijavac - a tiny compiler for a small subset of Java, for demo purposes.

Pipeline:  source --(lexer)--> tokens --(parser)--> AST --(codegen)--> stack bytecode --(VM)--> output

Supported subset:
  * one class containing static methods (main is the entry point)
  * types: int, boolean, String, void (only used for parsing; values are checked at run time)
  * statements: variable declarations, assignment (=, +=, -=, *=, /=), ++/--, if/else, while,
    for, return, blocks, method calls, System.out.println / System.out.print
  * expressions: + - * / % (32-bit int semantics), comparisons, && || !, string concatenation,
    recursion

Usage:  python3 minijavac.py Program.java [--dump]
"""
import re
import sys


class CompileError(Exception):
    pass


# ----------------------------------------------------------------------------- 1. lexer

TOKEN_RE = re.compile(r"""
    (?P<ws>\s+|//[^\n]*|/\*.*?\*/)
  | (?P<num>\d+)
  | (?P<str>"(?:\\.|[^"\\\n])*")
  | (?P<id>[A-Za-z_]\w*)
  | (?P<op>\+\+|--|\+=|-=|\*=|/=|==|!=|<=|>=|&&|\|\||[-+*/%<>=!(){}\[\];,.])
""", re.VERBOSE | re.DOTALL)

KEYWORDS = {"class", "public", "private", "static", "final", "void", "int", "boolean", "String",
            "if", "else", "while", "for", "return", "true", "false"}


def tokenize(src):
    tokens, pos, line = [], 0, 1
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise CompileError(f"line {line}: unexpected character {src[pos]!r}")
        kind, text = m.lastgroup, m.group()
        if kind == "str":
            tokens.append(("str", bytes(text[1:-1], "utf-8").decode("unicode_escape"), line))
        elif kind == "num":
            tokens.append(("num", int(text), line))
        elif kind == "id":
            tokens.append(("kw" if text in KEYWORDS else "id", text, line))
        elif kind == "op":
            tokens.append(("op", text, line))
        line += text.count("\n")
        pos = m.end()
    tokens.append(("eof", "<end of file>", line))
    return tokens


# ----------------------------------------------------------------------------- 2. parser -> AST
# AST nodes are plain tuples, e.g. ("bin", "+", left, right).

class Parser:
    def __init__(self, tokens):
        self.toks, self.i = tokens, 0

    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def at(self, *texts):
        kind, text, _ = self.peek()
        return kind in ("op", "kw") and text in texts

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, text):
        if not self.at(text):
            kind, got, line = self.peek()
            raise CompileError(f"line {line}: expected '{text}' but found '{got}'")
        return self.next()

    def ident(self):
        kind, text, line = self.next()
        if kind != "id":
            raise CompileError(f"line {line}: expected an identifier but found '{text}'")
        return text

    # program := 'class' ID '{' method* '}'
    def program(self):
        while self.at("public", "final"):
            self.next()
        self.expect("class")
        name = self.ident()
        self.expect("{")
        methods = {}
        while not self.at("}"):
            m = self.method()
            if m["name"] in methods:
                raise CompileError(f"method {m['name']} is already defined")
            methods[m["name"]] = m
        self.expect("}")
        return name, methods

    def type(self):
        kind, text, line = self.next()
        if text not in ("int", "boolean", "String", "void"):
            raise CompileError(f"line {line}: unknown type '{text}'")
        while self.at("["):
            self.next(); self.expect("]")
            text += "[]"
        return text

    def method(self):
        mods = set()
        while self.at("public", "private", "static", "final"):
            mods.add(self.next()[1])
        line = self.peek()[2]
        if "static" not in mods:
            raise CompileError(f"line {line}: only static methods are supported")
        ret = self.type()
        name = self.ident()
        self.expect("(")
        params = []
        while not self.at(")"):
            self.type()
            params.append(self.ident())
            if not self.at(")"):
                self.expect(",")
        self.expect(")")
        return {"name": name, "params": params, "ret": ret, "body": self.block(), "line": line}

    def block(self):
        self.expect("{")
        stmts = []
        while not self.at("}"):
            stmts.append(self.statement())
        self.expect("}")
        return ("block", stmts)

    def statement(self):
        line = self.peek()[2]
        if self.at("{"):
            return self.block()
        if self.at("if"):
            self.next(); self.expect("(")
            cond = self.expr(); self.expect(")")
            then = self.statement()
            other = None
            if self.at("else"):
                self.next()
                other = self.statement()
            return ("if", cond, then, other)
        if self.at("while"):
            self.next(); self.expect("(")
            cond = self.expr(); self.expect(")")
            return ("while", cond, self.statement())
        if self.at("for"):
            self.next(); self.expect("(")
            init = None if self.at(";") else self.simple_statement()
            self.expect(";")
            cond = ("bool", True) if self.at(";") else self.expr()
            self.expect(";")
            update = None if self.at(")") else self.simple_statement()
            self.expect(")")
            # for (init; cond; update) body  ==>  { init; while (cond) { body; update; } }
            body = self.statement()
            loop = ("while", cond, ("block", [body] + ([update] if update else [])))
            return ("block", [init, loop] if init else [loop])
        if self.at("return"):
            self.next()
            value = None if self.at(";") else self.expr()
            self.expect(";")
            return ("return", value, line)
        stmt = self.simple_statement()
        self.expect(";")
        return stmt

    def simple_statement(self):
        """A declaration, assignment, ++/-- or call (no trailing ';')."""
        line = self.peek()[2]
        if self.at("int", "boolean", "String"):
            self.type()
            name = self.ident()
            init = None
            if self.at("="):
                self.next()
                init = self.expr()
            return ("decl", name, init, line)
        e = self.expr()
        if e[0] not in ("assign", "incdec", "call"):
            raise CompileError(f"line {line}: not a statement")
        return ("expr", e)

    # Expressions, lowest to highest precedence.
    def expr(self):
        left = self.binary(0)
        if self.at("=", "+=", "-=", "*=", "/="):
            op, line = self.next()[1], self.peek()[2]
            if left[0] != "var":
                raise CompileError(f"line {line}: can only assign to a variable")
            return ("assign", left[1], op, self.expr())
        return left

    LEVELS = [("||",), ("&&",), ("==", "!="), ("<", "<=", ">", ">="), ("+", "-"), ("*", "/", "%")]

    def binary(self, level):
        if level == len(self.LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.at(*self.LEVELS[level]):
            op = self.next()[1]
            left = ("bin", op, left, self.binary(level + 1))
        return left

    def unary(self):
        if self.at("-", "!"):
            return ("un", self.next()[1], self.unary())
        if self.at("++", "--"):
            op = self.next()[1]
            target = self.unary()
            if target[0] != "var":
                raise CompileError("++/-- needs a variable")
            return ("incdec", target[1], op, True)
        e = self.primary()
        if self.at("++", "--"):
            if e[0] != "var":
                raise CompileError("++/-- needs a variable")
            return ("incdec", e[1], self.next()[1], False)
        return e

    def primary(self):
        kind, text, line = self.next()
        if kind == "num":
            if text > 2**31 - 1:
                raise CompileError(f"line {line}: integer number too large")
            return ("num", text)
        if kind == "str":
            return ("str", text)
        if text in ("true", "false"):
            return ("bool", text == "true")
        if text == "(":
            e = self.expr()
            self.expect(")")
            return e
        if kind == "id":
            name = text
            while self.at("."):              # dotted names like System.out.println
                self.next()
                name += "." + self.ident()
            if self.at("("):
                self.next()
                args = []
                while not self.at(")"):
                    args.append(self.expr())
                    if not self.at(")"):
                        self.expect(",")
                self.expect(")")
                return ("call", name, args, line)
            if "." in name:
                raise CompileError(f"line {line}: field access is not supported: {name}")
            return ("var", name, line)
        raise CompileError(f"line {line}: unexpected '{text}'")


# ----------------------------------------------------------------------------- 3. code generator
# Bytecode for a stack machine. Each instruction is a tuple (opcode, operand?).

BINOPS = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
          "<": "LT", "<=": "LE", ">": "GT", ">=": "GE", "==": "EQ", "!=": "NE"}


class MethodCompiler:
    def __init__(self, method, methods):
        self.method, self.methods = method, methods
        self.code = []
        self.scopes = [{}]
        self.nlocals = 0
        for p in method["params"]:
            self.declare(p, method["line"])

    def emit(self, *ins):
        self.code.append(list(ins))
        return len(self.code) - 1          # index, so jumps can be patched later

    def patch(self, at):
        self.code[at][1] = len(self.code)  # jump target = next instruction

    def declare(self, name, line):
        if any(name in s for s in self.scopes):
            raise CompileError(f"line {line}: variable {name} is already defined")
        self.scopes[-1][name] = self.nlocals
        self.nlocals += 1
        return self.nlocals - 1

    def slot(self, name, line):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        raise CompileError(f"line {line}: cannot find symbol: variable {name}")

    def compile(self):
        self.stmt(self.method["body"])
        self.emit("RET", self.method["ret"] != "void" and "missing")
        return {"code": self.code, "nparams": len(self.method["params"]), "nlocals": self.nlocals}

    # statements
    def stmt(self, s):
        kind = s[0]
        if kind == "block":
            self.scopes.append({})
            for x in s[1]:
                self.stmt(x)
            self.scopes.pop()
        elif kind == "decl":
            _, name, init, line = s
            self.expr(init if init else ("num", 0))
            self.emit("STORE", self.declare(name, line))
        elif kind == "expr":
            self.expr(s[1], keep=False)
        elif kind == "if":
            _, cond, then, other = s
            self.expr(cond)
            jz = self.emit("JZ", None)
            self.stmt(then)
            if other:
                jmp = self.emit("JMP", None)
                self.patch(jz)
                self.stmt(other)
                self.patch(jmp)
            else:
                self.patch(jz)
        elif kind == "while":
            _, cond, body = s
            top = len(self.code)
            self.expr(cond)
            jz = self.emit("JZ", None)
            self.stmt(body)
            self.emit("JMP", top)
            self.patch(jz)
        elif kind == "return":
            _, value, line = s
            is_void = self.method["ret"] == "void"
            if value is not None and is_void:
                raise CompileError(f"line {line}: cannot return a value from a void method")
            if value is None and not is_void:
                raise CompileError(f"line {line}: missing return value")
            if value is not None:
                self.expr(value)
            self.emit("RET", value is not None)

    # expressions; keep=False means the value is discarded
    def expr(self, e, keep=True):
        kind = e[0]
        if kind in ("num", "str", "bool"):
            self.emit("PUSH", e[1])
        elif kind == "var":
            self.emit("LOAD", self.slot(e[1], e[2]))
        elif kind == "un":
            self.expr(e[2])
            self.emit("NEG" if e[1] == "-" else "NOT")
        elif kind == "bin" and e[1] in ("&&", "||"):
            # a && b  ==>  a; DUP; JZ end; POP; b; end:
            # a || b  ==>  a; DUP; JZ rhs; JMP end; rhs: POP; b; end:
            self.expr(e[2])
            self.emit("DUP")
            jz = self.emit("JZ", None)
            if e[1] == "||":
                end = self.emit("JMP", None)
                self.patch(jz)
            self.emit("POP")
            self.expr(e[3])
            self.patch(end if e[1] == "||" else jz)
        elif kind == "bin":
            self.expr(e[2])
            self.expr(e[3])
            self.emit(BINOPS[e[1]])
        elif kind == "assign":
            _, name, op, value = e
            slot = self.slot(name, 0)
            if op != "=":
                self.emit("LOAD", slot)
                self.expr(value)
                self.emit(BINOPS[op[0]])
            else:
                self.expr(value)
            if keep:
                self.emit("DUP")
            self.emit("STORE", slot)
            return
        elif kind == "incdec":
            _, name, op, prefix = e
            slot = self.slot(name, 0)
            self.emit("LOAD", slot)
            if keep and not prefix:
                self.emit("DUP")              # old value is the result
            self.emit("PUSH", 1)
            self.emit("ADD" if op == "++" else "SUB")
            if keep and prefix:
                self.emit("DUP")              # new value is the result
            self.emit("STORE", slot)
            return
        elif kind == "call":
            self.call(e, keep)
            return
        if not keep:
            self.emit("POP")

    def call(self, e, keep):
        _, name, args, line = e
        if name in ("System.out.println", "System.out.print"):
            if len(args) > 1 or (name == "System.out.print" and not args):
                raise CompileError(f"line {line}: wrong number of arguments to {name}")
            for a in args:
                self.expr(a)
            self.emit("PRINTLN" if name.endswith("println") else "PRINT", len(args))
            if keep:
                raise CompileError(f"line {line}: {name} returns void")
            return
        target = self.methods.get(name)
        if target is None:
            raise CompileError(f"line {line}: cannot find symbol: method {name}")
        if len(args) != len(target["params"]):
            raise CompileError(f"line {line}: method {name} expects {len(target['params'])} argument(s), got {len(args)}")
        if keep and target["ret"] == "void":
            raise CompileError(f"line {line}: method {name} returns void")
        for a in args:
            self.expr(a)
        self.emit("CALL", name)
        if not keep and target["ret"] != "void":
            self.emit("POP")


def compile_source(src):
    class_name, methods = Parser(tokenize(src)).program()
    if "main" not in methods:
        raise CompileError(f"class {class_name} has no main method")
    return {name: MethodCompiler(m, methods).compile() for name, m in methods.items()}


# ----------------------------------------------------------------------------- 4. virtual machine

class JavaException(Exception):
    pass


def to_int(x):
    return (x + 2**31) % 2**32 - 2**31  # wrap to 32-bit like Java int


def java_str(v):
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def run(program, out=sys.stdout):
    frame = {"fn": program["main"], "pc": 0, "locals": [None] * program["main"]["nlocals"]}
    calls, stack = [], []
    while True:
        code = frame["fn"]["code"]
        op, *arg = code[frame["pc"]]
        frame["pc"] += 1
        if op == "PUSH":
            stack.append(arg[0])
        elif op == "LOAD":
            stack.append(frame["locals"][arg[0]])
        elif op == "STORE":
            frame["locals"][arg[0]] = stack.pop()
        elif op == "DUP":
            stack.append(stack[-1])
        elif op == "POP":
            stack.pop()
        elif op in ("ADD", "SUB", "MUL", "DIV", "MOD", "LT", "LE", "GT", "GE", "EQ", "NE"):
            b, a = stack.pop(), stack.pop()
            if op == "ADD" and (isinstance(a, str) or isinstance(b, str)):
                r = java_str(a) + java_str(b)
            elif op in ("DIV", "MOD"):
                if b == 0:
                    raise JavaException("java.lang.ArithmeticException: / by zero")
                q = abs(a) // abs(b) * (1 if (a < 0) == (b < 0) else -1)  # truncate toward zero
                r = q if op == "DIV" else a - b * q
            else:
                r = {"ADD": lambda: a + b, "SUB": lambda: a - b, "MUL": lambda: a * b,
                     "LT": lambda: a < b, "LE": lambda: a <= b, "GT": lambda: a > b,
                     "GE": lambda: a >= b, "EQ": lambda: a == b, "NE": lambda: a != b}[op]()
            stack.append(to_int(r) if type(r) is int else r)
        elif op == "NEG":
            stack.append(to_int(-stack.pop()))
        elif op == "NOT":
            stack.append(not stack.pop())
        elif op == "JMP":
            frame["pc"] = arg[0]
        elif op == "JZ":
            if not stack.pop():
                frame["pc"] = arg[0]
        elif op in ("PRINT", "PRINTLN"):
            text = java_str(stack.pop()) if arg[0] else ""
            out.write(text + ("\n" if op == "PRINTLN" else ""))
        elif op == "CALL":
            fn = program[arg[0]]
            n = fn["nparams"]
            args = stack[len(stack) - n:] if n else []
            del stack[len(stack) - n:]
            calls.append(frame)
            if len(calls) > 5000:
                raise JavaException("java.lang.StackOverflowError")
            frame = {"fn": fn, "pc": 0, "locals": args + [None] * (fn["nlocals"] - n)}
        elif op == "RET":
            if arg[0] == "missing":
                raise JavaException("missing return statement")
            if not calls:
                return
            frame = calls.pop()


def dump(program):
    for name, fn in program.items():
        print(f"method {name}  (params={fn['nparams']}, locals={fn['nlocals']})")
        for i, ins in enumerate(fn["code"]):
            print(f"  {i:4}  {ins[0]:<8} {'' if len(ins) == 1 else repr(ins[1])}")
        print()


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as f:
            program = compile_source(f.read())
    except CompileError as e:
        print(f"{argv[1]}: error: {e}", file=sys.stderr)
        return 1
    if "--dump" in argv:
        dump(program)
        return 0
    try:
        run(program)
    except JavaException as e:
        sys.stdout.flush()
        print(f'Exception in thread "main" {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
