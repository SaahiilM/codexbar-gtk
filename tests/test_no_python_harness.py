from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RESOLVER_PATH = ROOT / "scripts/native/no-python/cargo-artifact.py"
SPEC = importlib.util.spec_from_file_location("cargo_artifact", RESOLVER_PATH)
assert SPEC and SPEC.loader
cargo_artifact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cargo_artifact)


class CargoArtifactResolverTests(unittest.TestCase):
    def test_selects_exact_target_and_ignores_non_artifact_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "native"
            binary.write_text("synthetic executable")
            binary.chmod(0o755)
            messages = "\n".join(
                [
                    '{"reason":"build-finished","success":true}',
                    '{"reason":"compiler-artifact","target":{"name":"other"},"executable":"/missing"}',
                    json_message("codexbar_gtk_native", binary),
                ]
            )
            self.assertEqual(
                cargo_artifact.resolve(io.StringIO(messages), "codexbar_gtk_native"),
                binary,
            )

    def test_rejects_missing_ambiguous_and_malformed_artifacts(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            cargo_artifact.resolve(io.StringIO('{"reason":"build-finished"}'), "native")
        duplicate = json_message("native", Path("/tmp/one")) + "\n" + json_message("native", Path("/tmp/two"))
        with self.assertRaisesRegex(ValueError, "found 2"):
            cargo_artifact.resolve(io.StringIO(duplicate), "native")
        with self.assertRaisesRegex(ValueError, "invalid Cargo JSON"):
            cargo_artifact.resolve(io.StringIO("not-json"), "native")


def json_message(name: str, executable: Path) -> str:
    import json

    return json.dumps(
        {"reason": "compiler-artifact", "target": {"name": name}, "executable": str(executable)}
    )


class NoPythonSmokeArgumentTests(unittest.TestCase):
    def test_bad_artifact_is_an_input_error(self):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/smoke-native-no-python.sh"), "--artifact", "/missing/native"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)

    def test_required_docker_unavailable_fails_instead_of_skipping(self):
        with tempfile.TemporaryDirectory() as temp:
            fake_bin = Path(temp) / "bin"
            fake_bin.mkdir()
            docker = fake_bin / "docker"
            docker.write_text("#!/bin/sh\nexit 1\n")
            docker.chmod(0o755)
            artifact = Path(temp) / "native"
            artifact.write_text("synthetic executable")
            artifact.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["SMOKE_EVIDENCE"] = str(Path(temp) / "evidence")
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/smoke-native-no-python.sh"),
                    "--artifact",
                    str(artifact),
                    "--require-docker",
                ],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("required Docker daemon unavailable", result.stdout)


if __name__ == "__main__":
    unittest.main()
