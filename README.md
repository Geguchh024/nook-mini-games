# Mini Games

> Four small original games in your notch: **Comet**, **Doubles**, **Reflex**
> and **Pairs**. Each takes about a minute to play, and your best scores are
> saved.

![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![Python](https://img.shields.io/badge/python-3.8%2B-3776AB)
![Version](https://img.shields.io/badge/version-1.1.0-7C5CFF)
![Plugin for](https://img.shields.io/badge/plugin%20for-Nook%20%2F%20Fenn-111)

A plugin for **Nook**, the floating notch for Windows (and its successor
**Fenn**). The games are drawn on the page's canvas and played with the
keyboard or the mouse. There is nothing to install.

| | |
|---|---|
| **Tile** | small |
| **Page** | 660 × 420 |
| **Controls** | Arrow keys or WASD, `Space`, `Tab`, or the mouse |
| **Dependencies** | none |

## Install

Clone the repo into your plugins folder. The folder name must be `mini-games`:

```powershell
# Nook
git clone https://github.com/Geguchh024/nook-mini-games "$env:APPDATA\Nook\plugins\mini-games"
# Fenn
git clone https://github.com/Geguchh024/nook-mini-games "$env:APPDATA\Fenn\plugins\mini-games"
```

You can also download the ZIP and extract it to the same place.

## The games

Pick a game with the chips at the top, the number keys `1`–`4`, or `Tab` /
`Shift+Tab`. The board takes the keyboard while the page is open, and the
notch stays open while you play.

### 1 · Comet

Steer a comet to collect stars; its tail grows with each one. The edges wrap
around, so only your own tail can stop you. It speeds up as you score, and
every fifth star drops a pink diamond worth extra points for a few seconds.

- **Keys:** Arrows or WASD steer, `Space` pauses, `R` restarts
- **Mouse:** click above, below or ahead of the comet
- **Best:** highest score

### 2 · Doubles

Slide every tile one way; two equal tiles merge into their sum. The round
ends when nothing can move.

- **Keys:** Arrows or WASD slide, `U` takes back a move (3 per game), `R` starts a new board
- **Mouse:** click a side of the board
- **Best:** highest score

### 3 · Reflex

Wait for the panel to turn green, then react as fast as you can. There are
five rounds, and reacting early repeats the round.

- **Keys:** `Space` or `Enter`
- **Mouse:** click
- **Best:** lowest average (ms)

### 4 · Pairs

Turn over two cards at a time and find all nine pairs. A clock runs from the
first card, and finishing in 12 moves or fewer earns three stars.

- **Keys:** Arrows move the cursor, `Space` flips, `R` shuffles
- **Mouse:** click a card
- **Best:** fewest moves

## Notes

- The plugin only ticks while something on the board moves, and only while
  the page is open. Closing the page pauses Comet.
- Reflex times include a few milliseconds of drawing delay. It's the same for
  every round, so results stay comparable.
- Best scores are kept in `best.json` in
  `%APPDATA%\Nook\plugin-data\mini-games`.

## Files

| File | What it is |
|---|---|
| `main.py` | Game picker, input handling and the tile |
| `games.py` | The four games: logic and canvas drawing |
| `nook.py` | The Nook plugin helper |
| `plugin.toml` | Plugin manifest |

## Requirements

- Windows 10 or 11
- Python 3.8+ on `PATH` as `python`
