# Action reference

A plan is JSON. `iosagent run -f plan.json` executes it; `iosagent run 'tap x'`
builds a one-off plan from the shorthand grammar.

```json
{
  "launch": {
    "mode": "activate",
    "args": ["MYAPP_UI_TESTING"],
    "env":  {"MYAPP_SCENARIO": "library"}
  },
  "capture": {"after_every_step": true, "screenshot": true,
              "tree": true, "tree_depth": 60},
  "steps": [
    {"action": "tap", "id": "library.new"},
    {"action": "waitFor", "id": "editor.canvas", "timeout": 10},
    {"action": "drag",
      "from": {"id": "editor.canvas", "norm": [0.3, 0.4]},
      "to":   {"id": "editor.canvas", "norm": [0.7, 0.6]}, "duration": 0.4},
    {"action": "assertLabel", "id": "editor.title", "text": "Untitled"}
  ]
}
```

## launch.mode

| mode | effect |
|---|---|
| `activate` (default) | bring the running app forward, keeping its state. This is what makes consecutive batches behave like one session. |
| `launch` | relaunch from scratch, applying `args` and `env`. |
| `none` | touch nothing; drive whatever is already on screen. |

`args` and `env` only take effect on `launch` — iOS cannot change a running
process's launch environment.

## Selectors

Every action that needs an element accepts these, either inline or under
`target` / `from` / `to`:

| key | meaning |
|---|---|
| `id` | accessibility identifier — the stable one, always prefer it |
| `label` | substring match, case-insensitive |
| `type` | `button`, `staticText`, `textField`, `cell`, `image`, `switch`, `scrollView`, … |
| `index` | disambiguate among several matches (default: first) |
| `norm` | `[u, v]` fraction of the element, or of the screen when no element is named |
| `point` | `[x, y]` offset in points from the element's origin |

Naming a `type` narrows the search. An untyped query walks the whole tree, which
on a dense screen can take tens of seconds.

## Actions

| action | parameters | notes |
|---|---|---|
| `tap` | selector | falls back to a coordinate tap when given `norm`/`point` |
| `doubleTap` | selector | |
| `longPress` | selector, `duration` | default 1.0s |
| `type` | selector, `text` | taps to focus first if not already focused |
| `clear` | selector | deletes the current value character by character |
| `drag` | `from`, `to`, `duration` | a straight line — see LIMITATIONS |
| `swipe` | selector, `direction`, `velocity` | `up`/`down`/`left`/`right` |
| `pinch` | selector, `scale`, `velocity` | scale > 1 zooms in |
| `rotate` | selector, `value`, `velocity` | radians |
| `scrollTo` | selector, `direction`, `count`, `from` | swipes until hittable, `count` attempts |
| `wait` | `seconds` | |
| `waitFor` | selector, `timeout` | fails the step if it never appears |
| `waitGone` | selector, `timeout` | fails if it is still there |
| `assertExists` | selector | |
| `assertLabel` | selector, `text` | substring match |
| `screenshot` / `dumpTree` | `name` | explicit capture points; capture happens after every step anyway |
| `activate` / `terminate` / `relaunch` | | |
| `rotateDevice` | `value` | `portrait`, `landscape`, `landscapeRight`, `portraitUpsideDown` |
| `pressHome` | | |

A failing step ends the batch — every later step would be observing a state that
was never reached.

## Shorthand grammar

```
tap library.new              →  {"action":"tap","id":"library.new"}
tap @0.5,0.25                →  {"action":"tap","norm":[0.5,0.25]}
tap button:save              →  {"action":"tap","type":"button","id":"save"}
type note.title Hello there  →  {"action":"type","id":"note.title","text":"Hello there"}
wait 2.5                     →  {"action":"wait","seconds":2.5}
swipe library.list down      →  {"action":"swipe","id":"library.list","direction":"down"}
drag @0.2,0.3 @0.8,0.7       →  {"action":"drag","from":…,"to":…}
```

Anything more elaborate than this belongs in a plan file.
