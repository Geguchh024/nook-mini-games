"""Mini Games: four small original games drawn on a canvas on the page
(Comet, Doubles, Reflex, Pairs), played with the keyboard or clicks. Best
scores are kept in NOOK_DATA_DIR. A game only gets ticks while something on
it moves (and the page is open), so the plugin idles at no CPU."""

import threading
import time

import games
import nook

app = nook.Plugin()
GAMES = [games.Comet(), games.Doubles(), games.Reflex(), games.Pairs()]
best = app.load("best", {})          # game name -> best score
ui = {"game": app.load("last_game", 0) % len(GAMES), "w": 616, "h": 330, "new_best": False}
PANEL, GAP = 156, 10                 # side panel width, and its gap from the board


def post(message):
    app._inbox.put(message)


GAMES[2].post = post


def current():
    return GAMES[ui["game"]]


def best_text(g):
    b = best.get(g.name)
    if b is None:
        return "None yet"
    return {"Comet": f"{b} points", "Doubles": f"{b} points", "Reflex": f"{b} ms average",
            "Pairs": f"{b} moves"}[g.name]


def record():
    """Stores a finished round's score if it beats the best."""
    g = current()
    if g.finished is None:
        return
    score, g.finished = g.finished, None
    old = best.get(g.name)
    if old is None or (score < old if g.lower_is_better else score > old):
        best[g.name] = score
        app.save("best", best)
        ui["new_best"] = True
        if not app.page_open:
            app.badge_glyph("trophy")


# Frame clock: one thread that wakes the main loop when the game asks for it ------------------

clock = {"wake": threading.Event(), "pending": False}


def due():
    try:
        return current().interval() if app.page_open else None
    except RuntimeError:  # read mid-change by the main thread: look again soon
        return games.FPS


def run_clock():
    wake = clock["wake"]
    while True:
        iv = due()
        if iv is None:
            wake.wait()
        elif not wake.wait(iv) and not clock["pending"]:
            clock["pending"] = True
            post({"type": "x-tick"})
        wake.clear()


def sync_clock():
    """Call after anything that may start or stop movement."""
    clock["wake"].set()


threading.Thread(target=run_clock, daemon=True).start()


# Views --------------------------------------------------------------------------------------

def board_width():
    return ui["w"] - PANEL - GAP if ui["w"] >= 420 else ui["w"]


def tile_view():
    g = current()
    if app.tile_size in ("wide", "large"):
        return nook.row([
            nook.icon(g.icon, size=24, color="accent", fill=True),
            nook.column([nook.text(g.name, size="small", color="dim", bold=True),
                         nook.text(f"Best {best_text(g)}" if g.name in best else "Play")], gap=0),
        ], gap=8, align="center", tooltip="Mini games")
    return nook.column([nook.icon("game-controller", size=26, color="accent")],
                       align="center", justify="center", tooltip="Mini games")


def canvas_shapes():
    games.theme.update(dark=app.dark, accent=app.accent)
    g, now = current(), time.monotonic()
    bw, h = board_width(), ui["h"]
    shapes = g.draw(bw, h, now)
    if bw < ui["w"]:
        shapes += games.side_panel(bw + GAP, PANEL, h, g, best_text(g), ui["new_best"], now)
    return shapes


def page_view():
    g = current()
    return nook.column([
        nook.row([
            nook.chips("game", [x.name for x in GAMES], selected=ui["game"]),
            nook.spacer(),
            *g.controls(),
            nook.button("new", icon="arrow-clockwise", tooltip="New game (R)"),
        ], gap=4, align="center"),
        nook.canvas(ui["h"], canvas_shapes(), width=ui["w"], id="board", keys=True),
    ], gap=6)


def draw_page():
    app.page(page_view())


def draw():
    app.tile(tile_view())
    draw_page()


# Events -------------------------------------------------------------------------------------

def leave_game():
    """Pauses what shouldn't run in the background."""
    g = current()
    if isinstance(g, games.Comet):
        g.pause()
    if isinstance(g, games.Reflex) and g.phase in ("waiting", "go"):
        g.reset()


def switch(index):
    leave_game()
    ui["game"] = index % len(GAMES)
    ui["new_best"] = False
    app.save("last_game", ui["game"])
    draw()


def on_key(value):
    k, repeat = value.get("key", ""), bool(value.get("repeat"))
    if k == "Tab":
        switch(ui["game"] + (-1 if value.get("shift") else 1))
        return
    if k in ("1", "2", "3", "4"):
        switch(int(k) - 1)
        return
    if k in ("R", "N"):
        ui["new_best"] = False
        current().reset()
    else:
        current().key(k, repeat)
    record()
    draw_page()


@app.on_message("event")
def _(ev):
    eid, kind, value = ev.get("id", ""), ev.get("kind"), ev.get("value")
    g = current()
    if eid == "game" and kind == "change":
        switch(int((value or {}).get("index", 0)))
    elif eid == "board" and kind == "key" and isinstance(value, dict):
        on_key(value)
    elif eid == "board" and isinstance(value, dict):
        x, y = float(value.get("x", 0)), float(value.get("y", 0))
        if x <= board_width():
            g.click(x, y, board_width(), ui["h"])
            record()
            draw_page()
    elif eid == "new":
        leave_game()
        g.reset()
        ui["new_best"] = False
        draw_page()
    else:
        g.press(eid)
        record()
        draw_page()
    sync_clock()


@app.on_message("x-tick")
def _(msg):
    clock["pending"] = False
    g = current()
    if due() is None:
        sync_clock()
        return
    g.tick(time.monotonic())
    record()
    draw_page()
    sync_clock()


@app.on_message("x-go")
def _(msg):
    g = current()
    if isinstance(g, games.Reflex) and g.phase == "waiting":
        g.go()
        draw_page()
        g.go_at = time.monotonic()  # timed from the moment the green frame is sent


@app.on_message("layout")
def _(msg):
    if msg.get("target") == "page" and msg.get("width"):
        ui["w"] = max(240, int(msg["width"]))
        ui["h"] = max(180, int(msg.get("height", 366)) - 36)  # minus the chips row
    draw()


@app.on_message("theme")
def _(msg):
    draw()


@app.on_message("page_open")
def _(msg):
    app.clear_badge()
    sync_clock()


@app.on_message("page_close")
def _(msg):
    leave_game()
    sync_clock()
    draw_page()


draw()
app.run()
