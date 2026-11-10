from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeServiceProofTests(unittest.TestCase):
    def test_smoke_always_builds_in_fresh_target_before_docker_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            evidence = temp / "evidence"
            evidence.mkdir()
            previous = temp / "previous"
            previous.write_text("#!/bin/sh\necho previous artifact\nexit 0\n")
            previous.chmod(0o755)
            cargo_trace = temp / "cargo-args"
            cargo = fake_bin / "cargo"
            cargo.write_text(
                "#!/bin/bash\n"
                "printf '%s\\n' \"$*\" >> \"$CARGO_TRACE\"\n"
                "target=\n"
                "while (($#)); do if [[ $1 == --target-dir ]]; then target=$2; shift 2; else shift; fi; done\n"
                "mkdir -p \"$target/release\"\n"
                "artifact=\"$target/release/codexbar-gtk-native\"\n"
                "printf '#!/bin/sh\\nexit 0\\n' > \"$artifact\"\nchmod 755 \"$artifact\"\n"
                "python3 -c 'import json,os; p=os.environ[\"ARTIFACT\"]; print(json.dumps({\"reason\":\"compiler-artifact\",\"target\":{\"name\":\"codexbar-gtk-native\"},\"executable\":p}))' ARTIFACT=\"$artifact\"\n"
            )
            # Supply the executable path through the environment for the JSON record.
            cargo.write_text(cargo.read_text().replace(
                "python3 -c 'import json,os; p=os.environ[\"ARTIFACT\"]; print(json.dumps({\"reason\":\"compiler-artifact\",\"target\":{\"name\":\"codexbar-gtk-native\"},\"executable\":p}))' ARTIFACT=\"$artifact\"",
                "ARTIFACT=\"$artifact\" python3 -c 'import json,os; p=os.environ[\"ARTIFACT\"]; print(json.dumps({\"reason\":\"compiler-artifact\",\"target\":{\"name\":\"codexbar-gtk-native\"},\"executable\":p}))'",
            ))
            cargo.chmod(0o755)
            docker = fake_bin / "docker"
            docker.write_text("#!/bin/sh\n[ \"$1\" = info ] && exit 1\nexit 99\n")
            docker.chmod(0o755)
            environment = os.environ.copy()
            environment.update({
                "PATH": f"{fake_bin}:{environment['PATH']}",
                "CARGO_TRACE": str(cargo_trace),
                "SMOKE_EVIDENCE": str(evidence),
                "PREVIOUS_ARTIFACT": str(previous),
            })
            result = subprocess.run(
                [str(ROOT / "scripts/smoke-native-service.sh")],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            invocation = cargo_trace.read_text()
            self.assertIn("--target-dir", invocation)
            self.assertIn(str(evidence / "work/current-target"), invocation)
            artifact = evidence / "work/current-target/release/codexbar-gtk-native"
            self.assertTrue(artifact.is_file())
            self.assertIn(str(artifact), (evidence / "source-sha256.txt").read_text())

    def test_required_action_surfaces_failure(self) -> None:
        library = ROOT / "scripts/native/no-python/service-proof-lib.sh"
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; run_required_action refresh false', "bash", str(library)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required action failed: refresh", result.stderr)

    def test_stop_reap_kills_and_reaps_signal_ignoring_child_boundedly(self) -> None:
        library = ROOT / "scripts/native/no-python/service-proof-lib.sh"
        started = time.monotonic()
        result = subprocess.run(
            [
                "bash", "-c",
                'source "$1"; python3 -c "import signal,time; signal.signal(signal.SIGQUIT, signal.SIG_IGN); signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)" & child=$!; stop_reap "$child"',
                "bash", str(library),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=7,
        )
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(elapsed, 6)


if __name__ == "__main__":
    unittest.main()
