import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/native/no-python/service-targets.sh"


class ServiceTargetParserTests(unittest.TestCase):
    def parse(self, function, path):
        return subprocess.run(
            ["bash", "-c", f"source {str(HELPER)!r}; {function} \"$1\"", "test", str(path)],
            capture_output=True,
            text=True,
        )

    def test_desktop_and_service_targets_preserve_prefix_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "prefix with spaces" / "bin" / "native app"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            desktop = Path(tmp) / "app.desktop"
            desktop.write_text(f'[Desktop Entry]\nExec="{executable}" %U\n')
            service = Path(tmp) / "app.service"
            service.write_text(f'[Service]\nExecStart="{executable}"\n')

            self.assertEqual(self.parse("desktop_exec_target", desktop).stdout.strip(), str(executable))
            self.assertEqual(self.parse("service_exec_target", service).stdout.strip(), str(executable))

    def test_rejects_unquoted_exec_and_duplicate_directives(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "native"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            for contents in (
                f"[Desktop Entry]\nExec={executable} %U\n",
                f'[Desktop Entry]\nExec="{executable}" %U\nExec="{executable}" %U\n',
            ):
                entry = Path(tmp) / "bad.desktop"
                entry.write_text(contents)
                result = self.parse("desktop_exec_target", entry)
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
