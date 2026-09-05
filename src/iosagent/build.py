"""xcodebuild, with guardrails.

Two of these guards exist because of a real incident: passing a fresh
`-derivedDataPath /tmp/<name>` per run once left 563 orphaned DerivedData
directories totalling 215 GB, invisible to macOS storage tools. The other guard
exists because DerivedData inside an iCloud-synced folder gets stamped with
`com.apple.FinderInfo`, after which codesign refuses the built bundles with
"resource fork, Finder information, or similar detritus not allowed" -- and only
during `test`, never during `build`, so it reads as flaky rather than fatal.

Neither is left to discipline. Both are enforced here.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .config import Config


class BuildError(Exception):
    pass


def _reject_temp_path(path: Path) -> None:
    resolved = path.resolve()
    for bad in ("/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp"):
        if str(resolved) == bad or str(resolved).startswith(bad + "/"):
            raise BuildError(
                f"refusing DerivedData at {resolved}.\n"
                f"A unique temp path per run is how build output goes invisible: "
                f"orphaned DerivedData in /tmp does not show up in Storage settings "
                f"and can reach hundreds of gigabytes. Use one reused path instead."
            )


def _reject_synced_path(path: Path) -> None:
    """Walk every ancestor looking for a file-provider (iCloud/Dropbox) marker."""
    current = path if path.exists() else path.parent
    while True:
        try:
            attrs = subprocess.run(["xattr", str(current)], capture_output=True,
                                   text=True, timeout=10).stdout
        except (subprocess.SubprocessError, OSError):
            attrs = ""
        if "fileprovider" in attrs or "file-provider" in attrs:
            raise BuildError(
                f"refusing DerivedData at {path}: {current} is inside a synced "
                f"folder (iCloud Drive, Dropbox or similar).\n"
                f"The file provider stamps com.apple.FinderInfo on built bundles, "
                f"after which codesign fails with 'resource fork, Finder "
                f"information, or similar detritus not allowed' -- but only during "
                f"`test`, so it looks intermittent. Put DerivedData outside the "
                f"synced tree."
            )
        if current.parent == current:
            return
        current = current.parent


def derived_data_path(cfg: Config) -> Path:
    if cfg.derived_data:
        path = Path(os.path.expanduser(cfg.derived_data))
    else:
        path = (Path.home() / "Library/Developer/Xcode/DerivedData"
                / f"{cfg.project_name}-iosagent")
    _reject_temp_path(path)
    _reject_synced_path(path)
    return path


def base_command(cfg: Config) -> list[str]:
    """Prefer the project's own build wrapper when it has one."""
    wrapper = cfg.wrapper_path()
    if wrapper:
        return [str(wrapper)]
    path = derived_data_path(cfg)
    path.mkdir(parents=True, exist_ok=True)
    return ["xcodebuild", "-derivedDataPath", str(path)]


def run_xcodebuild(cfg: Config, args: list[str], *, env: dict[str, str] | None = None,
                   timeout: int = 3600, capture: bool = True) -> subprocess.CompletedProcess:
    cmd = [*base_command(cfg), *cfg.xcodebuild_project_args(), "-scheme", cfg.scheme, *args]
    merged = dict(os.environ)
    merged.update(env or {})
    if any(a.startswith("-derivedDataPath") for a in args):
        raise BuildError("-derivedDataPath is managed by iosagent; do not pass it through")
    return subprocess.run(cmd, capture_output=capture, text=True,
                          env=merged, cwd=cfg.root, timeout=timeout)


def build_settings(cfg: Config, destination: str) -> dict[str, str]:
    proc = run_xcodebuild(cfg, ["-destination", destination, "-showBuildSettings", "-json"],
                          timeout=600)
    if proc.returncode != 0:
        raise BuildError(f"could not read build settings:\n{proc.stderr[-2000:]}")
    # the wrapper may print a banner before the JSON
    text = proc.stdout[proc.stdout.index("["):]
    for entry in json.loads(text):
        settings = entry.get("buildSettings", {})
        if settings.get("PRODUCT_TYPE") == "com.apple.product-type.application":
            return settings
    raise BuildError("no application target found in build settings")


def app_path(cfg: Config, destination: str) -> Path:
    settings = build_settings(cfg, destination)
    return Path(settings["BUILT_PRODUCTS_DIR"]) / settings["FULL_PRODUCT_NAME"]


def build(cfg: Config, destination: str, *, for_testing: bool = True,
          only_testing: str = "", allow_provisioning: bool = True) -> None:
    args = ["-destination", destination]
    if allow_provisioning:
        args.append("-allowProvisioningUpdates")
    if only_testing:
        args += ["-only-testing:" + only_testing]
    args.append("build-for-testing" if for_testing else "build")

    proc = run_xcodebuild(cfg, args, capture=True)
    if proc.returncode != 0:
        errors = [ln for ln in (proc.stdout + proc.stderr).splitlines()
                  if "error:" in ln]
        detail = "\n".join(errors[-25:]) or (proc.stdout + proc.stderr)[-3000:]
        raise BuildError(f"build failed:\n{detail}")
