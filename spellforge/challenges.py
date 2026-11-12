"""The sequential quest chain that also acts as the tutorial."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Challenge:
    id: str
    title: str
    desc: str
    goal: float
    stat: str
    unit: str = ""
    hint: str = ""
    reward_xp: int = 20
    unlock: str | None = None


CHALLENGES: list[Challenge] = [
    Challenge(
        "first_spark", "First Spark", "Cast any spell once.", 1, "casts",
        "spell", "Select a spell with 1-9 or the mouse wheel. Aim with the "
        "mouse and press the left button.", 20,
    ),
    Challenge(
        "first_blood", "First Blood", "Defeat 3 enemies.", 3, "kills",
        "kills", "Husks rush you; Watchers keep their distance and shoot. "
        "Use cover and your cheapest spell.", 30,
    ),
    Challenge(
        "first_weave", "Weaver's Apprentice", "Save a spell on the weave canvas.",
        1, "weaves_saved", "weave",
        "Press G. Pick an element, click the canvas to place two runes, then "
        "right-drag from one rune to the other and press Ctrl+S.", 40,
        unlock="medium",
    ),
    Challenge(
        "closed_circuit", "Closed Circuit", "Save a weave that contains a closed loop.",
        1, "weave_cycles", "ring",
        "On the MEDIUM canvas, place four runes of the same element in a ring. "
        "Right-drag each rune to the next one, curving the arrow outward.", 50,
    ),
    Challenge(
        "storm_caller", "Storm Caller", "Cast a vortex spell.", 1, "vortex_casts",
        "vortex", "A closed Air ring becomes a Tornado. Select it with the wheel "
        "or the spellbook (TAB) and cast it into a group of enemies.", 45,
    ),
    Challenge(
        "pyromancer", "Pyromancer", "Set 20 flammable tiles alight.", 20, "burned",
        "tiles", "Fire spreads through wood, plants and oil. Emberbolt and Pyre "
        "are good starters.", 40,
    ),
    Challenge(
        "deep_freeze", "Deep Freeze", "Freeze 10 tiles of water into ice.", 10,
        "frozen", "tiles", "Aim Frostshard or Frostwall at the pond in the lower "
        "left of the arena.", 40,
    ),
    Challenge(
        "alchemist", "Alchemist", "Dissolve 10 solid tiles with acid.", 10,
        "dissolved", "tiles", "VenomPool spills acid. Drop it on stone, wood or ice "
        "and let it eat through the material.", 50,
    ),
    Challenge(
        "bulwark", "Bulwark", "Block 3 hostile bolts with a shield.", 3,
        "shield_blocks", "bolts", "Cast Ward and stand between a Watcher and its "
        "line of fire. The barrier counts every bolt it stops.", 40,
    ),
    Challenge(
        "overkill", "Overkill", "Deal 80 damage with a single cast.", 1, "overkills",
        "cast", "Build a large, focused weave: size up your runes, keep the "
        "circuit tight, and use power. One big detonation is enough.", 60,
        unlock="large",
    ),
    Challenge(
        "grand_ritual", "Grand Ritual", "Save a weave that spends at least 500 mana.",
        1, "big_weaves", "weave",
        "The HIGH canvas is unlocked now. Fill it with runes and arrows until the "
        "weave spends 500 raw mana (before the 20% weaving discount), then save it.", 70,
    ),
    Challenge(
        "architect", "Architect", "Write and save a spell in the code editor.",
        1, "code_saved", "spell",
        "Press E. Edit one of the example spells, or write a new one. Ctrl+S saves "
        "the file into spells/.", 50,
    ),
]
