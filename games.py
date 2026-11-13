"""The four games. Each one keeps its own state and knows how to:

    draw(w, h, now)    shapes for its board, a w×h area at the canvas' top left
    key(name, repeat)  react to a key ("Up", "Space", "R", ...)
    click(x, y, w, h)  react to a click on the board
    press(id)          react to one of its own buttons
    controls()         buttons shown next to the game chips
    stats(now)         [(label, value, note)] for the side panel
    keys_help()        [(keycaps, what they do)] for the side panel
    interval()         seconds until it next needs tick(), or None when still
    tick(now)          advance movement, animations and timers

and reports a finished score through `self.finished` (set to a number when a
round ends; main.py compares it with the best and clears it).
"""

import math
import random
import threading
import time

import nook

# Set by main.py from Nook's theme before each draw.
theme = {"dark": True, "accent": "#7C5CFF"}

KEY_DIRS = {"Up": (0, -1), "W": (0, -1), "Down": (0, 1), "S": (0, 1),
            "Left": (-1, 0), "A": (-1, 0), "Right": (1, 0), "D": (1, 0)}
DIR_NAMES = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}
ARROWS = {"Up": "arrow-up", "Down": "arrow-down", "Left": "arrow-left", "Right": "arrow-right"}
FPS = 1 / 30


# Colors and shared pieces ---------------------------------------------------------------

def with_alpha(hex_color, a):
    """#RRGGBB plus an alpha of 0-1."""
    return f"#{hex_color.lstrip('#')[:6]}{round(max(0.0, min(1.0, a)) * 255):02X}"


def ink(a):
    """The theme's text color, faded: for board backgrounds and outlines."""
    return with_alpha("#FFFFFF" if theme["dark"] else "#000000", a)


def accent(a=1.0):
    return with_alpha(theme["accent"], a)


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def board_bg(x, y, w, h, radius=12):
    return nook.rect(x, y, w, h, fill=ink(0.035), stroke=ink(0.09), width=1, radius=radius)


def overlay(w, h, title, sub="", icon=None, color=None, extra=()):
    """A card in the middle of the board: paused, game over, ..."""
    cw, ch = min(w - 32, 300), 92 if sub else 64
    x, y = (w - cw) / 2, (h - ch) / 2
    out = [nook.rect(0, 0, w, h, fill=with_alpha("#000000" if theme["dark"] else "#FFFFFF", 0.35),
                     radius=12),
           nook.rect(x, y, cw, ch, radius=14, fill="#1B1B22F2" if theme["dark"] else "#FFFFFFF5",
                     stroke=ink(0.12), width=1)]
    ty = y + (30 if sub else ch / 2)
    if icon:
        out.append(nook.glyph(w / 2, y + 22, icon, size=20, color=color or "accent", fill=True))
        ty += 14
    out.append(nook.label(w / 2, ty, title, size=19, bold=True, anchor="center"))
    if sub:
        out.append(nook.label(w / 2, ty + 24, sub, size=11, color="dim", anchor="center"))
    return out + list(extra)


def keycap(x, y, cap):
    """Draws one key at (x, y) (its top left); returns (shapes, width)."""
    w = 18 if cap in ARROWS or len(cap) == 1 else 9 + 6.2 * len(cap)
    out = [nook.rect(x, y, w, 18, radius=5, fill=ink(0.06), stroke=ink(0.16), width=1)]
    if cap in ARROWS:
        out.append(nook.glyph(x + w / 2, y + 9, ARROWS[cap], size=11, color="dim"))
    else:
        out.append(nook.label(x + w / 2, y + 9, cap, size=10, color="dim", anchor="center"))
    return out, w


def side_panel(x, w, h, game, best, new_best, now):
    """Name, score, best and the keys, on the right of the board."""
    out = [nook.rect(x, 0, w, h, radius=12, fill=ink(0.035), stroke=ink(0.09), width=1)]
    out.append(nook.glyph(x + 22, 22, game.icon, size=17, color="accent", fill=True))
    out.append(nook.label(x + 38, 22, game.name, size=14, bold=True))
    y = 50
    stats = game.stats(now)
    for i, (lab, value, note) in enumerate(stats):
        big = i == 0
        out.append(nook.label(x + 14, y, lab.upper(), size=9, color="faint", bold=True))
        out.append(nook.label(x + 14, y + (19 if big else 16), value, size=24 if big else 15,
                              bold=True))
        if note:
            out.append(nook.label(x + w - 12, y + (19 if big else 16), note, size=11,
                                  color="accent", anchor="end", bold=True))
        y += 46 if big else 36
    out.append(nook.label(x + 14, y, "BEST", size=9, color="faint", bold=True))
    out.append(nook.label(x + 14, y + 16, best, size=13, bold=True,
                          color="yellow" if new_best else "text"))
    if new_best:
        out.append(nook.glyph(x + w - 20, y + 10, "trophy", size=16, color="yellow", fill=True))
    # Keys, from the bottom up, when there's room under the stats.
    helps = (game.keys_help() + [(["Tab"], "Next game")])[:max(0, int((h - y - 40) // 24))]
    for i, (caps, what) in enumerate(helps):
        ky = h - 30 - (len(helps) - 1 - i) * 24
        kx = x + 12
        for cap in caps:
            shapes, cw = keycap(kx, ky, cap)
            out += shapes
            kx += cw + 3
        out.append(nook.label(kx + 4, ky + 9, what, size=10, color="dim"))
    return out


# Comet: a snake-like game on a board that wraps around its edges ---------------------------

class Comet:
    name, icon = "Comet", "shooting-star"
    lower_is_better = False
    COLS, ROWS = 24, 16
    BONUS_TIME = 6.0

    def __init__(self):
        self.finished = None
        self.reset()

    def reset(self):
        cy = self.ROWS // 2
        self.body = [(6, cy), (5, cy), (4, cy)]
        self.dir = (1, 0)
        self.queue = []
        self.score = 0
        self.stars = 0
        self.state = "ready"   # ready, running, paused, over
        self.food = self._free()
        self.bonus = None      # [cell, seconds left]
        self.sparks = []       # (x, y, vx, vy, born, color) in cells and cells/s
        self.acc = 0.0
        self.last = None

    def _free(self):
        taken = set(self.body)
        if getattr(self, "food", None):
            taken.add(self.food)
        if getattr(self, "bonus", None):
            taken.add(self.bonus[0])
        free = [(x, y) for x in range(self.COLS) for y in range(self.ROWS) if (x, y) not in taken]
        return random.choice(free) if free else None

    def level(self):
        return 1 + self.stars // 5

    def step_time(self):
        return max(0.055, 0.15 - self.score * 0.0022)

    def start(self):
        if self.state == "over":
            self.reset()
        if self.state != "running":
            self.state = "running"
            self.last = time.monotonic()
            self.acc = 0.0

    def pause(self):
        if self.state == "running":
            self.state = "paused"

    def turn(self, d):
        last = self.queue[-1] if self.queue else self.dir
        if d != last and d != (-last[0], -last[1]) and len(self.queue) < 3:
            self.queue.append(d)

    def _burst(self, cell, color, n, now):
        for k in range(n):
            a = 2 * math.pi * k / n + random.uniform(-0.3, 0.3)
            v = random.uniform(3, 7)
            self.sparks.append((cell[0] + .5, cell[1] + .5, math.cos(a) * v, math.sin(a) * v,
                                now, color))

    def _step(self, now):
        if self.queue:
            self.dir = self.queue.pop(0)
        hx, hy = self.body[0]
        head = ((hx + self.dir[0]) % self.COLS, (hy + self.dir[1]) % self.ROWS)
        eating = head == self.food
        body = self.body if eating else self.body[:-1]
        if head in body:
            self.state = "over"
            self.finished = self.score
            self._burst(self.body[0], "#F05A5A", 16, now)
            return
        self.body = [head] + body
        if eating:
            self.score += 1
            self.stars += 1
            self._burst(head, "#F2C94C", 10, now)
            self.food = self._free()
            if self.stars % 5 == 0 and not self.bonus:
                cell = self._free()
                if cell:
                    self.bonus = [cell, self.BONUS_TIME]
            if self.food is None:  # filled the board
                self.state = "over"
                self.finished = self.score
        if self.bonus and head == self.bonus[0]:
            self.score += 3 + self.level()
            self._burst(head, "#F26DB5", 14, now)
            self.bonus = None

    def interval(self):
        return FPS if self.state == "running" or self.sparks else None

    def tick(self, now):
        dt = min(0.25, now - self.last) if self.last else 0.0
        self.last = now
        self.sparks = [s for s in self.sparks if now - s[4] < 0.55]
        if self.state != "running":
            return
        if self.bonus:
            self.bonus[1] -= dt
            if self.bonus[1] <= 0:
                self.bonus = None
        self.acc += dt
        while self.state == "running" and self.acc >= self.step_time():
            self.acc -= self.step_time()
            self._step(now)

    def _geometry(self, w, h):
        cell = min((w - 8) / self.COLS, (h - 8) / self.ROWS)
        return cell, (w - cell * self.COLS) / 2, (h - cell * self.ROWS) / 2

    def draw(self, w, h, now):
        cell, ox, oy = self._geometry(w, h)
        bw, bh = cell * self.COLS, cell * self.ROWS
        out = [board_bg(ox - 4, oy - 4, bw + 8, bh + 8)]
        grid = ink(0.035)
        for c in range(1, self.COLS):
            out.append(nook.line([(ox + c * cell, oy), (ox + c * cell, oy + bh)], color=grid))
        for r in range(1, self.ROWS):
            out.append(nook.line([(ox, oy + r * cell), (ox + bw, oy + r * cell)], color=grid))
        at = lambda x, y: (ox + (x + .5) * cell, oy + (y + .5) * cell)  # noqa: E731
        if self.food:
            fx, fy = at(*self.food)
            pulse = 1 + 0.12 * math.sin(now * 6)
            out.append(nook.circle(fx, fy, cell * 0.62 * pulse, fill=with_alpha("#F2C94C", 0.16)))
            out.append(nook.glyph(fx, fy, "star", size=cell * 0.9, color="yellow", fill=True))
        if self.bonus:
            bx, by = at(*self.bonus[0])
            left = self.bonus[1] / self.BONUS_TIME
            out.append(nook.circle(bx, by, cell * 0.75, fill=with_alpha("#F26DB5", 0.14)))
            out.append(nook.arc(bx, by, cell * 0.75, 0, 360 * left, color="pink", width=2))
            out.append(nook.glyph(bx, by, "diamond", size=cell * 0.85, color="pink", fill=True))
        # The tail thins and fades like a comet's.
        alive = self.state != "over"
        base = theme["accent"] if alive else "#8A8A96"
        n = len(self.body)
        for i in range(n - 1, 0, -1):
            t = i / max(1, n - 1)
            x, y = at(*self.body[i])
            out.append(nook.circle(x, y, cell * (0.46 - 0.24 * t), fill=with_alpha(base, 1 - 0.7 * t)))
        hx, hy = at(*self.body[0])
        out.append(nook.circle(hx, hy, cell * 0.78, fill=with_alpha(base, 0.18)))
        out.append(nook.circle(hx, hy, cell * 0.54, fill=with_alpha(base, 1)))
        dx, dy = self.dir
        for side in (-1, 1):
            ex = hx + dx * cell * 0.14 - dy * side * cell * 0.22
            ey = hy + dy * cell * 0.14 + dx * side * cell * 0.22
            out.append(nook.circle(ex, ey, cell * 0.13, fill="white"))
            if alive:
                out.append(nook.circle(ex + dx * cell * 0.05, ey + dy * cell * 0.05, cell * 0.065,
                                       fill="#1B1B22"))
        for (sx, sy, vx, vy, born, color) in self.sparks:
            t = (now - born) / 0.55
            px = ox + (sx + vx * t * 0.55) * cell
            py = oy + (sy + vy * t * 0.55) * cell
            out.append(nook.circle(px, py, max(0.5, cell * 0.16 * (1 - t)),
                                   fill=with_alpha(color, 1 - t)))
        if self.state == "ready":
            out += overlay(w, h, "Comet", "Arrow keys or WASD to fly · catch the stars",
                           icon="shooting-star")
        elif self.state == "paused":
            out += overlay(w, h, "Paused", "Space or an arrow to keep flying", icon="pause")
        elif self.state == "over" and not self.sparks:
            out += overlay(w, h, f"{self.score} points", "Space to fly again", icon="skull",
                           color="red")
        return out

    def key(self, k, repeat):
        d = KEY_DIRS.get(k)
        if d:
            if self.state == "over":
                self.reset()
            self.turn(d)
            self.start()
        elif k in ("Space", "Enter", "P", "Escape"):
            if self.state == "running":
                self.pause()
            elif k != "Escape" and not repeat:
                self.start()
        elif k == "R":
            self.reset()

    def click(self, x, y, w, h):
        if self.state != "running":
            self.start()
            return
        cell, ox, oy = self._geometry(w, h)
        hx, hy = self.body[0]
        dx = x - (ox + (hx + .5) * cell)
        dy = y - (oy + (hy + .5) * cell)
        cur = self.queue[-1] if self.queue else self.dir
        if cur[0] != 0:  # moving sideways: clicks steer up or down
            if abs(dy) > cell / 2:
                self.turn((0, -1 if dy < 0 else 1))
        elif abs(dx) > cell / 2:
            self.turn((-1 if dx < 0 else 1, 0))

    def press(self, eid):
        if eid == "comet:pause":
            if self.state == "running":
                self.pause()
            else:
                self.start()

    def controls(self):
        running = self.state == "running"
        return [nook.button("comet:pause", icon="pause" if running else "play",
                            tooltip="Pause (Space)" if running else "Play (Space)",
                            primary=not running)]

    def stats(self, now):
        note = f"+{3 + self.level()}" if self.bonus else None
        return [("Score", self.score, note), ("Level", self.level(), None),
                ("Length", len(self.body), None)]

    def keys_help(self):
        return [(["Up", "Down", "Left", "Right"], "Steer"), (["Space"], "Pause"),
                (["R"], "Restart")]


# Doubles: slide the board, equal tiles merge into their sum ---------------------------------

# 2, 4, 8, ... each a step around the color wheel; dark text on the light ones.
TILE_COLORS = ["#5B7CFA", "#3FA7F5", "#2EC4B6", "#3DC97A", "#9BCB3C", "#F2C94C", "#F59E3B",
               "#F2704E", "#F05A5A", "#F26DB5", "#A37CFF", "#7C5CFF"]
DARK_TEXT = {"#9BCB3C", "#F2C94C"}


class Doubles:
    name, icon = "Doubles", "squares-four"
    lower_is_better = False
    N = 4
    UNDOS = 3

    def __init__(self):
        self.finished = None
        self.reset()

    def reset(self):
        self.grid = [[0] * self.N for _ in range(self.N)]
        self.score = 0
        self.over = False
        self.reached = False      # made a 2048 tile
        self.cheer = False        # showing the 2048 banner
        self.undo = None          # (grid, score) before the last move
        self.undos = self.UNDOS
        self.anims = {}           # (r, c) -> ("new" | "merge", start)
        self.gain = None          # (points, when)
        self._spawn(0)
        self._spawn(0)

    def _spawn(self, now):
        empty = [(r, c) for r in range(self.N) for c in range(self.N) if not self.grid[r][c]]
        if empty:
            r, c = random.choice(empty)
            self.grid[r][c] = 4 if random.random() < 0.1 else 2
            self.anims[(r, c)] = ("new", now)

    @staticmethod
    def _slide(line):
        vals = [v for v in line if v]
        out, merged, gained, i = [], [], 0, 0
        while i < len(vals):
            if i + 1 < len(vals) and vals[i] == vals[i + 1]:
                merged.append(len(out))
                out.append(vals[i] * 2)
                gained += vals[i] * 2
                i += 2
            else:
                out.append(vals[i])
                i += 1
        return out + [0] * (len(line) - len(out)), merged, gained

    def move(self, d):
        if self.over:
            return
        now = time.monotonic()
        n, g = self.N, self.grid
        before = ([row[:] for row in g], self.score)
        moved, gained = False, 0
        self.anims = {}
        for k in range(n):
            idx = [(k, c) for c in range(n)] if d in ("left", "right") else [(r, k) for r in range(n)]
            if d in ("right", "down"):
                idx.reverse()
            line = [g[r][c] for r, c in idx]
            new, merged, got = self._slide(line)
            if new != line:
                moved = True
                gained += got
                for (r, c), v in zip(idx, new):
                    g[r][c] = v
                for j in merged:
                    self.anims[idx[j]] = ("merge", now)
        if not moved:
            return
        self.cheer = False
        self.undo = before
        self.score += gained
        if gained:
            self.gain = (gained, now)
        self._spawn(now)
        if not self.reached and any(v >= 2048 for row in g for v in row):
            self.reached = self.cheer = True
        if not self._can_move():
            self.over = True
            self.finished = self.score

    def take_back(self):
        if self.undo and self.undos > 0:
            grid, self.score = self.undo
            self.grid = [row[:] for row in grid]
            self.undo, self.over, self.cheer = None, False, False
            self.undos -= 1
            self.anims, self.gain = {}, None

    def _can_move(self):
        g, n = self.grid, self.N
        for r in range(n):
            for c in range(n):
                if not g[r][c]:
                    return True
                if c + 1 < n and g[r][c] == g[r][c + 1]:
                    return True
                if r + 1 < n and g[r][c] == g[r + 1][c]:
                    return True
        return False

    def interval(self):
        now = time.monotonic()
        busy = any(now - t < 0.2 for _, t in self.anims.values())
        return FPS if busy or (self.gain and now - self.gain[1] < 0.9) else None

    def tick(self, now):
        self.anims = {k: v for k, v in self.anims.items() if now - v[1] < 0.2}

    def _geometry(self, w, h):
        side = min(w, h) - 4
        return side, (w - side) / 2, (h - side) / 2

    def draw(self, w, h, now):
        side, ox, oy = self._geometry(w, h)
        gap = max(5, side * 0.025)
        cell = (side - gap * (self.N + 1)) / self.N
        out = [board_bg(ox, oy, side, side)]
        for r in range(self.N):
            for c in range(self.N):
                x = ox + gap + c * (cell + gap)
                y = oy + gap + r * (cell + gap)
                out.append(nook.rect(x, y, cell, cell, radius=cell * 0.16, fill=ink(0.05)))
        for r in range(self.N):
            for c in range(self.N):
                v = self.grid[r][c]
                if not v:
                    continue
                scale = 1.0
                kind, t0 = self.anims.get((r, c), (None, 0))
                if kind == "new":
                    scale = 0.35 + 0.65 * ease_out((now - t0) / 0.15)
                elif kind == "merge":
                    scale = 1 + 0.14 * math.sin(math.pi * min(1.0, (now - t0) / 0.18))
                s = cell * scale
                x = ox + gap + c * (cell + gap) + (cell - s) / 2
                y = oy + gap + r * (cell + gap) + (cell - s) / 2
                level = v.bit_length() - 2  # 2 -> 0, 4 -> 1, ...
                fill = TILE_COLORS[level] if level < len(TILE_COLORS) else "#2A2A33"
                text = "#1B1B22" if fill in DARK_TEXT else ("#F2C94C" if level >= len(TILE_COLORS)
                                                            else "white")
                if v >= 1024:
                    out.append(nook.rect(x - 3, y - 3, s + 6, s + 6, radius=s * 0.2,
                                         fill=with_alpha(fill, 0.3)))
                out.append(nook.rect(x, y, s, s, radius=s * 0.16, fill=fill))
                out.append(nook.rect(x, y, s, s * 0.5, radius=s * 0.16, fill="#FFFFFF14"))
                digits = len(str(v))
                size = s * {1: 0.46, 2: 0.42, 3: 0.35, 4: 0.28}.get(digits, 0.23)
                out.append(nook.label(x + s / 2, y + s / 2, v, size=size, bold=True, color=text,
                                      anchor="center"))
        if self.over:
            sub = "U to take back a move · R for a new board" if self.undo and self.undos else \
                "Click or press R for a new board"
            out += overlay(w, h, "No moves left", sub, icon="flag", color="orange")
        elif self.cheer:
            out += overlay(w, h, "2048!", "Keep going: any arrow", icon="crown", color="yellow")
        return out

    def key(self, k, repeat):
        d = KEY_DIRS.get(k)
        if d and not repeat:
            self.move(DIR_NAMES[d])
        elif k in ("U", "Z", "Backspace"):
            self.take_back()
        elif k == "R" or (self.over and k in ("Space", "Enter")):
            self.reset()

    def click(self, x, y, w, h):
        if self.over:
            self.reset()
            return
        side, ox, oy = self._geometry(w, h)
        dx, dy = x - (ox + side / 2), y - (oy + side / 2)
        if abs(dx) > abs(dy):
            self.move("right" if dx > 0 else "left")
        else:
            self.move("down" if dy > 0 else "up")

    def press(self, eid):
        if eid == "doubles:undo":
            self.take_back()

    def controls(self):
        if not (self.undo and self.undos):
            return []
        return [nook.button("doubles:undo", icon="arrow-u-up-left",
                            tooltip=f"Take back a move (U) · {self.undos} left")]

    def stats(self, now):
        top = max(max(row) for row in self.grid)
        note = f"+{self.gain[0]}" if self.gain and now - self.gain[1] < 0.9 else None
        return [("Score", self.score, note), ("Top tile", top, None),
                ("Undo", f"{self.undos} left", None)]

    def keys_help(self):
        return [(["Up", "Down", "Left", "Right"], "Slide"), (["U"], "Undo"), (["R"], "New")]


# Reflex: press as soon as the panel turns green ---------------------------------------------

def rating(ms):
    for limit, word in ((200, "Lightning"), (250, "Sharp"), (300, "Quick"), (400, "Steady")):
        if ms < limit:
            return word
    return "Sleepy"


class Reflex:
    name, icon = "Reflex", "lightning"
    lower_is_better = True
    ROUNDS = 5

    def __init__(self):
        self.finished = None
        self.timer = None
        self.post = None  # set by main.py: wakes the main loop from the timer thread
        self.reset()

    def reset(self):
        self.cancel()
        self.phase = "idle"   # idle, waiting, go, result, early, done
        self.times = []
        self.go_at = 0.0
        self.last = None

    def cancel(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def arm(self):
        """Starts a round: turns green after 1.5-4 s."""
        self.cancel()
        self.phase = "waiting"
        self.timer = threading.Timer(random.uniform(1.5, 4.0), lambda: self.post({"type": "x-go"}))
        self.timer.daemon = True
        self.timer.start()

    def go(self):
        if self.phase == "waiting":
            self.phase = "go"
            self.go_at = 0.0  # set by main.py right after the green frame is sent

    def hit(self):
        if self.phase == "go":
            ms = int(round((time.monotonic() - self.go_at) * 1000))
            self.last = ms
            self.times.append(ms)
            if len(self.times) >= self.ROUNDS:
                self.phase = "done"
                self.finished = int(round(sum(self.times) / len(self.times)))
            else:
                self.phase = "result"
        elif self.phase == "waiting":
            self.cancel()
            self.phase = "early"
        elif self.phase == "done":
            self.reset()
            self.arm()
        else:  # idle, result, early
            self.arm()

    def interval(self):
        return None

    def tick(self, now):
        pass

    def draw(self, w, h, now):
        fills = {"waiting": "#E5484D", "go": "#2FB36D", "early": "#F59E3B"}
        fill = fills.get(self.phase)
        out = [nook.rect(0, 0, w, h, radius=12, fill=fill, stroke=None if fill else ink(0.09),
                         width=1)] if fill else [board_bg(0, 0, w, h)]
        on_color = fill is not None
        cx, cy = w / 2, h / 2 - 16
        r = min(w, h) * 0.17
        avg = sum(self.times) / len(self.times) if self.times else 0
        if self.phase == "waiting":
            out += [nook.circle(cx, cy, r, stroke="#FFFFFF66", width=3),
                    nook.glyph(cx, cy, "hand-tap", size=r * 0.9, color="white")]
            title, sub = "Wait for green…", "Pressing now counts as too soon"
        elif self.phase == "go":
            out += [nook.circle(cx, cy, r * 1.25, fill="#FFFFFF33"),
                    nook.circle(cx, cy, r, fill="white"),
                    nook.glyph(cx, cy, "lightning", size=r * 1.1, color="#2FB36D", fill=True)]
            title, sub = "Now!", ""
        elif self.phase == "early":
            out += [nook.circle(cx, cy, r, fill="#FFFFFF33"),
                    nook.glyph(cx, cy, "x", size=r, color="white")]
            title, sub = "Too soon!", "Space or click to retry this round"
        elif self.phase == "result":
            out += [nook.circle(cx, cy, r, fill=accent(0.14)),
                    nook.label(cx, cy - 4, self.last, size=r * 0.75, bold=True, anchor="center"),
                    nook.label(cx, cy + r * 0.45, "ms", size=11, color="dim", anchor="center")]
            title = rating(self.last)
            sub = f"Round {len(self.times)} of {self.ROUNDS} · Space or click for the next"
        elif self.phase == "done":
            out += [nook.circle(cx, cy, r, fill=accent(0.14)),
                    nook.glyph(cx, cy, "trophy", size=r, color="yellow", fill=True)]
            title = f"{avg:.0f} ms · {rating(avg)}"
            sub = "Space or click to play again"
        else:
            out += [nook.circle(cx, cy, r, fill=accent(0.14)),
                    nook.glyph(cx, cy, "lightning", size=r, color="accent", fill=True)]
            title = "Test your reflexes"
            sub = f"{self.ROUNDS} rounds · press Space or click when it turns green"
        out.append(nook.label(cx, cy + r + 24, title, size=22, bold=True,
                              color="white" if on_color else "text", anchor="center"))
        if sub:
            out.append(nook.label(cx, cy + r + 46, sub, size=11,
                                  color="#FFFFFFCC" if on_color else "dim", anchor="center"))
        for i in range(self.ROUNDS):
            x = w / 2 + (i - (self.ROUNDS - 1) / 2) * 18
            if i < len(self.times):
                out.append(nook.circle(x, h - 16, 5, fill="white" if on_color else "accent"))
            else:
                out.append(nook.circle(x, h - 16, 5, stroke="#FFFFFF88" if on_color else ink(0.25),
                                       width=1.5))
        return out

    def key(self, k, repeat):
        if k in ("Space", "Enter") and not repeat:
            self.hit()
        elif k == "R":
            self.reset()

    def click(self, x, y, w, h):
        self.hit()

    def press(self, eid):
        pass

    def controls(self):
        return []

    def stats(self, now):
        avg = sum(self.times) / len(self.times) if self.times else None
        played = len(self.times) if self.phase in ("result", "done") else len(self.times) + 1
        return [("Last", f"{self.last} ms" if self.last is not None else "–",
                 rating(self.last) if self.last is not None else None),
                ("Average", f"{avg:.0f} ms" if avg else "–", None),
                ("Round", f"{min(played, self.ROUNDS)} / {self.ROUNDS}", None)]

    def keys_help(self):
        return [(["Space"], "React"), (["R"], "Restart")]


# Pairs: turn over two cards at a time and find all the matches ------------------------------

PAIR_ICONS = ["star", "heart", "moon", "sun", "leaf", "fish", "rocket", "crown",
              "diamond", "lightning", "gift", "butterfly", "cat", "bird", "planet", "ghost"]
PAIR_COLORS = ["#F2C94C", "#F05A5A", "#A37CFF", "#F59E3B", "#3DC97A", "#4C9AFF", "#2EC4B6",
               "#F26DB5"]
FLIP = 0.22


class Pairs:
    name, icon = "Pairs", "cards"
    lower_is_better = True
    COLS, ROWS = 6, 3

    def __init__(self):
        self.finished = None
        self.reset()

    def reset(self):
        n = self.COLS * self.ROWS // 2
        icons = random.sample(range(len(PAIR_ICONS)), n)
        self.cards = icons + icons
        random.shuffle(self.cards)
        self.matched = {}       # card index -> when it was matched
        self.open = []
        self.moves = 0
        self.flips = {}         # card index -> (start, now face up)
        self.hide_at = None     # when a wrong pair turns back over
        self.cursor = 0
        self.show_cursor = False
        self.started = self.ended = None

    def done(self):
        return len(self.matched) == len(self.cards)

    def _flip(self, i, up, now):
        self.flips[i] = (now, up)

    def _hide(self, now):
        for i in self.open:
            self._flip(i, False, now)
        self.open = []
        self.hide_at = None

    def turn(self, i):
        now = time.monotonic()
        if self.done():
            self.reset()
            return
        if self.hide_at:  # a wrong pair is still showing: turn it back now
            self._hide(now)
        if i in self.matched or i in self.open:
            return
        self.started = self.started or now
        self.open.append(i)
        self._flip(i, True, now)
        if len(self.open) == 2:
            self.moves += 1
            a, b = self.open
            if self.cards[a] == self.cards[b]:
                self.matched[a] = self.matched[b] = now + FLIP
                self.open = []
                if self.done():
                    self.ended = now
                    self.finished = self.moves
            else:
                self.hide_at = now + 0.85

    def interval(self):
        now = time.monotonic()
        if self.hide_at or any(now - t < FLIP for t, _ in self.flips.values()) or \
                any(0 <= now - t < 0.3 for t in self.matched.values()):
            return FPS
        return 1.0 if self.started and not self.ended else None  # the clock

    def tick(self, now):
        if self.hide_at and now >= self.hide_at:
            self._hide(now)
        self.flips = {i: f for i, f in self.flips.items() if now - f[0] < FLIP}

    def _geometry(self, w, h):
        gap = 8
        cw = min((w - gap * (self.COLS + 1)) / self.COLS, 86)
        ch = min((h - gap * (self.ROWS + 1)) / self.ROWS, 86)
        bw = cw * self.COLS + gap * (self.COLS + 1)
        bh = ch * self.ROWS + gap * (self.ROWS + 1)
        return gap, cw, ch, (w - bw) / 2, (h - bh) / 2

    def draw(self, w, h, now):
        gap, cw, ch, ox, oy = self._geometry(w, h)
        out = []
        for i, card in enumerate(self.cards):
            r, c = divmod(i, self.COLS)
            x = ox + gap + c * (cw + gap)
            y = oy + gap + r * (ch + gap)
            up = i in self.matched or i in self.open
            sx = 1.0
            if i in self.flips:
                t0, to_up = self.flips[i]
                p = min(1.0, (now - t0) / FLIP)
                up = to_up if p >= 0.5 else not to_up
                sx = abs(1 - 2 * p)
            scale = 1.0
            if i in self.matched and 0 <= now - self.matched[i] < 0.3:
                scale = 1 + 0.08 * math.sin(math.pi * (now - self.matched[i]) / 0.3)
            cwi, chi = cw * max(0.04, sx) * scale, ch * scale
            cx, cy = x + cw / 2, y + ch / 2
            rx, ry = cx - cwi / 2, cy - chi / 2
            color = PAIR_COLORS[card % len(PAIR_COLORS)]
            if up:
                done = i in self.matched
                out.append(nook.rect(rx, ry, cwi, chi, radius=10,
                                     fill=with_alpha(color, 0.18 if done else 0.1),
                                     stroke=with_alpha(color, 0.5 if done else 0.9),
                                     width=1 if done else 2))
                if sx > 0.3:
                    out.append(nook.glyph(cx, cy, PAIR_ICONS[card], size=min(cwi, chi) * 0.5,
                                          fill=True, color=color))
            else:
                out.append(nook.rect(rx, ry, cwi, chi, radius=10, fill="accent"))
                out.append(nook.rect(rx + 4, ry + 4, cwi - 8, chi - 8, radius=7,
                                     stroke="#FFFFFF33", width=1))
                if sx > 0.3:
                    out.append(nook.glyph(cx, cy, "sparkle", size=min(cwi, chi) * 0.3,
                                          color="#FFFFFFAA", fill=True))
            if self.show_cursor and i == self.cursor and not self.done():
                out.append(nook.rect(x - 4, y - 4, cw + 8, ch + 8, radius=13, stroke="accent",
                                     width=2))
        if self.done() and not self.flips:
            n = 3 if self.moves <= 12 else 2 if self.moves <= 16 else 1
            stars = [nook.glyph(w / 2 + (k - 1) * 26, h / 2 + 64, "star", size=22,
                                color="yellow" if k < n else ink(0.25), fill=True) for k in range(3)]
            out += overlay(w, h, f"All pairs in {self.moves} moves",
                           f"{self._clock(now)} · Space or click to shuffle again", icon="cards",
                           extra=stars)
        return out

    def _clock(self, now):
        if not self.started:
            return "0:00"
        s = int((self.ended or now) - self.started)
        return f"{s // 60}:{s % 60:02d}"

    def key(self, k, repeat):
        d = KEY_DIRS.get(k)
        if d:
            if self.show_cursor:
                r, c = divmod(self.cursor, self.COLS)
                self.cursor = ((r + d[1]) % self.ROWS) * self.COLS + (c + d[0]) % self.COLS
            self.show_cursor = True
        elif k in ("Space", "Enter") and not repeat:
            if self.done():
                self.reset()
            elif self.show_cursor:
                self.turn(self.cursor)
            self.show_cursor = True
        elif k == "R":
            self.reset()

    def click(self, x, y, w, h):
        self.show_cursor = False
        if self.done():
            self.reset()
            return
        gap, cw, ch, ox, oy = self._geometry(w, h)
        c = int((x - ox - gap / 2) // (cw + gap))
        r = int((y - oy - gap / 2) // (ch + gap))
        if 0 <= c < self.COLS and 0 <= r < self.ROWS:
            self.cursor = r * self.COLS + c
            self.turn(self.cursor)

    def press(self, eid):
        pass

    def controls(self):
        return []

    def stats(self, now):
        found = len(self.matched) // 2
        return [("Moves", self.moves, None), ("Pairs", f"{found} / {len(self.cards) // 2}", None),
                ("Time", self._clock(now), None)]

    def keys_help(self):
        return [(["Up", "Down", "Left", "Right"], "Move"), (["Space"], "Flip"), (["R"], "Shuffle")]
