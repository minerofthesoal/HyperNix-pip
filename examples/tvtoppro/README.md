# tvtoppro themes

Every built-in theme, written out in btop's own `.theme` format. They are
here to be copied and edited — a theme is data, not code, and starting
from one that already works beats starting from the key list.

```bash
tvtoppro --theme gruvbox-dark              # by name, no file needed
tvtoppro --theme ./nord.theme              # from a file
tvtoppro --theme ~/.config/btop/themes/x.theme   # btop's own, unchanged
tvtoppro --list-themes
```

## Making your own

`--dump-theme` writes the active theme out, which is the quickest start:

```bash
tvtoppro --theme nord --dump-theme > mine.theme
$EDITOR mine.theme
tvtoppro --theme ./mine.theme
```

A partial file is a valid theme. Anything you leave out inherits from the
default, so a file with three lines in it changes three colours:

```
theme[cpu_start]="#00ff9c"
theme[cpu_mid]="#ffd166"
theme[cpu_end]="#ef476f"
```

## The keys that matter most

The `_start` / `_mid` / `_end` triples are gradients, and they are what
give the meters and graphs their look. A bar takes its colour per *cell*
from its own position along the ramp, so all three ends show at once on a
full bar.

| Prefix | Used by |
|---|---|
| `cpu_*` | the CPU meter and graph, and the GPU meter |
| `used_*` | RAM used, VRAM used |
| `available_*` | RAM available |
| `free_*` | cache, and the training progress bar and loss curve |
| `temp_*` | GPU temperature |

The rest are flat colours: `main_fg` for numbers, `inactive_fg` for
labels, `graph_text` for the dim right-hand annotations, `div_line` for
the box borders, `hi_fg` for the row headings, `meter_bg` for the unfilled
part of a bar, and `cpu_box` / `mem_box` / `net_box` / `proc_box` for each
panel's border.

## Colour formats

`#RRGGBB`, and btop's two-digit greyscale shorthand `#XX` — `#40` is a
mid-dark grey, not `#400000`. Both are accepted, which is what lets
btop's own theme files load unchanged.

## `mono`

For a terminal without truecolor, and for a screenshot that has to
survive being printed. Every ramp is grey, so the meters still read as
meters when the hue is gone.
