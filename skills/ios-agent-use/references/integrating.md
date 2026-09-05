# Integrating with an existing project

## 1. The driver file

Copy `driver/AgentDriverUITests.swift` into your UI test target's directory.

It is inert unless driven: with no `IOSAGENT_SCRIPT_B64` in its environment it
throws `XCTSkip`, so `xcodebuild test` behaves exactly as before. Verify that —
run your suite once after adding it and confirm the count moves by one skip and
nothing else.

If your project uses Xcode 16 folder groups
(`PBXFileSystemSynchronizedRootGroup`), dropping the file in the folder is the
whole job. Otherwise add it to the UI test target in Xcode.

## 2. `.iosagent.json`

`iosagent init` writes a starter. The keys that matter:

| key | |
|---|---|
| `project` / `workspace` | path relative to the config file |
| `scheme` | must build both the app and the UI test target |
| `bundle_id` | the app under test |
| `ui_test_target` | e.g. `MyAppUITests` |
| `driver_class` | `AgentDriverUITests` unless you renamed it |
| `build_wrapper` | a script to call instead of `xcodebuild` — see below |
| `artifacts` | where runs are written; default `~/.iosagent/runs` |
| `targets` | named destinations, each `{"kind": "device"\|"simulator", "name": …}` |
| `launch` | default launch `args` and `env` |

## 3. Seeding state

Drive whatever fixture mechanism the app already has rather than inventing a
second one. If the app checks a launch argument to load test fixtures, put it in
`launch.args`; if it reads a scenario name from the environment, put that in
`launch.env`. Remember these apply only with `"mode": "launch"`.

Two things worth checking in the app you are wiring up:

- **Does a UI-testing flag disable deep links?** Many apps guard `.onOpenURL`
  when under test. If so, `iosagent open` and the test flag are mutually
  exclusive, and you navigate by tapping instead.
- **Are host-path fixtures simulator-only?** A simulator process runs as your
  user and can read any host path; a device cannot. On device, use
  `iosagent push` to place fixtures in the app container.

## 4. Build wrappers

If your repo already wraps `xcodebuild` — to pin DerivedData, enforce a
destination, or set signing — point `build_wrapper` at it and `iosagent` will
call it instead, appending its own arguments. It never passes
`-derivedDataPath` in that case; your wrapper stays in charge.

Without a wrapper, `iosagent` pins one reused DerivedData directory at
`~/Library/Developer/Xcode/DerivedData/<project>-iosagent` and refuses to build
if that path is under `/tmp` or inside an iCloud- or Dropbox-synced folder.
Both refusals are deliberate:

- A fresh `-derivedDataPath /tmp/<unique>` per run leaves orphaned build output
  that macOS reports only as "System Data". This is not hypothetical: 563 such
  directories once accumulated to 215 GB.
- A synced folder's file provider stamps `com.apple.FinderInfo` on built
  bundles, after which codesign fails with *"resource fork, Finder information,
  or similar detritus not allowed"* — but only during `test`, never during
  `build`, so it presents as flakiness rather than as a configuration error.

## 5. Signing for device runs

A device run signs the app, the UI test bundle, and any embedded extensions —
the test bundle needs its own App ID. Automatic signing handles this if the
device is registered to the team; `iosagent build` passes
`-allowProvisioningUpdates` so Xcode can create what is missing.

## 6. Accessibility identifiers

The tool is only as good as the identifiers in the app. An element with neither
an identifier nor a label is counted in the diff but not named, which is close to
useless to an agent. Adding `.accessibilityIdentifier("library.new")` to the
things you want to drive is the single highest-value change you can make.
