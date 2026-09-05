# ios-agent-use

Let a coding agent drive a real iOS app — on a physical device or a simulator —
and then tell it, in words, what changed on screen.

Agents can already write Swift. What they cannot usually do is *check*: build the
change, open the app, tap the thing, and see whether the editor actually opened.
This closes that loop with nothing but the tooling Xcode already ships.

```console
$ iosagent run 'tap library.new' 'waitFor editor.canvas'
driving device:iPad Pro 13-inch — 2 step(s)
report: ~/.iosagent/runs/myapp/20260905-124055/report.md
PASSED in 13s (3 observations)
```

```markdown
## step 1 · tap
pixels   7.2% changed in 3 region(s) — (963,82 302×357pt), (467,165 55×55pt)
tree     +24 −72 ~1
  ! a modal appeared (Other "dismiss popup"); 72 background element(s) became
    inaccessible rather than being destroyed
  + Button "Notebook"       @ (1006,113 250x51)
  + Button "Whiteboard"     @ (1006,165 250x51)
  + Button "Record Lecture" @ (1006,375 250x51)
```

That report — not the screenshot — is the point. A picture says *something*
changed. This says which elements appeared, where, and what they are called, so
the agent can decide what to tap next instead of guessing at pixels.

## What it does not require

- **No code in your app.** Nothing is imported, linked, or `#if DEBUG`-ed into the
  binary you ship. One file goes into your *UI test* target and skips itself
  unless it is being driven.
- **No private APIs.** Public XCUITest, `devicectl`, `simctl`, `xcresulttool`.
- **No daemon, no server, no port forwarding, no Appium, no `bun`, no `pip`.**
  Python 3 from the standard library, and Xcode.

## Install

### As a Claude Code plugin (recommended)

```
/plugin marketplace add NoelSason/ios-agent-use
/plugin install ios-agent-use@ios-agent-use
```

That registers the `ios-agent-use` skill, so an agent knows when to reach for
this and how to read what comes back. The CLI ships with it at
`${CLAUDE_PLUGIN_ROOT}/bin/iosagent`.

### As a CLI

```bash
curl -fsSL https://raw.githubusercontent.com/NoelSason/ios-agent-use/main/install.sh | bash
```

Clones to `~/.ios-agent-use`, links `iosagent` into `~/.local/bin`, and
registers the skill if `~/.claude` exists. Or clone it yourself:

```bash
git clone https://github.com/NoelSason/ios-agent-use.git
cd ios-agent-use && ./install.sh
```

### Then, once per project

```bash
cd your-app-project
iosagent init                     # writes .iosagent.json
iosagent driver YourAppUITests/   # copies the driver into your UI test target
iosagent doctor
```

`doctor` checks the toolchain, the project, and which devices are reachable, and
tells you what is missing. Requirements: macOS, Xcode, Python 3. That is all —
there is nothing to `pip install` and nothing to keep running.

## The loop

```bash
iosagent build                       # app + test bundle
iosagent run 'tap library.new' 'waitFor editor.canvas' 'drag @.3,.4 @.7,.6'
iosagent snap                        # just a screenshot, ~1s, no test run
iosagent diff <stepA> <stepB>
```

One `run` is one `xcodebuild test-without-building`, which costs about 13-20s on
a device regardless of how many steps are in it — so put twenty steps in a batch,
not one. Between batches the app is `activate`d rather than relaunched, so state
survives and a sequence of batches behaves like one session.

## Design → build → check

Hand it a design file and compare it against what the device actually renders:

```bash
iosagent design mock.dc.html --out reference.png    # headless Chrome
iosagent run 'tap library.new'                       # build your screen, then look
iosagent compare mock.dc.html ~/.iosagent/runs/app/latest/steps/002
```

`compare` produces a side-by-side composite at matched scale, a dominant-colour
table for both sides, and a check of every string in the design against the
accessibility labels on the built screen. Colour and text are checked
objectively; whether the layout is right is left to your eyes, because a mockup
and a real screen legitimately differ in fonts, insets, and safe areas.

## Commands

| | |
|---|---|
| `init` `doctor` `targets` | set up, verify, discover |
| `build` `install` `launch` `terminate` | lifecycle |
| `run` `snap` `diff` | the loop |
| `design` `compare` | design-to-screen |
| `open` `push` `pull` `logs` | deep links, app-container files, logs |
| `clean` | prune old run artifacts |

## What it cannot do

Read [docs/LIMITATIONS.md](docs/LIMITATIONS.md) before you rely on it. The short
version: no Apple Pencil, no curved strokes, no audio verification, and dense
accessibility trees are slow.

## Licence

MIT. See [docs/PRIOR-ART.md](docs/PRIOR-ART.md) for related work.
