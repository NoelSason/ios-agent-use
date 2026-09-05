---
name: ios-agent-use
description: Drive a real iOS app on a physical device or simulator and see what changed — build, install, tap/type/drag, then read a structured diff of the screen and accessibility tree. Use when asked to try a change in the running app, verify a UI change on device, reproduce a UI bug, check that a screen loads, implement a design file and confirm it renders, or capture screenshots from an iPad or iPhone. Triggers on "on my iPad", "on device", "run the app and check", "does this actually work", "implement this design", "screenshot the app".
---

# ios-agent-use

Close the loop between writing Swift and knowing whether it worked.

The CLI lives at `~/Desktop/iOS-Agent-Use/bin/iosagent`. Run it from the project
root — it finds `.iosagent.json` by walking up.

## Before anything else

```bash
iosagent doctor
```

It reports the toolchain, the project config, and which devices are reachable.
If no device is connected, switch to the simulator target rather than failing:
`iosagent -t sim …`.

## The loop

```bash
iosagent build                                   # app + test bundle
iosagent run 'tap library.new' 'waitFor editor.canvas'
```

`run` prints the path to a `report.md`. **Read that report** — it is the point of
the tool. Each step gets:

- `pixels` — how much of the screen changed, and where, in points
- `tree` — which accessibility elements appeared, disappeared, or changed
- a downscaled `view.png` you can Read directly

The tree diff is what you reason over. `+ Button "Record Lecture" @ (1006,375
250x51)` tells you what to tap next. The screenshot is for judging whether it
*looks* right.

At the end the report lists what is tappable now — use those identifiers for the
next batch instead of guessing.

## Batch aggressively

One `run` costs about 13-20s on a device no matter how many steps it contains,
because the cost is launching the test runner. **Twenty steps in one batch is the
same price as one.** Never write a loop of single-step runs.

Between batches the app is `activate`d rather than relaunched, so state persists
and consecutive batches behave like one session. Pass `--mode launch` when you
deliberately want a clean start (and note that launch `args`/`env` only apply
then).

## Just looking

```bash
iosagent snap            # ~1s screenshot, no test run, no app changes
iosagent open <url>      # deep link
iosagent pull <path>     # a file out of the app container
iosagent logs
```

`snap` is the cheap way to answer "what is on screen right now".

## Implementing a design

When handed a design file (`.dc.html`, `.html`) and asked to build it:

1. `iosagent design mock.dc.html --out reference.png` — render it, then Read the
   PNG so you know what you are building.
2. Write the SwiftUI. Give every meaningful view an
   `.accessibilityIdentifier(...)` as you go — without them the next step is
   nearly blind.
3. `iosagent build && iosagent run 'waitFor <your.root.identifier>'` — confirm it
   loads at all before judging how it looks. A blank screen and a wrong screen
   look identical in a palette table.
4. `iosagent compare mock.dc.html <run>/steps/001` — a side-by-side composite,
   a dominant-colour table for both sides, and every string in the design checked
   against the labels on the built screen.
5. Read the composite. Colour and text are checked for you; layout, spacing and
   hierarchy are your judgement.

Do not report a design as implemented on the strength of the colour table alone.

## Writing steps

Shorthand covers most of it:

```bash
iosagent run 'tap library.new' 'wait 1' 'type note.title Organic Chemistry' \
             'drag @0.3,0.4 @0.7,0.6' 'assertExists editor.canvas'
```

For anything longer, write a plan file and use `-f`. Full grammar and the action
list: `docs/ACTIONS.md` in the repo.

Prefer identifiers over coordinates, and name a `type` when you can
(`tap button:save`) — an untyped query walks the whole tree and can take tens of
seconds on a dense screen.

## When a step fails

The batch stops at the first failure, because everything after it would be
observing a state that was never reached. The report names the step and the
error. Common causes, in order of likelihood:

- the identifier does not exist — check the "what is tappable now" list from the
  previous run's report
- the element exists but is not hittable — something is covering it, or it needs
  a `scrollTo` first
- the screen had not settled — add a `waitFor` rather than a `wait`
- the driver skipped entirely — `AgentDriverUITests.swift` is not in the UI test
  target, or `driver_class` does not match

## Rules

- **Never pass `-derivedDataPath` under `/tmp`**, and never let build output land
  in an iCloud-synced folder. The tool refuses both; do not work around it.
- **Artifacts live outside the repo** (`~/.iosagent/runs`). Do not move them into
  a synced project directory.
- The device must be **unlocked**, or the run blocks on a passcode prompt.
- Run `iosagent clean` occasionally; screenshots accumulate.

## Honest limits

No Apple Pencil input, and no curved strokes — public XCUITest drags are
straight lines. Audio, memory pressure and thermal behaviour are not testable
this way. If asked to verify any of those, say so rather than reporting a pass.
Full list: `docs/LIMITATIONS.md`.
