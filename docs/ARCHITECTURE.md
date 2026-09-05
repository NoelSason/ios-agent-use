# Architecture

Two planes. Nothing runs between batches.

```
Mac (control)                                iPad / Simulator
────────────────────────────────────────────────────────────────
iosagent build    ──►  xcodebuild (+ build-for-testing)
iosagent install  ──►  devicectl install app | simctl install
iosagent launch   ──►  devicectl process launch | simctl launch
iosagent run      ──►  xcodebuild test-without-building
                         │  TEST_RUNNER_IOSAGENT_SCRIPT_B64
                         ▼
                       AgentDriverUITests executes the script,
                       attaching a screenshot + accessibility
                       snapshot after every step
                  ◄──  .xcresult ─ xcresulttool export attachments
iosagent snap     ◄──  devicectl capture screenshot   (~1s, no test run)
iosagent diff     ──►  pixel + tree diff ─► report.md
```

## Why a batch instead of a live session

A long-lived on-device server (WebDriverAgent, or an in-app HTTP bridge) gives
lower per-action latency and costs a permanent dependency: a daemon, a transport
that has to survive Xcode's tunnel dropping every 10-15 seconds idle, and either
private APIs or a second signed bundle.

The batch transport is two mechanisms Xcode already guarantees: `xcodebuild`
forwards `TEST_RUNNER_`-prefixed environment variables into the runner, and
`XCTAttachment`s come back inside the result bundle. Nothing to keep alive,
nothing to reconnect, nothing to clean up if the run dies.

The cost is a fixed ~13-20s per batch on device. Since that cost is per *batch*
and not per step, and since `activate` preserves app state between batches, the
practical effect is a session with an occasional pause rather than a slow REPL.

## Coordinate spaces

Three, and conflating them is the main source of confusion:

| space | what |
|---|---|
| points | accessibility frames, and what a tap consumes |
| native pixels | what `XCUIScreen` captures — the raw framebuffer, always in the device's natural orientation |
| comparison pixels | the downscaled copy the pixel diff runs on |

`XCUIScreen.main.screenshot()` returns the *native* framebuffer, which stays
portrait however the interface is rotated, so a landscape screenshot arrives
sideways. The driver reports `UIDevice` orientation alongside the image; the host
rotates the file with `sips` before anything else touches it. Every coordinate in
a report is then in points, matching the accessibility frames.

`app.screenshot()` would arrive correctly oriented but omits anything presented
outside the application element — popovers, sheets, alerts — which is precisely
what you are usually trying to observe.

## Why the tree diff matters more than the image

A pixel diff answers "did something change". An agent needs "what is there now,
and what can I tap". The accessibility snapshot is walked into JSON on device,
flattened on the host, and diffed by identity — identifier first, then label,
then tree position, so an element that moves is reported as moved rather than as
one destroyed and one created.

Two refinements make the output usable rather than merely correct:

- Elements with no identifier and no label are counted, not listed. A popover
  adds forty anonymous containers and none of them mean anything.
- When a modal appears, everything behind it leaves the accessibility tree. The
  raw diff reads as "seventy elements destroyed". The diff detects the covering
  element and says what actually happened instead.

## Pixel diff

Both images are lossless PNGs from the same renderer, so matching regions are
near bit-identical and only resampling introduces drift. The threshold is
therefore deliberately low: a dark-themed interface changes by very few levels
per channel, and a mean-based test misses an entire popover against a black
background. Tiles are 16×16 on an 800px-longest-side copy; a tile is dirty when
more than 2% of its sampled pixels differ by more than 6 levels on any channel.
Dirty tiles are grouped into rectangles so the report names areas rather than
confetti.
