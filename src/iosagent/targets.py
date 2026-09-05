"""Physical devices and simulators behind one interface.

Everything here shells out to tooling that ships with Xcode -- `devicectl` for
devices, `simctl` for simulators. No third-party dependency, by design: the
whole point is that `git clone` is the entire install.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import TargetSpec


class TargetError(Exception):
    pass


def _run(cmd: list[str], *, check: bool = True, timeout: int = 180) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise TargetError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"{(proc.stderr or proc.stdout).strip()[:2000]}"
        )
    return proc


def _devicectl_json(args: list[str], *, timeout: int = 180) -> dict:
    """devicectl's only supported machine interface is --json-output to a file."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        _run(["xcrun", "devicectl", *args, "--json-output", str(out)], timeout=timeout)
        return json.loads(out.read_text()) if out.stat().st_size else {}
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

@dataclass
class Discovered:
    name: str
    udid: str
    kind: str
    state: str
    model: str = ""

    @property
    def available(self) -> bool:
        return self.state in ("connected", "Booted", "Shutdown", "available (paired)")


def list_devices() -> list[Discovered]:
    try:
        payload = _devicectl_json(["list", "devices"], timeout=90)
    except (TargetError, subprocess.TimeoutExpired):
        return []
    found = []
    for dev in payload.get("result", {}).get("devices", []):
        props = dev.get("deviceProperties", {})
        hw = dev.get("hardwareProperties", {})
        # devicectl also reports simulators and watches; keep real iOS hardware.
        if hw.get("reality") != "physical":
            continue
        if hw.get("platform") not in ("iOS", "iPadOS"):
            continue
        found.append(Discovered(
            name=props.get("name", "?"),
            udid=dev.get("identifier", ""),
            kind="device",
            state=dev.get("connectionProperties", {}).get("tunnelState", "")
                  or props.get("bootState", ""),
            model=hw.get("marketingName", ""),
        ))
    return found


def list_simulators() -> list[Discovered]:
    proc = _run(["xcrun", "simctl", "list", "devices", "--json"], check=False)
    if proc.returncode != 0:
        return []
    payload = json.loads(proc.stdout)
    found = []
    for runtime, devices in payload.get("devices", {}).items():
        if "iOS" not in runtime:
            continue
        for dev in devices:
            if not dev.get("isAvailable", False):
                continue
            found.append(Discovered(
                name=dev.get("name", "?"), udid=dev.get("udid", ""),
                kind="simulator", state=dev.get("state", ""), model=runtime.split(".")[-1],
            ))
    return found


# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------

class Target:
    kind = "abstract"

    def __init__(self, spec: TargetSpec):
        self.spec = spec
        self.udid = spec.identifier
        self.name = spec.name

    def resolve(self) -> "Target":
        raise NotImplementedError

    def destination(self) -> str:
        raise NotImplementedError

    def screenshot(self, dest: Path) -> Path:
        raise NotImplementedError

    def install(self, app: Path) -> None:
        raise NotImplementedError

    def launch(self, bundle_id: str, args: list[str], env: dict[str, str],
               fresh: bool = False) -> None:
        raise NotImplementedError

    def terminate(self, bundle_id: str) -> None:
        raise NotImplementedError

    def open_url(self, url: str) -> None:
        raise NotImplementedError

    def pull(self, bundle_id: str, remote: str, dest: Path) -> Path:
        raise NotImplementedError

    def push(self, bundle_id: str, local: Path, remote: str) -> None:
        raise NotImplementedError

    def logs(self, bundle_id: str, seconds: int) -> str:
        return ""

    def describe(self) -> str:
        return f"{self.kind}:{self.name or self.udid}"


class DeviceTarget(Target):
    kind = "device"

    def resolve(self) -> "DeviceTarget":
        devices = list_devices()
        if self.udid:
            match = next((d for d in devices if d.udid == self.udid), None)
        else:
            match = next((d for d in devices if d.name == self.name), None)
        if match is None:
            known = ", ".join(f"{d.name!r}" for d in devices) or "none"
            raise TargetError(
                f"device {self.name or self.udid!r} not found. Connected: {known}. "
                f"Check the cable, that the device is unlocked and trusted, and that "
                f"Developer Mode is enabled (Settings > Privacy & Security)."
            )
        self.udid, self.name = match.udid, match.name
        return self

    def destination(self) -> str:
        return f"platform=iOS,id={self.udid}"

    def screenshot(self, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run(["xcrun", "devicectl", "device", "capture", "screenshot",
              "--device", self.udid, "--destination", str(dest)], timeout=90)
        return dest

    def install(self, app: Path) -> None:
        _run(["xcrun", "devicectl", "device", "install", "app",
              "--device", self.udid, str(app)], timeout=600)

    def launch(self, bundle_id, args, env, fresh=False):
        cmd = ["xcrun", "devicectl", "device", "process", "launch", "--device", self.udid]
        if fresh:
            cmd.append("--terminate-existing")
        if env:
            cmd += ["--environment-variables", json.dumps(env)]
        cmd += [bundle_id, *args]
        _run(cmd, timeout=180)

    def terminate(self, bundle_id: str) -> None:
        # devicectl terminates by pid; find it, then signal.
        try:
            payload = _devicectl_json(
                ["device", "info", "processes", "--device", self.udid], timeout=90)
        except (TargetError, subprocess.TimeoutExpired):
            return
        for proc in payload.get("result", {}).get("runningProcesses", []):
            if bundle_id in (proc.get("executable") or ""):
                _run(["xcrun", "devicectl", "device", "process", "signal",
                      "--device", self.udid, "--signal", "SIGKILL",
                      "--pid", str(proc["processIdentifier"])], check=False)

    def open_url(self, url: str) -> None:
        _run(["xcrun", "devicectl", "device", "process", "openURL",
              "--device", self.udid, url], timeout=90)

    def pull(self, bundle_id: str, remote: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run(["xcrun", "devicectl", "device", "copy", "from", "--device", self.udid,
              "--domain-type", "appDataContainer", "--domain-identifier", bundle_id,
              "--source", remote, "--destination", str(dest)], timeout=600)
        return dest

    def push(self, bundle_id: str, local: Path, remote: str) -> None:
        _run(["xcrun", "devicectl", "device", "copy", "to", "--device", self.udid,
              "--domain-type", "appDataContainer", "--domain-identifier", bundle_id,
              "--source", str(local), "--destination", remote], timeout=600)

    def logs(self, bundle_id: str, seconds: int) -> str:
        # `log` can read a connected device, but not every pairing state allows it;
        # a missing log is an inconvenience, never a failed run.
        proc = _run(["log", "collect", "--device-udid", self.udid,
                     "--last", f"{seconds}s", "--output", "/dev/null"],
                    check=False, timeout=120)
        return proc.stdout or proc.stderr or ""


class SimulatorTarget(Target):
    kind = "simulator"

    def resolve(self) -> "SimulatorTarget":
        sims = list_simulators()
        if self.udid:
            match = next((s for s in sims if s.udid == self.udid), None)
        else:
            candidates = [s for s in sims if s.name == self.name]
            # prefer one that is already booted; booting costs ~20s
            match = next((s for s in candidates if s.state == "Booted"),
                         candidates[0] if candidates else None)
        if match is None:
            raise TargetError(
                f"simulator {self.name or self.udid!r} not found. "
                f"`xcrun simctl list devices` shows what is installed."
            )
        self.udid, self.name = match.udid, match.name
        self._state = match.state
        return self

    def destination(self) -> str:
        return f"platform=iOS Simulator,id={self.udid}"

    def boot(self) -> None:
        _run(["xcrun", "simctl", "boot", self.udid], check=False, timeout=180)
        _run(["xcrun", "simctl", "bootstatus", self.udid, "-b"], check=False, timeout=300)

    def screenshot(self, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run(["xcrun", "simctl", "io", self.udid, "screenshot", str(dest)], timeout=90)
        return dest

    def install(self, app: Path) -> None:
        _run(["xcrun", "simctl", "install", self.udid, str(app)], timeout=300)

    def launch(self, bundle_id, args, env, fresh=False):
        child_env = dict(os.environ)
        for key, value in env.items():
            child_env[f"SIMCTL_CHILD_{key}"] = value
        cmd = ["xcrun", "simctl", "launch"]
        if fresh:
            cmd.append("--terminate-running-process")
        cmd += [self.udid, bundle_id, *args]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              env=child_env, timeout=180)
        if proc.returncode != 0:
            raise TargetError(f"simctl launch failed: {proc.stderr.strip()}")

    def terminate(self, bundle_id: str) -> None:
        _run(["xcrun", "simctl", "terminate", self.udid, bundle_id], check=False)

    def open_url(self, url: str) -> None:
        _run(["xcrun", "simctl", "openurl", self.udid, url], timeout=90)

    def _container(self, bundle_id: str) -> Path:
        proc = _run(["xcrun", "simctl", "get_app_container", self.udid, bundle_id, "data"])
        return Path(proc.stdout.strip())

    def pull(self, bundle_id: str, remote: str, dest: Path) -> Path:
        src = self._container(bundle_id) / remote.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)
        return dest

    def push(self, bundle_id: str, local: Path, remote: str) -> None:
        dst = self._container(bundle_id) / remote.lstrip("/")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if Path(local).is_dir():
            shutil.copytree(local, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(local, dst)

    def logs(self, bundle_id: str, seconds: int) -> str:
        proc = _run(["xcrun", "simctl", "spawn", self.udid, "log", "show",
                     "--last", f"{seconds}s", "--style", "compact",
                     "--predicate", f'subsystem CONTAINS "{bundle_id}"'],
                    check=False, timeout=120)
        return proc.stdout or ""


def make(spec: TargetSpec) -> Target:
    cls = DeviceTarget if spec.is_device else SimulatorTarget
    return cls(spec).resolve()


def app_bundle_path(derived_data: Path, scheme: str, is_device: bool) -> Path:
    """Locate the built .app inside a DerivedData tree."""
    subdir = "Debug-iphoneos" if is_device else "Debug-iphonesimulator"
    products = derived_data / "Build" / "Products" / subdir
    if not products.exists():
        raise TargetError(f"no build products at {products}; run `iosagent build` first")
    exact = products / f"{scheme}.app"
    if exact.exists():
        return exact
    apps = sorted(products.glob("*.app"))
    if not apps:
        raise TargetError(f"no .app found in {products}")
    return apps[0]


def bundle_id_of(app: Path) -> str:
    info = app / "Info.plist"
    with info.open("rb") as handle:
        return plistlib.load(handle).get("CFBundleIdentifier", "")
