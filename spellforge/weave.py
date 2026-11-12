"""Graph-based spell weaving (prototype: fire, water, earth, air).

A weave is a small directed graph.  Nodes are elemental runes, links are mana
relations.  The canvas size sets a mana budget; every rune and every arrow
spends part of it.  ``resolve()`` inspects the topology and compiles the graph
into a normal :class:`SpellDef`, so the rest of the game does not need to know
whether a spell came from text or from the canvas.
"""

from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import dataclass, field

from .spell_lang import Instruction, SpellDef, SpellError

ELEMENTS4 = ("fire", "water", "earth", "air")

BASE_COST = {"fire": 28.0, "water": 26.0, "earth": 34.0, "air": 20.0}
PREFIX = {"fire": "Ember", "water": "Tide", "earth": "Stone", "air": "Gale"}
NOUN = {"fire": "Fire", "water": "Water", "earth": "Earth", "air": "Air"}

NODE_MIN, NODE_MAX = 0.55, 1.60
BEND_MIN, BEND_MAX = -0.90, 0.90

CANVAS = {
    "small": {"w": 560, "h": 420, "budget": 100.0, "max_nodes": 8, "max_links": 10,
              "label": "SMALL", "blurb": "100 mana"},
    "medium": {"w": 700, "h": 500, "budget": 500.0, "max_nodes": 16, "max_links": 24,
               "label": "MEDIUM", "blurb": "500 mana"},
    "large": {"w": 840, "h": 560, "budget": 1000.0, "max_nodes": 28, "max_links": 40,
              "label": "HIGH", "blurb": "1000 mana"},
}


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def node_cost(node: "WeaveNode") -> float:
    """Cost grows with the *area* of a rune, not just its radius."""
    if node.spell:
        return max(10.0, node.spell_mana * (node.size ** 1.3))
    return max(8.0, BASE_COST[node.element] * (node.size ** 1.8))


def node_radius(size: float) -> float:
    """Pixel radius used by the canvas renderer and hit testing."""
    return 14.0 + 9.0 * size


def node_px(node: "WeaveNode", canvas: str) -> tuple[float, float]:
    data = CANVAS[canvas]
    return node.x * data["w"], node.y * data["h"]


def link_length(link: "WeaveLink", nodes: dict[int, "WeaveNode"], canvas: str) -> float:
    a = nodes.get(link.src)
    b = nodes.get(link.dst)
    if a is None or b is None:
        return 0.0
    ax, ay = node_px(a, canvas)
    bx, by = node_px(b, canvas)
    return math.hypot(bx - ax, by - ay)


def link_cost(link: "WeaveLink", nodes: dict[int, "WeaveNode"], canvas: str) -> float:
    """Longer arrows cost more; bending an arrow costs a little extra."""
    length = link_length(link, nodes, canvas)
    return max(4.0, 6.0 + length / 40.0 + abs(link.bend) * 8.0)


def cast_cost(raw: float) -> int:
    """A woven spell casts for 80% of the mana spent drawing it."""
    return max(1, int(math.ceil(raw * 0.80)))


def _instruction_to_dict(ins: Instruction) -> dict:
    return {
        "name": ins.name,
        "element": ins.element,
        "params": {k: float(v) for k, v in ins.params.items()},
        "events": {key: [_instruction_to_dict(child) for child in block]
                   for key, block in ins.events.items()},
        "extra": dict(ins.extra),
    }


def _instruction_from_dict(data: dict) -> Instruction:
    params = {}
    raw_params = data.get("params", {})
    if isinstance(raw_params, dict):
        for key, value in raw_params.items():
            if isinstance(value, (int, float)):
                params[str(key)] = float(value)
    events = {}
    raw_events = data.get("events", {})
    if isinstance(raw_events, dict):
        for key, block in raw_events.items():
            if isinstance(block, list):
                events[str(key)] = [
                    _instruction_from_dict(item) for item in block
                    if isinstance(item, dict)]
    extra = data.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}
    return Instruction(str(data.get("name", "burst")), 1, 1,
                       data.get("element"), params, events, dict(extra))


def _scale_instruction(ins: Instruction, factor: float) -> Instruction:
    """Deep-copy a nested instruction and scale its size/power a little."""
    out = copy.deepcopy(ins)
    for key in ("power", "amount"):
        if key in out.params:
            out.params[key] *= factor
    root = math.sqrt(max(0.4, factor))
    for key in ("radius", "length", "width", "size"):
        if key in out.params:
            out.params[key] *= root
    out.events = {name: [_scale_instruction(child, factor) for child in block]
                  for name, block in out.events.items()}
    return out


@dataclass
class WeaveNode:
    id: int
    element: str
    x: float
    y: float
    size: float = 1.0
    spell: str = ""
    spell_mana: float = 0.0
    spell_program: list[Instruction] = field(default_factory=list)

    def cost(self) -> float:
        return node_cost(self)

    def to_dict(self) -> dict:
        data = {"id": self.id, "element": self.element,
                "x": round(self.x, 5), "y": round(self.y, 5),
                "size": round(self.size, 3)}
        if self.spell:
            data["spell"] = self.spell
            data["spell_mana"] = round(self.spell_mana, 3)
            data["spell_program"] = [_instruction_to_dict(i) for i in self.spell_program]
        return data


@dataclass
class WeaveLink:
    src: int
    dst: int
    bend: float = 0.0

    def to_dict(self) -> dict:
        return {"src": self.src, "dst": self.dst, "bend": round(self.bend, 3)}


@dataclass
class WeaveSpec:
    valid: bool
    name: str = "Weave"
    element: str = "arcane"
    shape: str = "none"
    power: float = 1.0
    radius: float = 2.0
    life: float = 1.0
    cooldown: float = 1.0
    mana: int = 1
    cost: float = 0.0
    desc: str = ""
    extra: dict = field(default_factory=dict)
    reason: str = ""
    cycle_len: int = 0
    nodes_cost: float = 0.0
    links_cost: float = 0.0
    nested: list[tuple[str, list[Instruction], float]] = field(default_factory=list)

    def to_spell(self, path: str = "") -> SpellDef:
        if not self.valid:
            raise SpellError(self.reason or "invalid weave", 1, 1,
                             "open the weave canvas and fix the circuit",
                             os.path.basename(path) if path else None)
        program: list[Instruction] = []
        if self.shape == "nested":
            pass
        elif self.shape in ("vortex", "steam"):
            params = {"power": self.power, "radius": self.radius, "life": self.life}
            if self.shape == "vortex":
                params["spin"] = float(self.extra.get("spin", 1))
                params["pull"] = float(self.extra.get("pull", 1.0))
            program.append(Instruction(
                name="_weave", line=1, col=1, element=self.element,
                params=params, extra={"shape": self.shape}))
        elif self.shape == "bolt":
            program.append(Instruction(
                name="bolt", line=1, col=1, element=self.element,
                params={"speed": 30.0 + self.extra.get("speed", 0.0),
                        "size": self.extra.get("size", 4.0),
                        "power": self.power, "pierce": 0.0, "homing": 0.0,
                        "life": 2.6, "offset": 1.0}))
        elif self.shape == "beam":
            program.append(Instruction(
                name="beam", line=1, col=1, element=self.element,
                params={"length": self.extra.get("length", 12.0),
                        "width": self.extra.get("width", 1.0),
                        "power": self.power, "offset": 0.0}))
        elif self.shape == "volley":
            program.append(Instruction(
                name="volley", line=1, col=1, element=self.element,
                params={"count": float(self.extra.get("count", 5)),
                        "spread": self.extra.get("spread", 18.0),
                        "power": self.power, "speed": 34.0,
                        "size": 3.0, "offset": 1.0}))
        elif self.shape == "wall":
            program.append(Instruction(
                name="wall", line=1, col=1, element=self.element,
                params={"length": self.extra.get("length", 7.0),
                        "height": 2.0, "life": self.life,
                        "power": self.power, "offset": 3.0}))
        else:  # burst, quake, prism
            program.append(Instruction(
                name="burst", line=1, col=1, element=self.element,
                params={"radius": self.radius, "power": self.power, "offset": 0.0}))
        for _name, child_program, child_size in self.nested:
            factor = max(0.55, min(1.9, float(child_size)))
            for ins in child_program:
                program.append(_scale_instruction(ins, factor))
        source = json.dumps({"generated": True, "shape": self.shape,
                             "canvas": self.extra.get("canvas", "medium")})
        raw = max(1, int(math.ceil(self.cost)))
        cast = cast_cost(self.cost)
        desc = self.desc
        if self.nested:
            names = ", ".join(sorted({name for name, _, _ in self.nested}))
            desc = f"{desc} Nested casting: {names}."
        return SpellDef(self.name, cast, self.cooldown,
                        desc, program, cast,
                        path=path, source=source, line_count=1, raw_mana=raw)


@dataclass
class WeaveGraph:
    canvas: str = "medium"
    name: str = ""
    nodes: list[WeaveNode] = field(default_factory=list)
    links: list[WeaveLink] = field(default_factory=list)
    next_id: int = 1

    # -- access ---------------------------------------------------------
    def by_id(self) -> dict[int, WeaveNode]:
        return {n.id: n for n in self.nodes}

    def node(self, nid: int) -> WeaveNode | None:
        for n in self.nodes:
            if n.id == nid:
                return n
        return None

    def add_node(self, element: str, x: float, y: float,
                 size: float = 1.0) -> WeaveNode | None:
        data = CANVAS.get(self.canvas, CANVAS["medium"])
        if element not in ELEMENTS4 or len(self.nodes) >= data["max_nodes"]:
            return None
        node = WeaveNode(self.next_id, element, clamp(x, 0.04, 0.96),
                         clamp(y, 0.04, 0.96), clamp(size, NODE_MIN, NODE_MAX))
        self.next_id += 1
        self.nodes.append(node)
        return node

    def add_spell_node(self, spell: SpellDef, x: float, y: float,
                       size: float = 1.0) -> WeaveNode | None:
        data = CANVAS.get(self.canvas, CANVAS["medium"])
        if len(self.nodes) >= data["max_nodes"]:
            return None
        element = spell.element if spell.element in ELEMENTS4 else "arcane"
        node = WeaveNode(self.next_id, element, clamp(x, 0.04, 0.96),
                         clamp(y, 0.04, 0.96), clamp(size, NODE_MIN, NODE_MAX),
                         spell=spell.name,
                         spell_mana=float(spell.raw_mana or spell.mana),
                         spell_program=copy.deepcopy(spell.program))
        self.next_id += 1
        self.nodes.append(node)
        return node

    def has_spell_nodes(self) -> bool:
        return any(bool(node.spell) for node in self.nodes)

    def remove_node(self, nid: int) -> None:
        self.nodes = [n for n in self.nodes if n.id != nid]
        self.links = [l for l in self.links if l.src != nid and l.dst != nid]

    def add_link(self, src: int, dst: int, bend: float = 0.0) -> WeaveLink | None:
        if src == dst or self.node(src) is None or self.node(dst) is None:
            return None
        data = CANVAS.get(self.canvas, CANVAS["medium"])
        if len(self.links) >= data["max_links"]:
            return None
        for link in self.links:
            if link.src == src and link.dst == dst:
                return link
        link = WeaveLink(src, dst, clamp(bend, BEND_MIN, BEND_MAX))
        self.links.append(link)
        return link

    def remove_link(self, link: WeaveLink) -> None:
        self.links = [l for l in self.links if l is not link]

    # -- cost -----------------------------------------------------------
    def budget(self) -> float:
        return CANVAS.get(self.canvas, CANVAS["medium"])["budget"]

    def cost_parts(self) -> tuple[float, float]:
        nodes = self.by_id()
        nc = sum(n.cost() for n in self.nodes)
        lc = sum(link_cost(l, nodes, self.canvas) for l in self.links)
        return nc, lc

    def spent(self) -> float:
        nc, lc = self.cost_parts()
        return nc + lc

    def over_budget(self) -> float:
        return max(0.0, self.spent() - self.budget())

    # -- validation / resolution ---------------------------------------
    def validate(self) -> str:
        data = CANVAS.get(self.canvas, CANVAS["medium"])
        if not self.nodes:
            return "Place at least one rune or spell node."
        if len(self.nodes) > data["max_nodes"]:
            return f"Too many runes: {len(self.nodes)} / {data['max_nodes']}."
        if len(self.links) > data["max_links"]:
            return f"Too many arrows: {len(self.links)} / {data['max_links']}."
        if self.over_budget() > 0.001:
            return f"Over budget by {self.over_budget():.1f} mana."
        for link in self.links:
            if self.node(link.src) is None or self.node(link.dst) is None:
                return "A relation points at a missing rune."
            if link.src == link.dst:
                return "A rune cannot circulate into itself."
        return ""

    def resolve(self) -> WeaveSpec:
        nc, lc = self.cost_parts()
        spent = nc + lc
        node_mana = nc
        link_mana = lc
        mana = cast_cost(spent)
        nested = [(node.spell, node.spell_program, node.size)
                  for node in self.nodes if node.spell]
        reason = self.validate()
        if reason:
            return WeaveSpec(False, reason=reason, cost=spent,
                             nodes_cost=nc, links_cost=lc, mana=mana)
        nodes = self.by_id()
        n = len(self.nodes)
        cycles = find_cycles(self)
        best = self._best_cycle(cycles, nodes)

        counts = {e: 0 for e in ELEMENTS4}
        for node in self.nodes:
            if node.element in counts:
                counts[node.element] += 1
        if not any(counts.values()):
            counts["air"] = 1
        dominant = max(ELEMENTS4, key=lambda e: (counts[e], BASE_COST[e]))
        used = [e for e in ELEMENTS4 if counts[e] > 0]
        spread_px = self._span(nodes)
        collinear = self._collinear(nodes) and n >= 3
        # Bigger runes contribute more mana and therefore more damage.
        power = clamp(0.7 + node_mana * 0.007 + link_mana * 0.0015 + n * 0.05,
                      0.7, 5.0)
        cooldown = round(clamp(0.45 + spent * 0.008, 0.45, 6.0), 2)
        spin = 1
        shape = "burst"
        name = f"{PREFIX[dominant]} Burst"
        desc = f"A cluster of {n} {NOUN[dominant].lower()} runes detonates at the target."
        radius = clamp(1.8 + n * 0.22 + spent * 0.004, 1.6, 8.0)
        life = 3.0
        extra: dict = {"canvas": self.canvas}

        if n == 1 and self.nodes[0].spell:
            node = self.nodes[0]
            return WeaveSpec(
                True, f"{node.spell} Echo", node.element, "nested", power,
                0.0, 1.0, cooldown, mana, spent,
                f"A single spell node. It releases {node.spell} scaled by the "
                "rune's size.", {"canvas": self.canvas},
                nodes_cost=nc, links_cost=lc, nested=nested)

        if best:
            cycle = best
            clen = len(cycle)
            elems = [nodes[i].element for i in cycle if i in nodes]
            same = len(set(elems)) == 1
            els = set(elems)
            spin = self._cycle_spin(cycle)
            direction = "clockwise" if spin > 0 else "counter-clockwise"

            if same and elems[0] == "air":
                shape = "vortex"
                name = "Tornado"
                radius = clamp(3.5 + 0.5 * clen + spent * 0.012, 3.0, 10.0)
                life = clamp(2.6 + 0.42 * clen + spent * 0.008, 2.0, 8.0)
                power = clamp(1.0 + node_mana * 0.010 + link_mana * 0.003 +
                              clen * 0.10, 0.8, 5.2)
                desc = (f"{clen} Air runes circulate {direction}. A tornado drags "
                        "enemies inward and tears at them.")
                extra.update({"spin": spin, "pull": clamp(
                    0.75 + 0.06 * clen + spent * 0.004, 0.6, 2.2)})
            elif same and elems[0] == "water":
                shape = "vortex"
                name = "Maelstrom"
                radius = clamp(3.2 + 0.45 * clen + spent * 0.010, 2.8, 9.0)
                life = clamp(3.0 + 0.45 * clen + spent * 0.007, 2.2, 8.0)
                power = clamp(0.9 + node_mana * 0.009 + link_mana * 0.0025 +
                              clen * 0.09, 0.8, 5.0)
                desc = (f"{clen} Water runes circulate {direction}. A whirlpool "
                        "drags, soaks and chills everything inside.")
                extra.update({"spin": spin, "pull": clamp(
                    0.85 + 0.07 * clen + spent * 0.004, 0.7, 2.4)})
            elif same and elems[0] == "fire":
                shape = "vortex"
                name = "Firestorm"
                radius = clamp(3.0 + 0.42 * clen + spent * 0.010, 2.6, 9.0)
                life = clamp(2.2 + 0.38 * clen + spent * 0.006, 1.8, 7.0)
                power = clamp(1.0 + node_mana * 0.011 + link_mana * 0.003 +
                              clen * 0.11, 0.9, 5.4)
                desc = (f"{clen} Fire runes circulate {direction}. A firestorm "
                        "spins embers through everything caught inside.")
                extra.update({"spin": spin, "pull": clamp(
                    0.55 + 0.05 * clen + spent * 0.003, 0.5, 1.8)})
            elif same and elems[0] == "earth":
                shape = "burst"
                name = "Quake"
                radius = clamp(2.8 + 0.45 * clen + spent * 0.009, 2.4, 9.0)
                power = clamp(1.2 + node_mana * 0.012 + link_mana * 0.003 +
                              clen * 0.11, 1.0, 5.4)
                desc = (f"{clen} Earth runes resonate in a closed loop. The "
                        "circuit releases a single seismic pulse.")
            elif els == {"fire", "water"}:
                shape = "steam"
                name = "Steam Coil"
                radius = clamp(2.2 + 0.25 * n + spent * 0.007, 1.8, 7.0)
                life = 2.5
                power = clamp(0.9 + node_mana * 0.007 + link_mana * 0.002 +
                              n * 0.07, 0.8, 4.8)
                desc = (f"{clen} Fire and Water runes circulate together. The "
                        "closed loop condenses into a scalding steam vortex.")
            else:
                shape = "burst"
                name = "Prism Coil"
                radius = clamp(2.2 + 0.35 * clen + spent * 0.007, 2.0, 8.0)
                power = clamp(1.0 + node_mana * 0.010 + link_mana * 0.0025 +
                              clen * 0.09, 0.9, 5.2)
                desc = (f"A mixed circulation of {', '.join(NOUN[e] for e in sorted(els))} "
                        "runes. The resonance collapses into a prismatic burst.")
            spec = WeaveSpec(True, name, elems[0] if same else dominant,
                             shape, power, radius, life, cooldown,
                             mana, spent, desc,
                             dict(extra), cycle_len=clen, nodes_cost=nc, links_cost=lc,
                             nested=nested)
            return spec

        # No closed loop: read the graph as a line, cluster or pair.
        if collinear and n >= 3:
            if dominant == "earth":
                span = clamp(spread_px / 6.0 * 0.75 + n * 0.7, 4.0, 30.0)
                spec = WeaveSpec(True, "Stone Wall", "earth", "wall", power,
                                 0.0, clamp(6.0 + spent * 0.09, 5.0, 22.0),
                                 cooldown, mana, spent,
                                 "A line of Earth runes raises a barricade of stone.",
                                 {"length": span, "canvas": self.canvas},
                                 nodes_cost=nc, links_cost=lc, nested=nested)
                return spec
            shape = "beam"
            name = f"{PREFIX[dominant]} Lance"
            length = clamp(spread_px / 6.0 * 0.62 + n * 1.0, 4.0, 30.0)
            desc = (f"{n} {NOUN[dominant]} runes line up. The circuit fires a "
                    f"focused lance of {dominant}.")
            return WeaveSpec(True, name, dominant, shape, power, 0.0, 1.0,
                             cooldown, mana, spent, desc,
                             {"length": length, "width": clamp(0.9 + spent * 0.012, 0.8, 2.4),
                              "canvas": self.canvas}, nodes_cost=nc, links_cost=lc,
                             nested=nested)

        if n == 1:
            node = self.nodes[0]
            name = f"{PREFIX[node.element]} Burst"
            desc = (f"A single {NOUN[node.element]} rune. It detonates at the "
                    "cursor when the weave is cast.")
            return WeaveSpec(True, name, node.element, "burst", power, radius,
                             life, cooldown, mana, spent,
                             desc, {"canvas": self.canvas}, nodes_cost=nc, links_cost=lc,
                             nested=nested)

        if n == 2 and len(self.links) >= 1:
            name = f"{PREFIX[dominant]} Bolt"
            desc = ("Two runes exchange mana. The circuit launches a bolt of "
                    f"{dominant} toward the cursor.")
            return WeaveSpec(True, name, dominant, "bolt", power, 0.0, 2.6,
                             cooldown, mana, spent, desc,
                             {"speed": clamp(spent * 0.25, 0.0, 22.0),
                              "size": clamp(3.0 + n * 0.5, 3.0, 8.0),
                              "canvas": self.canvas}, nodes_cost=nc, links_cost=lc,
                             nested=nested)

        if len(used) > 1 and counts["fire"] > 0 and counts["water"] > 0:
            shape = "steam"
            name = "Steam Veil"
            radius = clamp(2.0 + n * 0.20 + spent * 0.015, 1.8, 5.0)
            desc = ("Fire and water runes meet without a loop. The reaction "
                    "releases a scalding cloud of steam.")
            return WeaveSpec(True, name, "water", shape, power, radius, 2.4,
                             cooldown, mana, spent, desc,
                             {"canvas": self.canvas}, nodes_cost=nc, links_cost=lc,
                             nested=nested)

        if len(used) == 1 and n >= 4:
            name = f"{PREFIX[dominant]} Fan"
            desc = f"A fan of {n} {NOUN[dominant]} runes fires a spread of shards."
            return WeaveSpec(True, name, dominant, "volley", power * 0.8, 0.0, 1.9,
                             cooldown, mana, spent, desc,
                             {"count": float(min(9, n)), "spread": clamp(12 + n * 2, 14, 40),
                              "canvas": self.canvas}, nodes_cost=nc, links_cost=lc,
                             nested=nested)

        if len(used) > 1:
            name = "Fusion Burst"
            desc = ("A mixed cluster of runes collapses into a single "
                    f"{dominant} detonation.")
        return WeaveSpec(True, name, dominant, "burst", power, radius, life,
                         cooldown, mana, spent, desc,
                         {"canvas": self.canvas}, nodes_cost=nc, links_cost=lc,
                         nested=nested)

    # -- geometry helpers ----------------------------------------------
    def _span(self, nodes: dict[int, WeaveNode]) -> float:
        pts = [node_px(n, self.canvas) for n in nodes.values()]
        best = 0.0
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                best = max(best, math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]))
        return best

    def _collinear(self, nodes: dict[int, WeaveNode]) -> bool:
        pts = [node_px(n, self.canvas) for n in nodes.values()]
        if len(pts) < 3:
            return True
        p0, p1 = pts[0], pts[-1]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        line = math.hypot(dx, dy)
        if line < 1:
            return False
        dev = 0.0
        for x, y in pts[1:-1]:
            dev = max(dev, abs(dy * (x - p0[0]) - dx * (y - p0[1])) / line)
        limit = max(12.0, min(CANVAS[self.canvas]["w"], CANVAS[self.canvas]["h"]) * 0.035)
        return dev <= limit

    def _best_cycle(self, cycles: list[list[int]], nodes: dict[int, WeaveNode]) -> list[int] | None:
        if not cycles:
            return None
        return max(cycles, key=lambda c: (sum(nodes[i].cost() for i in c if i in nodes), len(c)))

    def _cycle_spin(self, cycle: list[int]) -> int:
        """Screen-space winding: +1 clockwise, -1 counter-clockwise."""
        pts: list[tuple[float, float]] = []
        for nid in cycle:
            node = self.node(nid)
            if node is not None:
                pts.append(node_px(node, self.canvas))
        if len(pts) < 3:
            return 1
        area = 0.0
        for i, (x1, y1) in enumerate(pts):
            x2, y2 = pts[(i + 1) % len(pts)]
            area += x1 * y2 - x2 * y1
        return 1 if area >= 0 else -1

    # -- persistence ----------------------------------------------------
    def to_dict(self, name: str | None = None) -> dict:
        return {
            "version": 1,
            "kind": "weave",
            "name": name or self.name or "Weave",
            "canvas": self.canvas,
            "nodes": [n.to_dict() for n in self.nodes],
            "links": [l.to_dict() for l in self.links],
        }


def find_cycles(graph: WeaveGraph, max_len: int = 8, cap: int = 48) -> list[list[int]]:
    adj: dict[int, list[int]] = {}
    for link in graph.links:
        adj.setdefault(link.src, []).append(link.dst)
    cycles: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()

    def dfs(start: int, current: int, path: list[int], used: set[int]) -> None:
        if len(cycles) >= cap:
            return
        for nxt in adj.get(current, []):
            if nxt == start and len(path) >= 3:
                key = tuple(sorted(path))
                if key not in seen:
                    seen.add(key)
                    cycles.append(list(path))
                continue
            if nxt in used or len(path) >= max_len:
                continue
            used.add(nxt)
            path.append(nxt)
            dfs(start, nxt, path, used)
            path.pop()
            used.remove(nxt)

    for node in graph.nodes:
        dfs(node.id, node.id, [node.id], {node.id})
    return cycles


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def load_weave(path: str) -> WeaveGraph:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise SpellError(f"cannot read weave: {exc}", 1, 1, None, os.path.basename(path))
    except json.JSONDecodeError as exc:
        raise SpellError(f"broken weave file: {exc.msg}", exc.lineno, exc.colno,
                         "delete or repair the file", os.path.basename(path))
    return graph_from_dict(data, os.path.basename(path))


def graph_from_dict(data: dict, filename: str = "") -> WeaveGraph:
    if not isinstance(data, dict):
        raise SpellError("weave file must contain a JSON object", 1, 1, None, filename)
    canvas = str(data.get("canvas", "medium"))
    if canvas not in CANVAS:
        raise SpellError(f"unknown canvas size '{canvas}'", 1, 1,
                         "canvas must be small, medium or large", filename)
    graph = WeaveGraph(canvas=canvas, name=str(data.get("name", "")))
    raw_nodes = data.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise SpellError("'nodes' must be a list", 1, 1, None, filename)
    used_ids: set[int] = set()
    for i, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            raise SpellError(f"node {i + 1} is not an object", 1, 1, None, filename)
        try:
            nid = int(raw["id"])
            element = str(raw["element"])
            x = float(raw["x"])
            y = float(raw["y"])
            size = float(raw.get("size", 1.0))
            spell = str(raw.get("spell", ""))
            spell_mana = float(raw.get("spell_mana", 0.0))
        except (KeyError, TypeError, ValueError):
            raise SpellError(f"node {i + 1} has invalid fields", 1, 1,
                             "each node needs id, element, x, y, size", filename)
        if element not in ELEMENTS4 and not spell:
            raise SpellError(f"unknown weave element '{element}'", 1, 1,
                             "the prototype supports fire, water, earth, air", filename)
        if nid in used_ids:
            raise SpellError(f"duplicate node id {nid}", 1, 1, None, filename)
        used_ids.add(nid)
        program = []
        raw_program = raw.get("spell_program", [])
        if isinstance(raw_program, list):
            program = [_instruction_from_dict(item) for item in raw_program
                       if isinstance(item, dict)]
        graph.nodes.append(WeaveNode(nid, element, clamp(x, 0.04, 0.96),
                                     clamp(y, 0.04, 0.96),
                                     clamp(size, NODE_MIN, NODE_MAX),
                                     spell=spell, spell_mana=spell_mana,
                                     spell_program=program))
    raw_links = data.get("links", [])
    if not isinstance(raw_links, list):
        raise SpellError("'links' must be a list", 1, 1, None, filename)
    for i, raw in enumerate(raw_links):
        if not isinstance(raw, dict):
            raise SpellError(f"link {i + 1} is not an object", 1, 1, None, filename)
        try:
            src = int(raw["src"])
            dst = int(raw["dst"])
            bend = float(raw.get("bend", 0.0))
        except (KeyError, TypeError, ValueError):
            raise SpellError(f"link {i + 1} has invalid fields", 1, 1,
                             "each link needs src, dst, bend", filename)
        graph.links.append(WeaveLink(src, dst, clamp(bend, BEND_MIN, BEND_MAX)))
    if graph.nodes:
        graph.next_id = max(n.id for n in graph.nodes) + 1
    return graph


def save_weave(path: str, graph: WeaveGraph, name: str | None = None) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(graph.to_dict(name), fh, indent=2)
        fh.write("\n")


def load_weave_spell(path: str) -> SpellDef:
    graph = load_weave(path)
    spec = graph.resolve()
    if not spec.valid:
        raise SpellError(spec.reason, 1, 1,
                         "open the weave canvas with G and repair the circuit",
                         os.path.basename(path))
    if not graph.name:
        graph.name = spec.name
    spell = spec.to_spell(path)
    if graph.name:
        spell.name = graph.name
    return spell


def tornado_graph() -> WeaveGraph:
    """Four air runes in a ring, linked clockwise with outward-curving arrows."""
    graph = WeaveGraph(canvas="medium", name="Tornado")
    w = CANVAS["medium"]["w"]
    h = CANVAS["medium"]["h"]
    radius = min(w, h) * 0.27
    rx = radius / w
    ry = radius / h
    points = [(0.5, 0.5 - ry), (0.5 + rx, 0.5), (0.5, 0.5 + ry), (0.5 - rx, 0.5)]
    ids = []
    for x, y in points:
        node = graph.add_node("air", x, y, 1.0)
        if node:
            ids.append(node.id)
    for i in range(len(ids)):
        graph.add_link(ids[i], ids[(i + 1) % len(ids)], -0.45)
    graph.next_id = max(ids) + 1 if ids else 1
    return graph
