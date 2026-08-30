import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class PackageProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        pi = self.fake_bin / "pi"
        pi.write_text("#!/usr/bin/env bash\necho 'pi test'\n")
        pi.chmod(0o755)

    def install_env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = str(self.root / "home")
        env["PI_CODING_AGENT_DIR"] = str(self.root / "agent")
        env["PATH"] = f"{self.fake_bin}:{env['PATH']}"
        return env

    def run_install(self, *args: str, repo_root: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(repo_root / "scripts" / "install.sh"), *args],
            cwd=repo_root,
            env=self.install_env(repo_root),
            text=True,
            capture_output=True,
            check=False,
        )

    def stage_install_repo(self, manifest: dict) -> Path:
        repo = self.root / "repo"
        (repo / "scripts").mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "scripts" / "install.sh", repo / "scripts" / "install.sh")
        (repo / "packages.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return repo

    def test_install_defaults_to_pinned_sources(self):
        result = self.run_install("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Install profile: pinned", result.stdout)
        self.assertIn("[dry-run] pi install npm:pi-hashline-edit@0.8.3", result.stdout)
        self.assertNotIn("[dry-run] pi install npm:pi-hashline-edit\n", result.stdout)

    def test_install_latest_uses_unversioned_sources(self):
        result = self.run_install("--latest", "--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Install profile: latest", result.stdout)
        self.assertIn("[dry-run] pi install npm:pi-hashline-edit\n", result.stdout)
        self.assertNotIn("npm:pi-hashline-edit@0.8.3", result.stdout)

    def test_install_latest_fails_before_install_when_source_is_missing(self):
        manifest = {
            "packages": [
                {
                    "source": "npm:example@1.2.3",
                    "id": "example",
                    "kind": "npm",
                    "note": "test package",
                }
            ],
            "local_extensions": [],
            "local_configs": [],
            "local_agents": [],
        }
        repo = self.stage_install_repo(manifest)

        result = self.run_install("--latest", "--dry-run", repo_root=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("latest_source", result.stderr)
        self.assertNotIn("pi install", result.stdout)

    def test_install_rejects_malformed_git_sources_before_install(self):
        manifest = {
            "packages": [
                {
                    "source": "git:github.com/example/plugin",
                    "latest_source": "https://",
                    "id": "plugin",
                    "kind": "git",
                    "note": "test package",
                }
            ],
            "local_extensions": [],
            "local_configs": [],
            "local_agents": [],
        }
        repo = self.stage_install_repo(manifest)

        result = self.run_install("--latest", "--dry-run", repo_root=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("plugin.latest_source", result.stderr)
        self.assertNotIn("pi install", result.stdout)

    def test_install_rejects_non_exact_pinned_npm_versions(self):
        manifest = {
            "packages": [
                {
                    "source": "npm:example@latest",
                    "latest_source": "npm:example",
                    "id": "example",
                    "kind": "npm",
                    "note": "test package",
                }
            ],
            "local_extensions": [],
            "local_configs": [],
            "local_agents": [],
        }
        repo = self.stage_install_repo(manifest)

        result = self.run_install("--dry-run", repo_root=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("example.source", result.stderr)
        self.assertIn("exact version", result.stderr)
        self.assertNotIn("pi install", result.stdout)

    def test_install_applies_package_resource_filters_to_settings(self):
        manifest = {
            "packages": [
                {
                    "source": "npm:pine-of-glass@0.10.2",
                    "latest_source": "npm:pine-of-glass",
                    "id": "pine-of-glass",
                    "kind": "npm",
                    "extensions": ["!extensions/pi-traceline/**"],
                    "note": "test package",
                }
            ],
            "local_extensions": [],
            "local_configs": [],
            "local_agents": [],
        }
        repo = self.stage_install_repo(manifest)
        agent_dir = self.root / "agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "settings.json").write_text(
            json.dumps({"packages": ["npm:pine-of-glass@0.10.2", "npm:other@1.0.0"]}) + "\n"
        )

        result = self.run_install("--skip-packages", repo_root=repo)

        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads((agent_dir / "settings.json").read_text())
        self.assertEqual(
            settings["packages"][0],
            {
                "source": "npm:pine-of-glass@0.10.2",
                "extensions": ["!extensions/pi-traceline/**"],
            },
        )
        self.assertEqual(settings["packages"][1], "npm:other@1.0.0")

    def test_with_settings_merges_quiet_calm_compatible_preferences(self):
        result = self.run_install("--skip-packages", "--with-settings")

        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads((self.root / "agent" / "settings.json").read_text())
        self.assertTrue(settings["hideThinkingBlock"])
        self.assertTrue(settings["quietStartup"])
        self.assertTrue(settings["collapseChangelog"])
        self.assertEqual(settings["steeringMode"], "all")
        self.assertEqual(settings["followUpMode"], "all")

    def test_dump_preserves_latest_source_and_adds_it_for_new_npm_packages(self):
        repo = self.root / "dump-repo"
        (repo / "scripts").mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "scripts" / "dump.sh", repo / "scripts" / "dump.sh")
        manifest = {
            "$schema_note": "test manifest",
            "meta": {"name": "test/repo"},
            "packages": [
                {
                    "source": "npm:existing@1.0.0",
                    "latest_source": "npm:existing",
                    "id": "existing",
                    "kind": "npm",
                    "note": "keep me",
                }
            ],
            "local_extensions": [],
            "local_configs": [],
            "local_agents": [],
        }
        (repo / "packages.json").write_text(json.dumps(manifest, indent=2) + "\n")

        agent_dir = self.root / "dump-agent"
        (agent_dir / "npm").mkdir(parents=True)
        (agent_dir / "settings.json").write_text(
            json.dumps(
                {
                    "packages": [
                        {
                            "source": "npm:existing",
                            "extensions": ["!extensions/pi-traceline/**"],
                        },
                        "npm:new-package",
                    ]
                }
            )
            + "\n"
        )
        (agent_dir / "npm" / "package.json").write_text(
            json.dumps({"dependencies": {"existing": "1.2.3", "new-package": "2.0.0"}}) + "\n"
        )
        env = os.environ.copy()
        env["PI_CODING_AGENT_DIR"] = str(agent_dir)

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "dump.sh")],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        dumped = json.loads((repo / "packages.json").read_text())
        by_id = {package["id"]: package for package in dumped["packages"]}
        self.assertEqual(by_id["existing"]["source"], "npm:existing@1.2.3")
        self.assertEqual(by_id["existing"]["latest_source"], "npm:existing")
        self.assertEqual(by_id["existing"]["note"], "keep me")
        self.assertEqual(
            by_id["existing"]["extensions"],
            ["!extensions/pi-traceline/**"],
        )
        self.assertEqual(by_id["new-package"]["source"], "npm:new-package@2.0.0")
        self.assertEqual(by_id["new-package"]["latest_source"], "npm:new-package")


if __name__ == "__main__":
    unittest.main()
