# Limitations

Stated up front, because the failure mode of a tool like this is an agent
confidently reporting that something works when it was never actually checked.

## Input

- **No Apple Pencil.** There is no public API to synthesize a `.pencil` touch,
  or any pressure, altitude or azimuth. Everything the driver draws is finger
  input. If your app behaves differently for Pencil — and a drawing app does —
  that difference is not covered here.
- **No curved strokes.** Public XCUITest offers `press(forDuration:thenDragTo:)`,
  which is a straight line. A polyline is N separate gestures with a pen-lift
  between each. For a canvas app this is the single biggest gap and it cannot be
  closed without private APIs.
- **`type` needs a focused text input.** It taps the element first, but a field
  that refuses first-responder status will silently receive nothing.
- **No multi-finger gestures beyond pinch and rotate**, and no 3D Touch.

## Observation

- **Screenshots arrive in the device's native orientation.** `XCUIScreen`
  captures the raw framebuffer, which stays portrait however the interface is
  rotated. The host rotates it back using the reported device orientation. If a
  screenshot ever comes out sideways, that is where to look.
- **The accessibility tree is not the view hierarchy.** Elements behind a modal
  are reported as gone, not hidden — the driver detects this case and says so
  rather than listing eighty removals, but the underlying limitation stands.
- **Elements without an identifier or a label are invisible to the diff.** They
  are counted, not listed. Add accessibility identifiers to anything you want to
  address or assert on.
- **Dense trees are slow.** A screen where every word is its own element can take
  tens of seconds to snapshot. Scope your queries by element type, and lower
  `tree_depth` when you do not need the leaves.

## Timing

- **About 13-20s per batch on a device**, dominated by launching the test runner,
  not by the steps. Batch aggressively.
- **The device must be unlocked.** A locked device will prompt for its passcode
  and the run will block until someone enters it.
- **One session at a time.** No parallel devices, no concurrent runs against the
  same target.

## Not covered at all

- **Audio.** Routing, interruptions, background capture, and whether a recording
  actually sounds right are not testable this way.
- **Memory pressure, jetsam, and thermal state** under real load.
- **Anything requiring the camera, a phone call, or physically unplugging a cable.**

## Comparison against a design

`compare` checks colour and text objectively. It does not check layout, spacing,
or hierarchy, and it deliberately does not pixel-diff a mockup against a
screenshot: fonts, insets and safe areas differ legitimately, so a pixel score
would be noise dressed up as a number.
