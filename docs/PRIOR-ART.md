# Prior art

**gstack `ios-qa`** (github.com/garrytan/gstack, MIT) takes the opposite
approach: a DEBUG-only HTTP server compiled *into* the app, reached over the
CoreDevice USB tunnel, with a Mac-side daemon. That buys lower latency per
action and a read of the app's own model state. The costs are that it modifies
the app, its touch layer is a KIF port that calls private UIKit and IOKit
selectors (fine for DEBUG, fatal if it ever reaches a Release build), it is
device-only, and it needs `bun` and a running daemon. Two operational details
documented there are worth knowing regardless of which tool you use: Xcode 26's
CoreDevice tunnel drops after 10-15s idle unless something keeps it warm, and
SwiftUI `Button` hit-testing needs the iOS 18+ `_UIHitTestContext` path.

**WebDriverAgent / Appium** run an XCUITest target as a long-lived HTTP server on
the device, reached over a usbmuxd port forward. That is the mature answer for
cross-platform test automation at scale. It is also a large dependency, needs its
own signing and provisioning, and is more machinery than a single agent driving a
single app needs.

**KIF** pioneered in-process touch synthesis on iOS and is where essentially every
private-API touch injector descends from.

**`idb`** (Meta) wrapped device and simulator control behind one CLI. Much of what
it offered on device is now covered by `devicectl`, which is why this tool has no
third-party runtime dependency.

This project is deliberately the complement to the first of those: external
rather than in-app, public API rather than private, simulator *and* device, and
built around reporting what changed rather than around low-latency remote
control.
