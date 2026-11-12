"""The SpellForge spell language.

A spell file looks like this::

    spell Fireball {
      mana 26
      cooldown 0.9
      desc "A bolt that erupts on impact."

      cast {
        bolt fire speed=34 size=5 power=1.1 {
          on hit {
            burst fire radius=2.6 power=1.5
          }
        }
      }
    }

The compiler is deliberately strict: unknown instructions, elements, parameters
or out of range values are reported with a line and column.  A spell also has
to pay for the magic it uses: the declared ``mana`` may not be lower than the
compiled cost estimate.
"""

from __future__ import annotations

import difflib
import math
import os
from dataclasses import dataclass, field

from .config import ELEMENT_NAMES


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class SpellError(Exception):
    def __init__(self, message: str, line: int = 1, col: int = 1,
                 hint: str | None = None, filename: str | None = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.hint = hint
        self.filename = filename

    def at_file(self, filename: str) -> "SpellError":
        self.filename = filename
        return self

    def __str__(self) -> str:
        where = f"{self.filename}:{self.line}:{self.col}" if self.filename else f"{self.line}:{self.col}"
        txt = f"{where}: {self.message}"
        if self.hint:
            txt += f"\n  hint: {self.hint}"
        return txt


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------
@dataclass
class Token:
    kind: str
    value: object
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.kind!r}, {self.value!r}, {self.line}:{self.col})"


PUNCT = {"{": "lbrace", "}": "rbrace", "=": "equals", ",": "comma"}


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(src)

    def advance(ch: str) -> None:
        nonlocal line, col
        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1

    while i < n:
        ch = src[i]
        if ch in " \t\r":
            advance(ch)
            i += 1
            continue
        if ch == "\n":
            advance(ch)
            i += 1
            continue
        if ch == "#":
            while i < n and src[i] != "\n":
                advance(src[i])
                i += 1
            continue
        if ch == '"':
            start_line, start_col = line, col
            advance(ch)
            i += 1
            chars: list[str] = []
            closed = False
            while i < n:
                c = src[i]
                if c == '"':
                    advance(c)
                    i += 1
                    closed = True
                    break
                if c == "\n":
                    raise SpellError("unterminated string", start_line, start_col)
                if c == "\\" and i + 1 < n:
                    nxt = src[i + 1]
                    esc = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt)
                    if esc is None:
                        raise SpellError(f"unknown escape '\\{nxt}'", line, col)
                    chars.append(esc)
                    advance(c)
                    advance(nxt)
                    i += 2
                    continue
                chars.append(c)
                advance(c)
                i += 1
            if not closed:
                raise SpellError("unterminated string", start_line, start_col)
            tokens.append(Token("string", "".join(chars), start_line, start_col))
            continue
        if ch.isdigit():
            start_line, start_col = line, col
            start = i
            while i < n and (src[i].isdigit() or src[i] == "."):
                if src[i] == "." and (i + 1 >= n or not src[i + 1].isdigit()):
                    raise SpellError("malformed number", line, col)
                advance(src[i])
                i += 1
            text = src[start:i]
            if text.count(".") > 1:
                raise SpellError(f"malformed number '{text}'", start_line, start_col)
            value = float(text) if "." in text else int(text)
            tokens.append(Token("number", value, start_line, start_col))
            continue
        if ch.isalpha() or ch == "_":
            start_line, start_col = line, col
            start = i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                advance(src[i])
                i += 1
            tokens.append(Token("ident", src[start:i], start_line, start_col))
            continue
        if ch in PUNCT:
            tokens.append(Token(PUNCT[ch], ch, line, col))
            advance(ch)
            i += 1
            continue
        raise SpellError(f"unexpected character {ch!r}", line, col)

    tokens.append(Token("eof", "", line, col))
    return tokens


# ---------------------------------------------------------------------------
# Instruction definitions
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Param:
    name: str
    default: float
    minimum: float
    maximum: float
    integer: bool = False


@dataclass(frozen=True)
class InstructionSpec:
    name: str
    summary: str
    takes_element: bool
    params: tuple[Param, ...]
    events: tuple[str, ...] = ()
    material_only: bool = False

    def param(self, name: str) -> Param | None:
        for p in self.params:
            if p.name == name:
                return p
        return None

    def defaults(self) -> dict[str, float]:
        return {p.name: p.default for p in self.params}


def _p(name: str, default: float, lo: float, hi: float, integer: bool = False) -> Param:
    return Param(name, default, lo, hi, integer)


INSTRUCTIONS: dict[str, InstructionSpec] = {
    "bolt": InstructionSpec(
        "bolt", "Launch a projectile that flies toward the cursor.", True,
        (_p("speed", 32, 4, 90), _p("size", 4, 1, 18), _p("power", 1.0, 0.05, 5.0),
         _p("pierce", 0, 0, 12, True), _p("homing", 0, 0, 8), _p("life", 2.5, 0.1, 8),
         _p("offset", 1.0, 0, 24)),
        events=("hit", "expire"),
    ),
    "burst": InstructionSpec(
        "burst", "Detonate an element at the cursor.", True,
        (_p("radius", 2.5, 0.4, 12), _p("power", 1.0, 0.05, 5.0), _p("offset", 0, 0, 30)),
    ),
    "beam": InstructionSpec(
        "beam", "Instant ray that stops at walls.", True,
        (_p("length", 14, 2, 90), _p("width", 1.0, 0.3, 4.0), _p("power", 1.0, 0.05, 5.0),
         _p("offset", 0, 0, 20)),
        events=("hit",),
    ),
    "wall": InstructionSpec(
        "wall", "Raise a wall of material across the aim line.", True,
        (_p("length", 6, 1, 40), _p("height", 2, 1, 10, True), _p("life", 8, 0.5, 30),
         _p("power", 1.0, 0.05, 5.0), _p("offset", 5, 0, 20)),
        material_only=True,
    ),
    "orb": InstructionSpec(
        "orb", "Leave a lingering elemental field.", True,
        (_p("radius", 2.2, 0.4, 10), _p("life", 3.0, 0.2, 20),
         _p("power", 0.8, 0.05, 5.0), _p("offset", 5, 0, 24)),
    ),
    "volley": InstructionSpec(
        "volley", "Fire a fan of projectiles.", True,
        (_p("count", 5, 1, 40, True), _p("spread", 16, 0, 60), _p("power", 0.8, 0.05, 5.0),
         _p("speed", 30, 4, 90), _p("size", 3, 1, 18), _p("offset", 1, 0, 24)),
    ),
    "shield": InstructionSpec(
        "shield", "A personal barrier that blocks hostile projectiles.", True,
        (_p("radius", 2.2, 0.6, 8), _p("life", 6, 0.5, 30), _p("power", 0.8, 0.05, 5.0)),
    ),
    "dash": InstructionSpec(
        "dash", "Surge toward the cursor, leaving an elemental trail.", False,
        (_p("power", 7, 1, 16),),
    ),
    "blink": InstructionSpec(
        "blink", "Teleport a short distance toward the cursor.", False,
        (_p("distance", 10, 1, 40),),
    ),
    "heal": InstructionSpec(
        "heal", "Mend your own wounds.", False,
        (_p("amount", 25, 1, 100),),
    ),
}

INSTRUCTION_NAMES = tuple(INSTRUCTIONS)
EVENT_NAMES = ("hit", "expire")


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------
@dataclass
class Instruction:
    name: str
    line: int
    col: int
    element: str | None = None
    params: dict[str, float] = field(default_factory=dict)
    events: dict[str, list["Instruction"]] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def get(self, key: str) -> float:
        if key == "element":
            raise KeyError("element is not numeric")
        return self.params[key]


@dataclass
class SpellDef:
    name: str
    mana: int
    cooldown: float
    desc: str
    program: list[Instruction]
    cost: int
    path: str = ""
    source: str = ""
    line_count: int = 0
    raw_mana: int = 0

    @property
    def element(self) -> str:
        for ins in self.program:
            if ins.element:
                return ins.element
        return "arcane"


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------
class Parser:
    def __init__(self, tokens: list[Token], source: str = "", filename: str = ""):
        self.tokens = tokens
        self.pos = 0
        self.source = source
        self.filename = filename
        self.instruction_count = 0

    # -- token helpers -----------------------------------------------------
    def peek(self, offset: int = 0) -> Token:
        i = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[i]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def error(self, msg: str, tok: Token | None = None, hint: str | None = None) -> None:
        tok = tok or self.peek()
        raise SpellError(msg, tok.line, tok.col, hint, self.filename or None)

    def expect(self, kind: str, what: str) -> Token:
        tok = self.peek()
        if tok.kind != kind:
            self.error(f"expected {what}, found {self.describe(tok)}", tok)
        return self.advance()

    def expect_ident(self, value: str, what: str | None = None) -> Token:
        tok = self.peek()
        if tok.kind != "ident":
            self.error(f"expected {what or repr(value)}, found {self.describe(tok)}", tok)
        if tok.value != value:
            self.error(f"expected {what or repr(value)}, found {tok.value!r}", tok)
        return self.advance()

    @staticmethod
    def describe(tok: Token) -> str:
        if tok.kind == "eof":
            return "end of file"
        if tok.kind == "number":
            return f"number {tok.value}"
        if tok.kind == "string":
            return "a string"
        return repr(tok.value)

    # -- grammar -----------------------------------------------------------
    def parse(self) -> SpellDef:
        self.expect_ident("spell", "'spell' at the start of the file")
        name_tok = self.peek()
        if name_tok.kind != "ident":
            self.error("expected a spell name (letters, digits, underscore)", name_tok)
        name = str(self.advance().value)
        if not name[0].isalpha() and name[0] != "_":
            self.error("spell name must start with a letter", name_tok)
        self.expect("lbrace", "'{' after the spell name")

        mana: int | None = None
        mana_line = 1
        cooldown = 0.7
        desc = ""
        seen: set[str] = set()
        cast_program: list[Instruction] | None = None

        while True:
            tok = self.peek()
            if tok.kind == "rbrace":
                self.advance()
                break
            if tok.kind == "eof":
                self.error("unexpected end of file; missing '}' for the spell", tok)
            if tok.kind != "ident":
                self.error(f"expected a spell header or 'cast', found {self.describe(tok)}", tok)
            key = str(tok.value)
            if key == "cast":
                if cast_program is not None:
                    self.error("duplicate 'cast' block", tok)
                self.advance()
                self.expect("lbrace", "'{' after 'cast'")
                cast_program = self.parse_block(top_level=True)
                continue
            if key not in ("mana", "cooldown", "desc"):
                self.error(f"unknown spell header '{key}'", tok,
                           "headers are: mana, cooldown, desc, cast")
            if key in seen:
                self.error(f"duplicate header '{key}'", tok)
            seen.add(key)
            self.advance()
            if key == "mana":
                mana_line = tok.line
                value_tok = self.expect("number", "an integer mana cost")
                value = value_tok.value
                if isinstance(value, float) and not value.is_integer():
                    self.error("mana must be a whole number", value_tok)
                mana = int(value)
                if not 1 <= mana <= 300:
                    self.error(f"mana must be between 1 and 300 (got {mana})", value_tok)
            elif key == "cooldown":
                value_tok = self.expect("number", "a cooldown in seconds")
                cooldown = float(value_tok.value)
                if not 0.05 <= cooldown <= 20:
                    self.error(f"cooldown must be between 0.05 and 20 seconds (got {cooldown})", value_tok)
            else:
                value_tok = self.expect("string", "a quoted description")
                desc = str(value_tok.value)
                if len(desc) > 160:
                    self.error("description is too long (max 160 characters)", value_tok)

        if mana is None:
            self.error("missing 'mana' header", self.peek(),
                       "every spell declares its mana cost, e.g. 'mana 20'")
        if cast_program is None:
            self.error("missing 'cast' block", self.peek(),
                       "the cast block contains the instructions of the spell")
        if not cast_program:
            self.error("the cast block is empty", self.peek(),
                       "a spell needs at least one instruction")
        if self.peek().kind != "eof":
            self.error(f"unexpected text after the spell: {self.describe(self.peek())}")

        cost = estimate_program_cost(cast_program)
        if mana < cost:
            raise SpellError(
                f"mana {mana} is too low: this spell costs at least {cost}",
                mana_line, 1,
                f"raise mana to {cost} or reduce the power of the spell",
                self.filename or None,
            )
        return SpellDef(name, mana, cooldown, desc, cast_program, cost,
                        path=self.filename, source=self.source,
                        line_count=self.source.count("\n") + 1)

    def parse_block(self, top_level: bool = False, depth: int = 0) -> list[Instruction]:
        program: list[Instruction] = []
        while True:
            tok = self.peek()
            if tok.kind == "rbrace":
                self.advance()
                return program
            if tok.kind == "eof":
                self.error("unexpected end of file; missing '}'", tok)
            if tok.kind != "ident":
                self.error(f"expected an instruction, found {self.describe(tok)}", tok)
            program.append(self.parse_instruction(depth))
            if len(program) > 24:
                self.error("too many instructions in one block (max 24)", tok)

    def parse_instruction(self, depth: int) -> Instruction:
        tok = self.expect("ident", "an instruction")
        name = str(tok.value)
        spec = INSTRUCTIONS.get(name)
        if spec is None:
            hint = suggestion(name, INSTRUCTION_NAMES)
            self.error(f"unknown instruction '{name}'", tok,
                       f"did you mean '{hint}'?" if hint else "open the spell language reference with F1")
        self.instruction_count += 1
        if self.instruction_count > 60:
            self.error("spell is too complex (max 60 instructions)", tok)

        element: str | None = None
        if spec.takes_element:
            etok = self.peek()
            if etok.kind != "ident":
                self.error(f"'{name}' needs an element, found {self.describe(etok)}", etok,
                           "elements: " + ", ".join(ELEMENT_NAMES))
            value = str(etok.value)
            if value in INSTRUCTIONS:
                self.error(f"'{name}' needs an element before its parameters, found '{value}'", etok)
            if value not in ELEMENT_NAMES:
                hint = suggestion(value, ELEMENT_NAMES)
                self.error(f"unknown element '{value}'", etok,
                           f"did you mean '{hint}'?" if hint else "elements: " + ", ".join(ELEMENT_NAMES))
            element = value
            self.advance()
            if spec.material_only and element not in ("fire", "water", "ice", "earth", "poison"):
                self.error(f"'{name}' needs a material element (fire, water, ice, earth, poison), not '{element}'", etok)
        elif name == "dash":
            # Dash has no mandatory element, but an optional one tints its trail.
            t = self.peek()
            if t.kind == "ident" and t.value in ELEMENT_NAMES:
                element = str(self.advance().value)

        params = spec.defaults()
        seen: set[str] = set()
        while True:
            nt = self.peek()
            if nt.kind != "ident" or self.peek(1).kind != "equals":
                break
            pname = str(nt.value)
            self.advance()
            self.advance()  # '='
            p = spec.param(pname)
            if p is None:
                hint = suggestion(pname, [x.name for x in spec.params])
                self.error(f"unknown parameter '{pname}' for '{name}'", nt,
                           f"did you mean '{hint}'?" if hint else
                           ("parameters: " + ", ".join(x.name for x in spec.params) if spec.params else
                            f"'{name}' takes no parameters"))
            if pname in seen:
                self.error(f"duplicate parameter '{pname}'", nt)
            seen.add(pname)
            value_tok = self.expect("number", f"a number for '{pname}'")
            value = value_tok.value
            if p.integer:
                if isinstance(value, float) and not value.is_integer():
                    self.error(f"'{pname}' must be a whole number", value_tok)
                value = int(value)
            value = float(value)
            if not (p.minimum <= value <= p.maximum):
                lo = _fmt(p.minimum)
                hi = _fmt(p.maximum)
                self.error(f"'{pname}' must be between {lo} and {hi} (got {_fmt(value)})", value_tok)
            params[pname] = value

        # Special case: dash accepts an optional element parameter.
        events: dict[str, list[Instruction]] = {}
        if self.peek().kind == "lbrace":
            self.advance()
            if not spec.events:
                self.error(f"'{name}' does not accept an event block", self.peek(),
                           "only bolt (on hit/on expire) and beam (on hit) react to impacts")
            while True:
                t = self.peek()
                if t.kind == "rbrace":
                    self.advance()
                    break
                if t.kind == "eof":
                    self.error("unexpected end of file inside event block", t)
                self.expect_ident("on", "'on' inside an event block")
                event_tok = self.peek()
                if event_tok.kind != "ident":
                    self.error("expected an event name after 'on'", event_tok)
                event = str(event_tok.value)
                if event not in spec.events:
                    allowed = " or ".join(f"'on {e}'" for e in spec.events)
                    self.error(f"'{name}' does not support 'on {event}'", event_tok,
                               f"allowed here: {allowed}")
                if event in events:
                    self.error(f"duplicate 'on {event}' block", event_tok)
                self.advance()
                self.expect("lbrace", f"'{{' after 'on {event}'")
                if depth >= 1:
                    self.error("event blocks cannot be nested inside other event blocks", event_tok)
                events[event] = self.parse_block(depth=depth + 1)
                if not events[event]:
                    self.error("event block is empty", event_tok)

        return Instruction(name, tok.line, tok.col, element, params, events)


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def suggestion(word: str, options) -> str | None:
    matches = difflib.get_close_matches(word, list(options), n=1, cutoff=0.55)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------
ELEMENT_MULTIPLIER = {
    "fire": 1.00, "water": 0.92, "ice": 1.02, "earth": 1.08, "air": 0.82,
    "lightning": 1.28, "poison": 1.00, "arcane": 1.12, "light": 1.02, "dark": 1.06,
}

# The code language uses the same mana economy as the weave canvas, where a
# small canvas holds 100 mana and the player starts with 1000.  Instruction
# weights are authored in "old" units and scaled here once.
MANA_SCALE = 5


def instruction_cost(ins: Instruction) -> float:
    p = ins.params
    name = ins.name
    if name == "bolt":
        c = 3 + 2.0 * p["power"] + 0.25 * p["speed"] + 0.25 * p["size"] \
            + 0.8 * p["pierce"] + 1.0 * p["homing"] + 0.4 * p["life"]
    elif name == "burst":
        c = 2.5 + 3 * p["power"] + 1.2 * p["radius"]
    elif name == "beam":
        c = 3 + 2.5 * p["power"] + 0.2 * p["length"] + 0.8 * p["width"]
    elif name == "wall":
        c = 2 + 0.35 * p["length"] * p["height"] + 1.0 * p["power"]
    elif name == "orb":
        c = 3 + 2 * p["power"] + 1.2 * p["radius"] + 0.6 * p["life"]
    elif name == "volley":
        c = 2 + 1.1 * p["count"] + 1.5 * p["power"]
    elif name == "shield":
        c = 2.5 + 2 * p["power"] + 1.0 * p["radius"] + 0.5 * p["life"]
    elif name == "dash":
        c = 2 + 1.1 * p["power"]
    elif name == "blink":
        c = 2 + 0.5 * p["distance"]
    elif name == "heal":
        c = 1.5 + 0.22 * p["amount"]
    else:  # pragma: no cover
        c = 5
    if ins.element:
        c *= ELEMENT_MULTIPLIER[ins.element]
    for program in ins.events.values():
        c += 0.6 * _raw_program_cost(program)
    return c


def _raw_program_cost(program: list[Instruction]) -> float:
    return sum(instruction_cost(ins) for ins in program)


def estimate_program_cost(program: list[Instruction]) -> int:
    return int(math.ceil(_raw_program_cost(program) * MANA_SCALE))


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def compile_spell(source: str, filename: str = "") -> SpellDef:
    tokens = tokenize(source)
    return Parser(tokens, source, filename).parse()


def compile_file(path: str) -> SpellDef:
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    spell = compile_spell(source, os.path.basename(path))
    spell.path = path
    return spell


@dataclass
class Spellbook:
    spells: dict[str, SpellDef] = field(default_factory=dict)
    errors: list[SpellError] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)

    def as_list(self) -> list[SpellDef]:
        return sorted(self.spells.values(), key=lambda s: (s.path or s.name))


def load_spellbook(directory: str) -> Spellbook:
    book = Spellbook()
    if not os.path.isdir(directory):
        return book
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".spell"):
            continue
        path = os.path.join(directory, fname)
        try:
            spell = compile_file(path)
            if spell.name in book.spells:
                raise SpellError(f"duplicate spell name '{spell.name}'", 1, 1,
                                 f"already defined in {book.spells[spell.name].path}", fname)
            book.spells[spell.name] = spell
            book.files[spell.name] = path
        except SpellError as exc:
            exc.at_file(fname)
            book.errors.append(exc)
        except OSError as exc:  # pragma: no cover
            book.errors.append(SpellError(f"cannot read file: {exc}", 1, 1, None, fname))
    # Graph-woven spells (prototype) live in the same folder.
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".weave"):
            continue
        path = os.path.join(directory, fname)
        try:
            from .weave import load_weave_spell
            spell = load_weave_spell(path)
            if spell.name in book.spells:
                raise SpellError(f"duplicate spell name '{spell.name}'", 1, 1,
                                 f"already defined in {book.spells[spell.name].path}", fname)
            book.spells[spell.name] = spell
            book.files[spell.name] = path
        except SpellError as exc:
            exc.at_file(fname)
            book.errors.append(exc)
        except Exception as exc:  # pragma: no cover - defensive
            book.errors.append(SpellError(f"cannot load weave: {exc}", 1, 1, None, fname))
    return book
