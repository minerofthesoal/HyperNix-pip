"""``bin/hypernix-t1`` — running a T1 API as a thing you manage.

The gap it fills: starting the server by hand is a uvicorn incantation
with six environment variables, and every one has to match what ``gkey``
and ``waiter`` think. Getting one wrong does not fail loudly — it
produces a server that runs and rejects your keys, which is the most
expensive way for this to go wrong.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from shell_support import BASH, NO_BASH_REASON

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "hypernix-t1"

pytestmark = pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)


def run(*argv: str, home: Path, config: Path, timeout: int = 60):
    """Run the script. `.output` is stdout+stderr.

    Warnings go to stderr — correct for a status line, and easy to miss
    when asserting.
    """
    result = subprocess.run(
        [BASH, str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={
            **os.environ,
            "HOME": str(home),
            "T1_CONFIG_DIR": str(config),
            "NO_COLOR": "1",
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
    )
    result.output = result.stdout + result.stderr  # type: ignore[attr-defined]
    return result


@pytest.fixture
def configured(tmp_path):
    home = tmp_path / "home"
    config = tmp_path / "cfg"
    home.mkdir()
    config.mkdir()
    (config / ".env").write_text(
        "T1_HOST=127.0.0.1\n"
        "T1_PORT=8123\n"
        f"T1_KEYMASTER_DIR={config}/keymaster\n"
        f"T1_DB_PATH={config}/t1.sqlite3\n"
        "T1_TOKEN_SECRET=" + "d" * 64 + "\n"
    )
    return home, config


class TestShape:
    def test_it_exists_and_is_executable(self):
        assert SCRIPT.is_file()
        assert os.access(SCRIPT, os.X_OK)

    def test_it_parses(self):
        subprocess.run([BASH, "-n", str(SCRIPT)], check=True)

    def test_shellcheck_is_clean_if_available(self):
        if shutil.which("shellcheck") is None:
            pytest.skip("shellcheck not installed")
        result = subprocess.run(
            ["shellcheck", "--severity=style", str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_help_lists_every_command(self, configured):
        home, config = configured
        text = run("help", home=home, config=config).output
        for command in ("start", "stop", "kill", "restart", "status", "logs",
                        "create", "configure", "test", "key", "autostart", "remove"):
            assert command in text, command

    def test_an_unknown_command_fails(self, configured):
        home, config = configured
        assert run("nonsense", home=home, config=config).returncode == 2


class TestProcessIdentity:
    """A PID file outlives the process it named, and PIDs get reused.

    Trusting one is how a manager reports a dead server as healthy — or,
    much worse, kills whatever now holds that number.
    """

    def test_a_stale_pid_is_not_reported_as_running(self, configured):
        home, config = configured
        (config / "server.pid").write_text("999999\n")
        assert "not running" in run("status", home=home, config=config).output

    def test_someone_elses_process_is_not_claimed(self, configured):
        """The dangerous case: the PID exists, and is not ours."""
        home, config = configured
        victim = subprocess.Popen(["sleep", "120"])
        try:
            (config / "server.pid").write_text(f"{victim.pid}\n")
            assert "not running" in run("status", home=home, config=config).output
            # And stop must not kill it.
            run("stop", home=home, config=config)
            assert victim.poll() is None, "it killed an unrelated process"
        finally:
            victim.kill()
            victim.wait(timeout=10)

    def test_it_checks_the_command_line_not_just_the_pid(self):
        source = SCRIPT.read_text()
        assert "hypernix.t1api" in source.split("server_pid()")[1][:600]


class TestConfig:
    def test_the_env_file_is_read_not_sourced(self):
        """.env is a file people edit by hand; sourcing runs whatever
        ends up in it."""
        source = SCRIPT.read_text()
        body = source.split("load_env()")[1].split("\n}")[0]
        # The syntax, not the word — the function's own comment explains
        # why sourcing is avoided, and matching that proves nothing.
        code = "\n".join(
            row for row in body.splitlines() if not row.strip().startswith("#")
        )
        assert '. "$ENV_FILE"' not in code
        assert "source " not in code

    def test_only_known_prefixes_are_exported(self):
        """A stray line in .env should not set PATH or LD_PRELOAD."""
        assert 'T1_*|HYPERNIX_*)' in SCRIPT.read_text()


class TestTheSystemdUnit:
    def test_exec_start_is_absolute(self, configured):
        """systemd will not resolve a relative path, and the unit it
        wrote silently refused to start."""
        home, config = configured
        run("autostart", "on", home=home, config=config)
        unit = home / ".config" / "systemd" / "user" / "hypernix-t1.service"
        if not unit.exists():
            pytest.skip("systemd not available to write a unit here")
        line = next(
            row for row in unit.read_text().splitlines() if row.startswith("ExecStart=")
        )
        path = line.split("=", 1)[1].split()[0]
        assert path.startswith("/"), line

    def test_the_unit_sets_an_explicit_path(self):
        """A user unit gets a minimal PATH, and a tailscale in
        /usr/local/bin then becomes invisible — which presents as
        "Tailscale is broken" when only PATH is."""
        source = SCRIPT.read_text()
        assert "Environment=PATH=" in source
        assert "/usr/local/bin" in source

    def test_it_runs_the_foreground_form_under_systemd(self):
        """No PID file and no backgrounding: systemd supervises."""
        source = SCRIPT.read_text()
        assert "start-foreground" in source
        foreground = source.split("cmd_start_foreground()")[1][:500]
        assert "exec " in foreground
        assert "PID_FILE" not in foreground


class TestRemoveKeepsTheKeys:
    def test_the_key_store_is_never_deleted(self):
        """Keys are not recoverable and may still be in use elsewhere.

        Everything else in the config directory can be rebuilt.
        """
        body = SCRIPT.read_text().split("cmd_remove()")[1][:1200]
        assert "! -name keymaster" in body
        assert "Keeping the key store" in body

    def test_it_requires_typing_the_word(self):
        body = SCRIPT.read_text().split("cmd_remove()")[1][:800]
        assert "'remove'" in body or '"remove"' in body


@pytest.mark.skipif(
    subprocess.run(["python3", "-c", "import fastapi"], capture_output=True).returncode != 0,
    reason="needs the [t1api] extra",
)
class TestAgainstARealServer:
    def test_start_status_and_stop(self, configured):
        home, config = configured
        try:
            started = run("start", home=home, config=config, timeout=120)
            assert started.returncode == 0, started.stdout + started.stderr
            assert "Running" in started.stdout

            status = run("status", home=home, config=config)
            assert "running" in status.stdout
            assert "t1 v" in status.stdout, "status did not reach /status"
        finally:
            run("kill", home=home, config=config)

    def test_start_is_idempotent(self, configured):
        home, config = configured
        try:
            run("start", home=home, config=config, timeout=120)
            again = run("start", home=home, config=config, timeout=60)
            assert "Already running" in again.stdout
        finally:
            run("kill", home=home, config=config)

    def test_key_uses_the_servers_own_store(self, configured):
        """gkey and the server must agree about where the keys live.

        They did not until T1_KEYMASTER_DIR was honoured by both: keys
        the operator minted were invisible to their own server.
        """
        home, config = configured
        result = run("key", "create", "-v", "v2", home=home, config=config, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        assert list((config / "keymaster").glob("*.json")), "minted somewhere else"


class TestCreateWithoutACheckout:
    """`pip install hypernix` gives you the manager and no installer.

    `create` hands off to install-t1.sh, which is a checkout file. From a
    wheel there is no checkout, and a dead end there would mean the
    manager cannot create the thing it manages.
    """

    def _isolated(self, tmp_path):
        """Run the script from a copy with no install-t1.sh anywhere near it.

        That is what a wheel install looks like: the program sits in a bin
        directory beside other console scripts, and the repo is not there.
        """
        binned = tmp_path / "prefix" / "bin"
        binned.mkdir(parents=True)
        copied = binned / "hypernix-t1"
        copied.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
        copied.chmod(0o755)
        return copied

    def _run(self, copied: Path, *argv: str, home: Path, config: Path):
        return subprocess.run(
            [BASH, str(copied), *argv],
            capture_output=True, text=True, timeout=120,
            env={
                **os.environ,
                "HOME": str(home),
                "T1_CONFIG_DIR": str(config),
                "NO_COLOR": "1",
                "PYTHONPATH": str(REPO_ROOT / "src"),
            },
            cwd=str(tempfile.gettempdir()),
        )

    def test_it_writes_a_usable_config(self, tmp_path):
        home, config = tmp_path / "home", tmp_path / "cfg"
        home.mkdir()
        copied = self._isolated(tmp_path)

        result = self._run(copied, "create", "--port", "8971",
                           home=home, config=config)

        assert result.returncode == 0, result.stdout + result.stderr
        env = (config / ".env").read_text()
        assert "T1_PORT=8971" in env
        assert "T1_HOST=127.0.0.1" in env
        assert f"T1_KEYMASTER_DIR={config}/keymaster" in env

    def test_the_secret_is_real_and_the_file_is_not_readable(self, tmp_path):
        home, config = tmp_path / "home", tmp_path / "cfg"
        home.mkdir()
        copied = self._isolated(tmp_path)

        self._run(copied, "create", home=home, config=config)

        env_file = config / ".env"
        assert oct(env_file.stat().st_mode)[-3:] == "600"
        secret = next(
            line.split("=", 1)[1]
            for line in env_file.read_text().splitlines()
            if line.startswith("T1_TOKEN_SECRET=")
        )
        assert len(secret) == 64
        assert int(secret, 16)              # hex, and not a placeholder
        assert len(set(secret)) > 4

    def test_two_creates_produce_different_secrets(self, tmp_path):
        """A fixed secret would validate every other install's tokens."""
        secrets = []
        for i in range(2):
            home, config = tmp_path / f"home{i}", tmp_path / f"cfg{i}"
            home.mkdir()
            copied = self._isolated(tmp_path / f"run{i}")
            self._run(copied, "create", home=home, config=config)
            secrets.append((config / ".env").read_text())
        assert secrets[0] != secrets[1]

    def test_it_refuses_to_overwrite_without_force(self, tmp_path):
        home, config = tmp_path / "home", tmp_path / "cfg"
        home.mkdir()
        copied = self._isolated(tmp_path)

        self._run(copied, "create", home=home, config=config)
        first = (config / ".env").read_text()
        again = self._run(copied, "create", home=home, config=config)

        assert again.returncode != 0
        assert "already exists" in again.stdout + again.stderr
        assert (config / ".env").read_text() == first

        forced = self._run(copied, "create", "--force", home=home, config=config)
        assert forced.returncode == 0
        assert (config / ".env").read_text() != first

    def test_it_says_what_the_minimal_config_does_not_cover(self, tmp_path):
        """Silence here would read as "configured", which it is not."""
        home, config = tmp_path / "home", tmp_path / "cfg"
        home.mkdir()
        copied = self._isolated(tmp_path)

        result = self._run(copied, "create", home=home, config=config)
        combined = result.stdout + result.stderr

        assert "install-t1.sh" in combined
        for missing in ("allowlist", "rate limits", "pricing"):
            assert missing in combined.lower(), missing

    def test_a_bad_port_is_refused(self, tmp_path):
        home, config = tmp_path / "home", tmp_path / "cfg"
        home.mkdir()
        copied = self._isolated(tmp_path)

        result = self._run(copied, "create", "--port", "eight",
                           home=home, config=config)

        assert result.returncode != 0
        assert not (config / ".env").exists()

    def test_the_checkout_still_hands_off_to_the_installer(self, tmp_path):
        """The guided setup stays the default wherever it is available."""
        home, config = tmp_path / "home", tmp_path / "cfg"
        home.mkdir()
        result = subprocess.run(
            [BASH, str(SCRIPT), "create", "--help"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "HOME": str(home),
                 "T1_CONFIG_DIR": str(config), "NO_COLOR": "1"},
        )
        # install-t1.sh --help, not the minimal path's "Unknown option".
        assert "install-t1.sh" in result.stdout
        assert "--non-interactive" in result.stdout


class TestItIsActuallyInstalled:
    def test_pyproject_ships_it_on_path(self):
        """[project.scripts] cannot carry a shell program; script-files can.

        Without this the docs promise a `hypernix-t1` that `pip install
        hypernix` does not provide.
        """
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'script-files = ["bin/hypernix-t1"]' in text

    def test_the_sdist_carries_it_and_the_installer(self):
        """tests/ ships in the sdist and runs both of these files."""
        manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        assert "include install-t1.sh" in manifest
        assert "recursive-include bin *" in manifest
