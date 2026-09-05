import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from iosagent import build, config
from iosagent.cli import parse_step
from iosagent.config import ConfigError


VALID = {
    "project": "App.xcodeproj", "scheme": "App", "bundle_id": "com.example.App",
    "ui_test_target": "AppUITests", "default_target": "sim",
    "targets": {"sim": {"kind": "simulator", "name": "iPad Pro 11-inch (M5)"},
                "ipad": {"kind": "device", "name": "My iPad"}},
}


class ConfigLoading(unittest.TestCase):
    def write(self, tmp, payload):
        path = Path(tmp) / ".iosagent.json"
        path.write_text(json.dumps(payload))
        return Path(tmp)

    def test_found_by_walking_up_from_a_subdirectory(self):
        with TemporaryDirectory() as tmp:
            root = self.write(tmp, VALID)
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            self.assertEqual(config.load(nested).scheme, "App")

    def test_missing_required_key_names_the_key(self):
        with TemporaryDirectory() as tmp:
            root = self.write(tmp, {k: v for k, v in VALID.items() if k != "bundle_id"})
            with self.assertRaises(ConfigError) as ctx:
                config.load(root)
            self.assertIn("bundle_id", str(ctx.exception))

    def test_unknown_target_lists_the_known_ones(self):
        with TemporaryDirectory() as tmp:
            cfg = config.load(self.write(tmp, VALID))
            with self.assertRaises(ConfigError) as ctx:
                cfg.target("nope")
            self.assertIn("sim", str(ctx.exception))

    def test_device_targets_are_distinguished_from_simulators(self):
        with TemporaryDirectory() as tmp:
            cfg = config.load(self.write(tmp, VALID))
            self.assertTrue(cfg.target("ipad").is_device)
            self.assertFalse(cfg.target("sim").is_device)

    def test_artifacts_default_outside_the_project(self):
        with TemporaryDirectory() as tmp:
            cfg = config.load(self.write(tmp, VALID))
            self.assertNotIn(str(cfg.root), str(cfg.artifacts_root))


class DerivedDataGuards(unittest.TestCase):
    """Both of these have cost real disk and real debugging time."""

    def make(self, tmp, derived):
        payload = dict(VALID, derived_data=derived)
        Path(tmp, ".iosagent.json").write_text(json.dumps(payload))
        return config.load(Path(tmp))

    def test_refuses_derived_data_under_tmp(self):
        with TemporaryDirectory() as tmp:
            cfg = self.make(tmp, "/tmp/iosagent-build")
            with self.assertRaises(build.BuildError) as ctx:
                build.derived_data_path(cfg)
            self.assertIn("/tmp", str(ctx.exception))

    def test_refuses_derived_data_under_private_tmp(self):
        with TemporaryDirectory() as tmp:
            cfg = self.make(tmp, "/private/tmp/whatever")
            with self.assertRaises(build.BuildError):
                build.derived_data_path(cfg)

    def test_refuses_a_synced_folder(self):
        with TemporaryDirectory() as tmp:
            cfg = self.make(tmp, str(Path(tmp) / "DerivedData"))
            fake = mock.Mock(stdout="com.apple.fileprovider.fpfs#P\n")
            with mock.patch("iosagent.build.subprocess.run", return_value=fake):
                with self.assertRaises(build.BuildError) as ctx:
                    build.derived_data_path(cfg)
            self.assertIn("synced", str(ctx.exception))

    def test_accepts_an_ordinary_path(self):
        with TemporaryDirectory() as tmp:
            cfg = self.make(tmp, str(Path(tmp) / "DerivedData"))
            fake = mock.Mock(stdout="")
            with mock.patch("iosagent.build.subprocess.run", return_value=fake):
                self.assertTrue(str(build.derived_data_path(cfg)).endswith("DerivedData"))

    def test_caller_cannot_smuggle_in_its_own_derived_data_path(self):
        with TemporaryDirectory() as tmp:
            cfg = self.make(tmp, str(Path(tmp) / "DerivedData"))
            with self.assertRaises(build.BuildError):
                build.run_xcodebuild(cfg, ["-derivedDataPath", "/tmp/sneaky", "build"])


class StepGrammar(unittest.TestCase):
    def test_tap_by_identifier(self):
        self.assertEqual(parse_step("tap library.new"),
                         {"action": "tap", "id": "library.new"})

    def test_tap_by_normalised_coordinate(self):
        self.assertEqual(parse_step("tap @0.5,0.25"),
                         {"action": "tap", "norm": [0.5, 0.25]})

    def test_type_keeps_spaces_in_the_text(self):
        step = parse_step("type note.title Hello there world")
        self.assertEqual(step["text"], "Hello there world")

    def test_wait_takes_seconds(self):
        self.assertEqual(parse_step("wait 2.5")["seconds"], 2.5)

    def test_typed_selector(self):
        self.assertEqual(parse_step("tap button:save"),
                         {"action": "tap", "type": "button", "id": "save"})

    def test_drag_between_two_coordinates(self):
        step = parse_step("drag @0.2,0.3 @0.8,0.7")
        self.assertEqual(step["from"]["norm"], [0.2, 0.3])
        self.assertEqual(step["to"]["norm"], [0.8, 0.7])

    def test_swipe_direction(self):
        self.assertEqual(parse_step("swipe library.list down")["direction"], "down")


if __name__ == "__main__":
    unittest.main()
