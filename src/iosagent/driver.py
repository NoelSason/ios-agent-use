"""Send an action script to the device, bring observations back.

The transport is deliberately boring, because boring is what survives Xcode
upgrades: the script goes out as a base64 environment variable that xcodebuild
forwards into the test runner, and the observations come back as XCTAttachments
inside the .xcresult. No sockets, no port forwarding, no daemon, nothing
running between batches.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import build, png
from .config import Config
from .targets import Target

MAX_SCRIPT_BYTES = 64 * 1024
ATTACHMENT_RE = re.compile(r"^iosagent-(?P<seq>\d{3}|result)-?(?P<kind>[a-z]*)")
VIEW_MAX_DIM = 1200


class DriverError(Exception):
    pass


@dataclass
class StepArtifacts:
    index: int
    action: str
    ok: bool
    ms: int = 0
    error: str | None = None
    note: str | None = None
    screenshot: Path | None = None
    view: Path | None = None
    tree: Path | None = None


@dataclass
class RunOutcome:
    ok: bool
    run_dir: Path
    steps: list[StepArtifacts] = field(default_factory=list)
    screen_size: tuple[float, float] = (0.0, 0.0)
    image_size: tuple[float, float] = (0.0, 0.0)
    seconds: float = 0.0
    message: str = ""

    def step(self, index: int) -> StepArtifacts | None:
        return next((s for s in self.steps if s.index == index), None)


def encode_script(plan: dict) -> str:
    payload = json.dumps(plan, separators=(",", ":")).encode()
    if len(payload) > MAX_SCRIPT_BYTES:
        raise DriverError(
            f"action script is {len(payload)} bytes; the environment-variable "
            f"transport caps at {MAX_SCRIPT_BYTES}. Split it into several batches."
        )
    return base64.b64encode(payload).decode()


def new_run_dir(cfg: Config, label: str = "") -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{label}" if label else stamp
    path = cfg.artifacts_root / name
    (path / "steps").mkdir(parents=True, exist_ok=True)
    latest = cfg.artifacts_root / "latest"
    latest.unlink(missing_ok=True)
    try:
        latest.symlink_to(path, target_is_directory=True)
    except OSError:
        pass
    return path


def run(cfg: Config, target: Target, plan: dict, *, label: str = "",
        keep_xcresult: bool = False, timeout: int = 1800) -> RunOutcome:
    if not cfg.ui_test_target:
        raise DriverError(
            "`ui_test_target` is not set in .iosagent.json, so there is no test "
            "target to drive. Add the UI test target's name."
        )

    run_dir = new_run_dir(cfg, label)
    (run_dir / "plan.json").write_text(json.dumps(plan, indent=2))
    xcresult = run_dir / "raw.xcresult"

    env = {
        "TEST_RUNNER_IOSAGENT_SCRIPT_B64": encode_script(plan),
        "TEST_RUNNER_IOSAGENT_BUNDLE_ID": cfg.bundle_id,
    }
    args = [
        "-destination", target.destination(),
        "-only-testing:" + f"{cfg.ui_test_target}/{cfg.driver_class}",
        "-resultBundlePath", str(xcresult),
        "test-without-building",
    ]

    began = time.time()
    proc = build.run_xcodebuild(cfg, args, env=env, timeout=timeout)
    elapsed = time.time() - began

    if not xcresult.exists():
        tail = (proc.stdout + proc.stderr)[-3000:]
        raise DriverError(
            "the test run produced no result bundle. Usually this means the app "
            "was not built for this destination -- run `iosagent build` first.\n\n"
            + tail
        )

    outcome = collect(xcresult, run_dir)
    outcome.seconds = elapsed
    if not keep_xcresult:
        shutil.rmtree(xcresult, ignore_errors=True)

    if not outcome.steps:
        outcome.message = _diagnose_empty(proc.stdout + proc.stderr)
    return outcome


def _diagnose_empty(log: str) -> str:
    if "was skipped" in log or "XCTSkip" in log:
        return ("The driver skipped: it did not see IOSAGENT_SCRIPT_B64. Check that "
                "AgentDriverUITests.swift is in the UI test target and that "
                "`driver_class` in .iosagent.json matches its class name.")
    if "Failed to determine if" in log or "no devices" in log.lower():
        return "The destination was not reachable. `iosagent targets` lists what is."
    return "No attachments came back; run with --keep-xcresult and inspect it in Xcode."


# UIDeviceOrientation raw values
_LANDSCAPE_LEFT, _LANDSCAPE_RIGHT = 3, 4


def _rotation_for(screen: tuple[float, float], image: tuple[int, int],
                  orientation: int) -> int:
    """Degrees clockwise needed to bring a native-framebuffer capture into the
    app's coordinate space. Zero whenever the two already agree."""
    if not all(screen) or not all(image):
        return 0
    if (screen[0] > screen[1]) == (image[0] > image[1]):
        return 0
    return 90 if orientation == _LANDSCAPE_RIGHT else 270


def collect(xcresult: Path, run_dir: Path) -> RunOutcome:
    """Unpack XCTAttachments and lay them out one directory per step."""
    export = run_dir / ".export"
    shutil.rmtree(export, ignore_errors=True)
    export.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        ["xcrun", "xcresulttool", "export", "attachments",
         "--path", str(xcresult), "--output-path", str(export)],
        capture_output=True, text=True, timeout=900,
    )
    manifest_path = export / "manifest.json"
    if proc.returncode != 0 or not manifest_path.exists():
        raise DriverError(f"could not export attachments:\n{proc.stderr[-2000:]}")

    files: dict[tuple[str, str], Path] = {}
    for group in json.loads(manifest_path.read_text()):
        for item in group.get("attachments", []):
            name = item.get("suggestedHumanReadableName", "")
            match = ATTACHMENT_RE.match(name)
            if not match:
                continue
            exported = export / item["exportedFileName"]
            if exported.exists():
                files[(match["seq"], match["kind"] or "result")] = exported

    result_file = files.get(("result", "result"))
    if result_file is None:
        shutil.rmtree(export, ignore_errors=True)
        return RunOutcome(ok=False, run_dir=run_dir)

    payload = json.loads(result_file.read_text())
    outcome = RunOutcome(ok=payload.get("ok", False), run_dir=run_dir)
    size = payload.get("screenSize") or [0, 0]
    outcome.screen_size = (float(size[0]), float(size[1]))
    image = payload.get("imageSize") or [0, 0]
    outcome.image_size = (float(image[0]), float(image[1]))
    orientation = payload.get("orientation", 0)

    for entry in payload.get("steps", []):
        index = entry["index"]
        seq = f"{index:03d}"
        step_dir = run_dir / "steps" / seq
        step_dir.mkdir(parents=True, exist_ok=True)

        artifacts = StepArtifacts(
            index=index, action=entry.get("action", "?"), ok=entry.get("ok", False),
            ms=entry.get("ms", 0), error=entry.get("error"), note=entry.get("note"),
        )
        if shot := files.get((seq, "screen")):
            artifacts.screenshot = step_dir / "screen.png"
            shutil.move(str(shot), artifacts.screenshot)
            # Decide from the file itself: the runner reports an image size
            # taken from UIImage, which is already interface-oriented even when
            # the PNG bytes behind it are the native portrait framebuffer.
            rotation = _rotation_for(outcome.screen_size,
                                     png.dimensions(artifacts.screenshot), orientation)
            if rotation:
                png.rotate_file(artifacts.screenshot, rotation)
            # a full-resolution iPad screenshot is 2752x2064; the agent reads
            # the downscaled copy and only reaches for the original on demand.
            try:
                artifacts.view = png.downscale(artifacts.screenshot,
                                               step_dir / "view.png", VIEW_MAX_DIM)
            except (subprocess.SubprocessError, OSError):
                artifacts.view = artifacts.screenshot
        if tree := files.get((seq, "tree")):
            artifacts.tree = step_dir / "tree.json"
            shutil.move(str(tree), artifacts.tree)
        outcome.steps.append(artifacts)

    (run_dir / "result.json").write_text(json.dumps(payload, indent=2))
    shutil.rmtree(export, ignore_errors=True)
    return outcome
