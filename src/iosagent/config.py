"""Project configuration: `.iosagent.json`, discovered by walking up from cwd."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = ".iosagent.json"


class ConfigError(Exception):
    pass


@dataclass
class TargetSpec:
    name: str
    kind: str           # "simulator" | "device"
    identifier: str = ""   # UDID, optional; name is resolved at runtime when blank

    @property
    def is_device(self) -> bool:
        return self.kind == "device"


@dataclass
class Config:
    root: Path
    scheme: str
    bundle_id: str
    project: str = ""
    workspace: str = ""
    ui_test_target: str = ""
    driver_class: str = "AgentDriverUITests"
    build_wrapper: str = ""
    derived_data: str = ""
    artifacts: str = "~/.iosagent/runs"
    default_target: str = ""
    targets: dict[str, TargetSpec] = field(default_factory=dict)
    launch_args: list[str] = field(default_factory=list)
    launch_env: dict[str, str] = field(default_factory=dict)

    # -- derived ----------------------------------------------------------

    @property
    def project_name(self) -> str:
        return self.root.name

    @property
    def artifacts_root(self) -> Path:
        return Path(os.path.expanduser(self.artifacts)) / self.project_name

    def xcodebuild_project_args(self) -> list[str]:
        if self.workspace:
            return ["-workspace", str(self.root / self.workspace)]
        if self.project:
            return ["-project", str(self.root / self.project)]
        return []

    def wrapper_path(self) -> Path | None:
        if not self.build_wrapper:
            return None
        p = self.root / self.build_wrapper
        return p if p.exists() else None

    def target(self, name: str = "") -> TargetSpec:
        name = name or self.default_target
        if not name:
            raise ConfigError(
                "no target requested and no `default_target` in .iosagent.json"
            )
        if name not in self.targets:
            known = ", ".join(sorted(self.targets)) or "(none defined)"
            raise ConfigError(f"unknown target {name!r}; configured targets: {known}")
        return self.targets[name]


def find_config(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        cfg = candidate / CONFIG_NAME
        if cfg.exists():
            return cfg
    raise ConfigError(
        f"no {CONFIG_NAME} found in {here} or any parent. "
        f"Run `iosagent init` in your project root."
    )


def load(start: Path | None = None) -> Config:
    path = find_config(start)
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc

    for required in ("scheme", "bundle_id"):
        if not raw.get(required):
            raise ConfigError(f"{path} is missing required key {required!r}")

    targets: dict[str, TargetSpec] = {}
    for name, spec in (raw.get("targets") or {}).items():
        kind = spec.get("kind", "simulator")
        if kind not in ("simulator", "device"):
            raise ConfigError(f"target {name!r}: kind must be 'simulator' or 'device'")
        targets[name] = TargetSpec(
            name=spec.get("name", ""), kind=kind, identifier=spec.get("id", "")
        )
    if not targets:
        raise ConfigError(f"{path} defines no targets")

    launch = raw.get("launch") or {}
    default_target = raw.get("default_target") or next(iter(targets))

    return Config(
        root=path.parent,
        scheme=raw["scheme"],
        bundle_id=raw["bundle_id"],
        project=raw.get("project", ""),
        workspace=raw.get("workspace", ""),
        ui_test_target=raw.get("ui_test_target", ""),
        driver_class=raw.get("driver_class", "AgentDriverUITests"),
        build_wrapper=raw.get("build_wrapper", ""),
        derived_data=raw.get("derived_data", ""),
        artifacts=raw.get("artifacts", "~/.iosagent/runs"),
        default_target=default_target,
        targets=targets,
        launch_args=list(launch.get("args") or []),
        launch_env=dict(launch.get("env") or {}),
    )


TEMPLATE = {
    "project": "MyApp.xcodeproj",
    "scheme": "MyApp",
    "bundle_id": "com.example.MyApp",
    "ui_test_target": "MyAppUITests",
    "driver_class": "AgentDriverUITests",
    "build_wrapper": "",
    "artifacts": "~/.iosagent/runs",
    "default_target": "sim",
    "targets": {
        "sim": {"kind": "simulator", "name": "iPad Pro 11-inch (M5)"},
        "device": {"kind": "device", "name": "My iPad"},
    },
    "launch": {"args": [], "env": {}},
}
