"""In-game spell editor with live compilation."""

from __future__ import annotations

import os
import re

import pygame

from .config import (ACCENT, BG, BG_PANEL, BG_PANEL_LIGHT, BORDER, CYAN, ELEMENTS,
                     GOLD, GREEN, RED, TEXT, TEXT_DIM, TEXT_FAINT, WINDOW_H, WINDOW_W)
from .gfx import draw_text, font, panel, text_width, wrap
from .spell_lang import INSTRUCTIONS, INSTRUCTION_NAMES, SpellError, compile_spell

TOKEN_RE = re.compile(r"(#.*)|(\"(?:[^\"\\]|\\.)*\")|([A-Za-z_]\w*)|(\d+(?:\.\d+)?)|([{}])")
KEYWORDS = {"spell", "cast", "mana", "cooldown", "desc", "on", "hit", "expire"}
ELEMENT_SET = set(ELEMENTS)

LAYOUT = {
    "outer": pygame.Rect(16, 16, WINDOW_W - 32, WINDOW_H - 32),
    "list": pygame.Rect(28, 84, 236, 604),
    "code": pygame.Rect(276, 84, 824, 556),
    "status": pygame.Rect(276, 648, 824, 40),
    "info": pygame.Rect(1112, 84, 300, 604),
}

LINE_H = 20
FONT_SIZE = 15
PAD_X = 10
PAD_Y = 8

TEMPLATE = """# Describe your spell. Ctrl+S to save.
spell Untitled {
  mana 20
  cooldown 0.8
  desc "A new spell."

  cast {
    bolt arcane speed=32 size=4 power=1.0
  }
}
"""


class Editor:
    def __init__(self, game):
        self.game = game
        self.open = False
        self.files: list[str] = []
        self.path: str | None = None
        self.lines: list[str] = [""]
        self.rows = 0
        self.cursor_row = 0
        self.cursor_col = 0
        self.scroll = 0
        self.dirty = False
        self.undo: list[tuple[list[str], int, int]] = []
        self.redo: list[tuple[list[str], int, int]] = []
        self.error: SpellError | None = None
        self.spell = None
        self.status = ""
        self.status_timer = 0.0
        self.btn_rects: dict[str, pygame.Rect] = {}
        self.mono = font(FONT_SIZE, mono=True)
        self.char_w = max(6, self.mono.size("M")[0])
        self.visible_rows = (LAYOUT["code"].h - PAD_Y * 2) // LINE_H
        self._refresh_files()

    # ------------------------------------------------------------------
    def _refresh_files(self) -> None:
        directory = self.game.spells_dir
        try:
            self.files = sorted(f for f in os.listdir(directory) if f.endswith(".spell"))
        except OSError:
            self.files = []

    def open_editor(self, path: str | None = None) -> None:
        self._refresh_files()
        if path is None:
            path = getattr(self.game.current_spell, "path", None)
        if path and os.path.exists(path):
            self._load_path(path)
        elif self.files:
            self._load_path(os.path.join(self.game.spells_dir, self.files[0]))
        else:
            self._new_file()
        self.open = True
        self.status = "Editing - Ctrl+S saves, F5 recompiles from disk, Esc closes"
        self.status_timer = 5.0

    def _load_path(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
        except OSError:
            self._new_file()
            return
        self.path = path
        self.lines = source.split("\n")
        if self.lines and self.lines[-1] == "":
            self.lines.pop()
        if not self.lines:
            self.lines = [""]
        self.rows = len(self.lines)
        self.cursor_row = 0
        self.cursor_col = 0
        self.scroll = 0
        self.dirty = False
        self.undo.clear()
        self.redo.clear()
        self._compile()

    def _new_file(self) -> None:
        self.path = None
        self.lines = TEMPLATE.rstrip("\n").split("\n")
        self.rows = len(self.lines)
        self.cursor_row = 3
        self.cursor_col = 0
        self.scroll = 0
        self.dirty = True
        self.undo.clear()
        self.redo.clear()
        self._compile()

    def _source(self) -> str:
        return "\n".join(self.lines) + "\n"

    def _compile(self) -> None:
        if not self._source().strip():
            self.error = None
            self.spell = None
            return
        try:
            self.spell = compile_spell(self._source(), os.path.basename(self.path) if self.path else "untitled")
            self.error = None
        except SpellError as exc:
            self.error = exc
            self.spell = None

    # ------------------------------------------------------------------
    def _snapshot(self) -> None:
        self.undo.append((list(self.lines), self.cursor_row, self.cursor_col))
        if len(self.undo) > 80:
            self.undo.pop(0)
        self.redo.clear()

    def _changed(self) -> None:
        self.rows = len(self.lines)
        self.dirty = True
        self._compile()

    def _insert(self, text: str) -> None:
        self._snapshot()
        line = self.lines[self.cursor_row]
        col = min(self.cursor_col, len(line))
        parts = text.split("\n")
        if len(parts) == 1:
            self.lines[self.cursor_row] = line[:col] + text + line[col:]
            self.cursor_col = col + len(text)
        else:
            indent = re.match(r"[ \t]*", line).group(0)
            before = line[:col]
            after = line[col:]
            new_lines = [before + parts[0]]
            for part in parts[1:]:
                new_lines.append(part)
            new_lines[-1] += after
            if text.endswith("\n"):
                new_lines[-1] = indent + after
            self.lines[self.cursor_row:self.cursor_row + 1] = new_lines
            self.cursor_row += len(parts) - 1
            self.cursor_col = len(indent) if text.endswith("\n") else len(parts[-1])
        self._changed()

    def _backspace(self) -> None:
        if self.cursor_col == 0:
            if self.cursor_row == 0:
                return
            self._snapshot()
            prev = self.lines[self.cursor_row - 1]
            cur = self.lines[self.cursor_row]
            self.cursor_col = len(prev)
            self.lines[self.cursor_row - 1] = prev + cur
            del self.lines[self.cursor_row]
            self.cursor_row -= 1
            self._changed()
            return
        self._snapshot()
        line = self.lines[self.cursor_row]
        col = min(self.cursor_col, len(line))
        self.lines[self.cursor_row] = line[:col - 1] + line[col:]
        self.cursor_col = col - 1
        self._changed()

    def _delete(self) -> None:
        line = self.lines[self.cursor_row]
        col = min(self.cursor_col, len(line))
        if col >= len(line):
            if self.cursor_row + 1 >= len(self.lines):
                return
            self._snapshot()
            self.lines[self.cursor_row] = line + self.lines[self.cursor_row + 1]
            del self.lines[self.cursor_row + 1]
            self._changed()
            return
        self._snapshot()
        self.lines[self.cursor_row] = line[:col] + line[col + 1:]
        self._changed()

    def _undo(self) -> None:
        if not self.undo:
            return
        self.redo.append((list(self.lines), self.cursor_row, self.cursor_col))
        self.lines, self.cursor_row, self.cursor_col = self.undo.pop()
        self.rows = len(self.lines)
        self._changed()

    def _redo(self) -> None:
        if not self.redo:
            return
        self.undo.append((list(self.lines), self.cursor_row, self.cursor_col))
        self.lines, self.cursor_row, self.cursor_col = self.redo.pop()
        self.rows = len(self.lines)
        self._changed()

    # ------------------------------------------------------------------
    def save(self) -> None:
        self._compile()
        name = self.spell.name if self.spell else None
        if name:
            for sp in self.game.spellbook.spells.values():
                same_path = bool(self.path) and os.path.abspath(sp.path) == os.path.abspath(self.path)
                if not same_path and sp.name.lower() == name.lower():
                    self.game.toast(f"Name '{name}' is already used by {os.path.basename(sp.path)}", RED, 4.0)
                    self.game.audio.play("error", 0.6)
                    return
        if self.path is None:
            base = (name or "untitled").lower()
            base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_") or "untitled"
            filename = base + ".spell"
            path = os.path.join(self.game.spells_dir, filename)
            n = 2
            while os.path.exists(path):
                path = os.path.join(self.game.spells_dir, f"{base}_{n}.spell")
                n += 1
            self.path = path
        try:
            with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(self._source())
        except OSError as exc:
            self.game.toast(f"Cannot save: {exc}", RED)
            return
        self.dirty = False
        self._refresh_files()
        self.game.reload_spells()
        self.game.stats["spells_saved"] += 1
        if self.spell:
            self.game.stats["code_saved"] += 1
        self.game._save_progress()
        if self.spell:
            self.status = f"Saved {self.spell.name} - cost {self.spell.cost}, mana {self.spell.mana}"
            self.game.toast(f"Spell saved: {self.spell.name}", GREEN)
            self.game.audio.play("heal", 0.45)
            self.game._update_quests()
        else:
            self.status = "Saved with compile errors"
            self.game.toast("Saved (compile errors)", GOLD)
            self.game.audio.play("error", 0.5)
        self.status_timer = 4.0

    def close(self) -> None:
        if self.dirty:
            self.save()
        self.open = False
        self.game.reload_spells()
        self.game.toast("Spellbook reloaded", ACCENT)

    def reload_from_disk(self) -> None:
        if self.path and os.path.exists(self.path):
            if self.dirty:
                self.save()
            self._load_path(self.path)
            self.status = "Reloaded from disk"
            self.status_timer = 3.0

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.open:
            return False
        if event.type == pygame.KEYDOWN:
            key = event.key
            mods = pygame.key.get_mods()
            ctrl = mods & pygame.KMOD_CTRL
            if key == pygame.K_ESCAPE:
                self.close()
                return True
            if ctrl and key == pygame.K_s:
                self.save()
                return True
            if ctrl and key == pygame.K_n:
                self._new_file()
                return True
            if ctrl and key == pygame.K_z:
                self._undo()
                return True
            if ctrl and key == pygame.K_y:
                self._redo()
                return True
            if key == pygame.K_F5:
                self.reload_from_disk()
                return True
            if key == pygame.K_UP:
                self._move_cursor(-1, 0)
            elif key == pygame.K_DOWN:
                self._move_cursor(1, 0)
            elif key == pygame.K_LEFT:
                self._move_cursor(0, -1)
            elif key == pygame.K_RIGHT:
                self._move_cursor(0, 1)
            elif key == pygame.K_PAGEUP:
                self._move_cursor(-self.visible_rows, 0)
            elif key == pygame.K_PAGEDOWN:
                self._move_cursor(self.visible_rows, 0)
            elif key == pygame.K_HOME:
                self.cursor_col = 0
            elif key == pygame.K_END:
                self.cursor_col = len(self.lines[self.cursor_row])
            elif key == pygame.K_BACKSPACE:
                self._backspace()
            elif key == pygame.K_DELETE:
                self._delete()
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._insert("\n")
            elif key == pygame.K_TAB:
                self._insert("    ")
            elif key == pygame.K_v and ctrl:
                try:
                    text = pygame.scrap.get_text()
                    if text:
                        self._insert(text.replace("\r\n", "\n").replace("\r", "\n"))
                except Exception:
                    pass
            elif event.unicode and event.unicode.isprintable() and not ctrl:
                self._insert(event.unicode)
            self._ensure_visible()
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            for name, rect in self.btn_rects.items():
                if rect.collidepoint(pos):
                    if name == "save":
                        self.save()
                    elif name == "new":
                        self.save() if self.dirty else None
                        self._new_file()
                    elif name == "reload":
                        self.reload_from_disk()
                    elif name == "close":
                        self.close()
                    return True
            if LAYOUT["list"].collidepoint(pos):
                self._click_file(pos)
                return True
            if LAYOUT["code"].collidepoint(pos):
                self._click_code(pos)
                return True
            return True

        if event.type == pygame.MOUSEWHEEL:
            mouse = pygame.mouse.get_pos()
            if LAYOUT["code"].collidepoint(mouse):
                self.scroll = max(0, min(max(0, self.rows - 1), self.scroll - event.y * 3))
                self._ensure_visible()
            return True
        return True

    def _move_cursor(self, drow: int, dcol: int) -> None:
        if drow:
            self.cursor_row = max(0, min(self.rows - 1, self.cursor_row + drow))
            self.cursor_col = min(self.cursor_col, len(self.lines[self.cursor_row]))
        if dcol:
            self.cursor_col += dcol
            if self.cursor_col < 0:
                if self.cursor_row > 0:
                    self.cursor_row -= 1
                    self.cursor_col = len(self.lines[self.cursor_row])
                else:
                    self.cursor_col = 0
            elif self.cursor_col > len(self.lines[self.cursor_row]):
                if self.cursor_row < self.rows - 1:
                    self.cursor_row += 1
                    self.cursor_col = 0
                else:
                    self.cursor_col = len(self.lines[self.cursor_row])

    def _ensure_visible(self) -> None:
        if self.cursor_row < self.scroll:
            self.scroll = self.cursor_row
        elif self.cursor_row >= self.scroll + self.visible_rows:
            self.scroll = self.cursor_row - self.visible_rows + 1

    def _click_file(self, pos) -> None:
        index = (pos[1] - LAYOUT["list"].y - 8) // 30
        if 0 <= index < len(self.files):
            if self.dirty:
                self.save()
            path = os.path.join(self.game.spells_dir, self.files[index])
            if path != self.path:
                self._load_path(path)

    def _click_code(self, pos) -> None:
        rect = LAYOUT["code"]
        row = self.scroll + (pos[1] - rect.y - PAD_Y) // LINE_H
        self.cursor_row = max(0, min(self.rows - 1, int(row)))
        col = int((pos[0] - rect.x - 46) // self.char_w)
        self.cursor_col = max(0, min(len(self.lines[self.cursor_row]), col))

    def update(self, dt: float) -> None:
        self.status_timer = max(0.0, self.status_timer - dt)

    # ------------------------------------------------------------------
    def draw(self, surf: pygame.Surface) -> None:
        pygame.draw.rect(surf, (6, 7, 12), surf.get_rect())
        outer = LAYOUT["outer"]
        panel(surf, outer, (14, 16, 25), BORDER, radius=12)

        # Header ------------------------------------------------------
        draw_text(surf, "SPELL FORGE", (outer.x + 16, outer.y + 12), 22, TEXT, bold=True)
        draw_text(surf, "the whole language is yours", (outer.x + 190, outer.y + 20), 12, TEXT_FAINT)
        name = os.path.basename(self.path) if self.path else "untitled.spell"
        draw_text(surf, name + (" *" if self.dirty else ""),
                  (outer.x + 16, outer.y + 40), 12, GOLD if self.dirty else TEXT_DIM, mono=True)

        self.btn_rects = {}
        bx = outer.right - 16
        for label, key, color in (("CLOSE", "close", TEXT_DIM), ("RELOAD", "reload", CYAN),
                                  ("NEW", "new", GOLD), ("SAVE", "save", GREEN)):
            w = text_width(label, 12, bold=True) + 22
            rect = pygame.Rect(bx - w, outer.y + 12, w, 26)
            pygame.draw.rect(surf, BG_PANEL_LIGHT, rect, border_radius=6)
            pygame.draw.rect(surf, BORDER, rect, 1, border_radius=6)
            draw_text(surf, label, (rect.centerx, rect.y + 6), 12, color, bold=True, align="center")
            self.btn_rects[key] = rect
            bx -= w + 6

        # File list ---------------------------------------------------
        lst = LAYOUT["list"]
        panel(surf, lst, BG_PANEL, BORDER, radius=8)
        draw_text(surf, "SPELLBOOK", (lst.x + 12, lst.y + 10), 12, TEXT_DIM, bold=True)
        draw_text(surf, f"{len(self.files)} files", (lst.right - 12, lst.y + 10), 11,
                  TEXT_FAINT, align="right")
        y = lst.y + 34
        for i, fname in enumerate(self.files):
            if y + 30 > lst.bottom - 8:
                break
            rect = pygame.Rect(lst.x + 8, y, lst.w - 16, 26)
            selected = self.path and os.path.basename(self.path) == fname
            if selected:
                pygame.draw.rect(surf, (48, 40, 72), rect, border_radius=5)
                pygame.draw.rect(surf, ACCENT, rect, 1, border_radius=5)
            elif rect.collidepoint(pygame.mouse.get_pos()):
                pygame.draw.rect(surf, BG_PANEL_LIGHT, rect, border_radius=5)
            label = fname[:-6] if fname.endswith(".spell") else fname
            draw_text(surf, label, (rect.x + 8, rect.y + 6), 12,
                      TEXT if selected else TEXT_DIM, mono=True)
            if selected and self.dirty:
                draw_text(surf, "*", (rect.right - 14, rect.y + 6), 12, GOLD)
            y += 30
        if len(self.files) > 18:
            draw_text(surf, "more files...", (lst.x + 12, lst.bottom - 22), 10, TEXT_FAINT)

        # Code area ---------------------------------------------------
        code = LAYOUT["code"]
        panel(surf, code, (11, 12, 20), BORDER, radius=8)
        self._draw_code(surf, code)

        # Status bar --------------------------------------------------
        status = LAYOUT["status"]
        panel(surf, status, BG_PANEL, BORDER, radius=6)
        msg = self.status if self.status_timer > 0 else \
            "Tab=indent  Ctrl+S save  Ctrl+N new  Ctrl+Z undo  F5 reload  Esc close"
        draw_text(surf, msg, (status.x + 10, status.y + 6), 11,
                  GOLD if self.status_timer > 0 else TEXT_FAINT)

        # Info panel --------------------------------------------------
        info = LAYOUT["info"]
        panel(surf, info, BG_PANEL, BORDER, radius=8)
        self._draw_info(surf, info)

    def _draw_code(self, surf: pygame.Surface, rect: pygame.Rect) -> None:
        text_x = rect.x + 46
        text_y = rect.y + PAD_Y
        old_clip = surf.get_clip()
        surf.set_clip(rect.inflate(-4, -4))
        visible = self.lines[self.scroll:self.scroll + self.visible_rows]
        err_line = self.error.line - 1 if self.error else -1

        for i, line in enumerate(visible):
            row = self.scroll + i
            y = text_y + i * LINE_H
            if row == err_line:
                pygame.draw.rect(surf, (54, 26, 32),
                                 (rect.x + 4, y - 2, rect.w - 8, LINE_H), border_radius=3)
            elif row == self.cursor_row:
                pygame.draw.rect(surf, (24, 26, 40),
                                 (rect.x + 4, y - 2, rect.w - 8, LINE_H), border_radius=3)
            draw_text(surf, str(row + 1), (rect.x + 36, y), 11, TEXT_FAINT, mono=True,
                      align="right")
            x = text_x
            for segment, color in self._segments(line):
                if x > rect.right - 6:
                    break
                draw_text(surf, segment, (x, y), FONT_SIZE, color, mono=True)
                x += self.mono.size(segment)[0]

        if pygame.time.get_ticks() % 1000 < 550:
            cy = text_y + (self.cursor_row - self.scroll) * LINE_H
            if text_y <= cy < rect.bottom - 6:
                cx = text_x + self.cursor_col * self.char_w
                color = RED if self.error else ACCENT
                pygame.draw.line(surf, color, (cx, cy), (cx, cy + 16), 2)
        surf.set_clip(old_clip)

    def _segments(self, line: str):
        pos = 0
        for m in TOKEN_RE.finditer(line):
            if m.start() > pos:
                yield line[pos:m.start()], TEXT
            tok = m.group(0)
            if tok.startswith("#"):
                color = TEXT_FAINT
            elif tok.startswith('"'):
                color = (150, 208, 130)
            elif tok in ("spell", "cast", "mana", "cooldown", "desc"):
                color = (255, 176, 96)
            elif tok in ("on", "hit", "expire"):
                color = GOLD
            elif tok in INSTRUCTIONS:
                color = (198, 152, 255)
            elif tok in ELEMENT_SET:
                color = ELEMENTS[tok]["color"]
            elif tok[0].isdigit():
                color = (132, 214, 232)
            elif tok in "{}":
                color = (222, 196, 132)
            elif tok == "=":
                color = TEXT_DIM
            else:
                color = TEXT
            yield tok, color
            pos = m.end()
        if pos < len(line):
            yield line[pos:], TEXT

    def _draw_info(self, surf: pygame.Surface, rect: pygame.Rect) -> None:
        x = rect.x + 14
        y = rect.y + 12
        w = rect.w - 28
        draw_text(surf, "COMPILER", (x, y), 12, TEXT_DIM, bold=True)
        y += 24
        if self.error:
            draw_text(surf, "ERROR", (x, y), 13, RED, bold=True)
            y += 20
            draw_text(surf, f"line {self.error.line}:{self.error.col}", (x, y), 11, RED)
            y += 18
            for line in wrap(self.error.message, w, 11):
                draw_text(surf, line, (x, y), 11, (255, 170, 170))
                y += 15
            if self.error.hint:
                y += 4
                for line in wrap("hint: " + self.error.hint, w, 11):
                    draw_text(surf, line, (x, y), 11, GOLD)
                    y += 15
        elif self.spell:
            draw_text(surf, "OK", (x, y), 13, GREEN, bold=True)
            y += 22
            draw_text(surf, self.spell.name, (x, y), 17, TEXT, bold=True)
            y += 24
            elem = self.spell.element
            draw_text(surf, elem.upper(), (x, y), 11, ELEMENTS[elem]["color"], bold=True)
            y += 20
            for label, value in (("mana", self.spell.mana), ("cost", self.spell.cost),
                                 ("cooldown", f"{self.spell.cooldown:g}s")):
                draw_text(surf, label, (x, y), 12, TEXT_DIM)
                draw_text(surf, str(value), (x + 90, y), 12, TEXT, mono=True)
                y += 18
            y += 6
            mana_left = self.spell.mana - self.spell.cost
            draw_text(surf, f"{mana_left} mana of headroom", (x, y), 10,
                      GREEN if mana_left >= 0 else RED)
            y += 22
            for line in wrap(self.spell.desc or "No description.", w, 11):
                draw_text(surf, line, (x, y), 11, TEXT_DIM)
                y += 15
        else:
            draw_text(surf, "-", (x, y), 13, TEXT_DIM)
            y += 22

        y = max(y + 12, rect.y + 250)
        pygame.draw.line(surf, BORDER, (x, y), (x + w, y), 1)
        y += 12
        draw_text(surf, "QUICK REFERENCE", (x, y), 11, TEXT_DIM, bold=True)
        y += 20
        refs = {
            "bolt": "element  speed size power pierce homing life offset",
            "burst": "element  radius power offset",
            "beam": "element  length width power offset",
            "wall": "element  length height life offset",
            "orb": "element  radius life power offset",
            "volley": "element  count spread power speed size",
            "shield": "element  radius life power",
            "dash": "power  [element]",
            "blink": "distance",
            "heal": "amount",
        }
        for name, params in refs.items():
            if y > rect.bottom - 40:
                break
            draw_text(surf, name, (x, y), 10, (198, 152, 255), mono=True)
            wrapped = wrap(params, w - 10, 9, mono=True)[:2]
            for j, line in enumerate(wrapped):
                draw_text(surf, line, (x + 4, y + 10 + j * 10), 9, TEXT_FAINT, mono=True)
            y += 11 + 10 * len(wrapped) + 2
        y += 6
        if y < rect.bottom - 90:
            draw_text(surf, "EVENTS", (x, y), 10, TEXT_DIM, bold=True)
            y += 16
            for line in ("bolt { on hit { ... } on expire { ... } }",
                         "beam { on hit { ... } }"):
                draw_text(surf, line, (x, y), 9, TEXT_FAINT, mono=True)
                y += 13
        if y < rect.bottom - 70:
            y += 6
            draw_text(surf, "ELEMENTS", (x, y), 10, TEXT_DIM, bold=True)
            y += 16
            cols = 2
            for i, (ename, data) in enumerate(ELEMENTS.items()):
                ex = x + (i % cols) * (w // cols)
                ey = y + (i // cols) * 13
                draw_text(surf, ename, (ex, ey), 9, data["color"], mono=True)
            y += 13 * ((len(ELEMENTS) + 1) // cols)
        if y < rect.bottom - 46:
            y += 8
            draw_text(surf, "mana must be >= computed cost", (x, y), 10, GOLD)
