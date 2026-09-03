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


def _function_body(source: str, name: str) -> str:
    """The body of a shell function, from its `name()` to the closing brace.

    A fixed character window would instead measure how much comment the
    function carries, and go red when someone explains themselves.
    """
    start = source.index(f"{name}()")
    end = source.index("\n}", start)
    return source[start:end]


def run(*argv: str, home: Path, config: Path, timeout: int = 60):
    """Run the script. `.output` is stdout+stderr.

    Warnings go to stderr — correct for a status line, and easy to miss
    when asserting.
    """
    result = subprocess.run(
        [BASH, str(SCRIPT), *argv],
        capture_output=True,
        text=True, encoding="utf-8",
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
        "T1_TOKEN_SECRET=" + "d" * 64 + "\n",
        encoding="utf-8",
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
        # warning, not style, and matching the other two shell tests. The
        # info and style tiers are advisory and their contents move between
        # shellcheck releases: 0.8.0 raises SC2009 on `ps -p "$pid" | grep`,
        # 0.9.0 through 0.11.0 do not, because -p already scopes it to one
        # process. Gating CI on those tiers makes the build depend on which
        # shellcheck the runner happens to ship, which is how a commit that
        # touched nothing turns red.
        result = subprocess.run(
            ["shellcheck", "--severity=warning", str(SCRIPT)],
            capture_output=True, text=True, encoding="utf-8",
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
        (config / "server.pid").write_text("999999\n", encoding="utf-8")
        assert "not running" in run("status", home=home, config=config).output

    def test_someone_elses_process_is_not_claimed(self, configured):
        """The dangerous case: the PID exists, and is not ours."""
        home, config = configured
        victim = subprocess.Popen(["sleep", "120"])
        try:
            (config / "server.pid").write_text(f"{victim.pid}\n", encoding="utf-8")
            assert "not running" in run("status", home=home, config=config).output
            # And stop must not kill it.
            run("stop", home=home, config=config)
            assert victim.poll() is None, "it killed an unrelated process"
        finally:
            victim.kill()
            victim.wait(timeout=10)

    def test_it_checks_the_command_line_not_just_the_pid(self):
        """Both checks, and read from the function, not from a byte window.

        This used to slice the first 600 characters after `server_pid()`,
        which made it a test of how much comment the function carries: a
        four-line note pushed the `ps` line past the window and the test
        failed while the code was correct.
        """
        body = _function_body(SCRIPT.read_text(encoding="utf-8"), "server_pid")
        assert "kill -0" in body, "does not check the PID is alive"
        assert "hypernix.t1api" in body, "does not check the command line"


class TestConfig:
    def test_the_env_file_is_read_not_sourced(self):
        """.env is a file people edit by hand; sourcing runs whatever
        ends up in it."""
        source = SCRIPT.read_text(encoding="utf-8")
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
        assert 'T1_*|HYPERNIX_*)' in SCRIPT.read_text(encoding="utf-8")


class TestTheSystemdUnit:
    def test_exec_start_is_absolute(self, configured):
        """systemd will not resolve a relative path, and the unit it
        wrote silently refused to start."""
        home, config = configured
        # --write-only installs the unit without touching the user bus.
        # Without it this test skipped wherever `systemctl --user` cannot
        # reach a session -- containers, plain ssh, WSL -- which is
        # everywhere CI runs, so the assertion below never ran.
        run("autostart", "on", "--write-only", home=home, config=config)
        unit = home / ".config" / "systemd" / "user" / "hypernix-t1.service"
        if not unit.exists():
            pytest.skip("systemd not available to write a unit here")
        line = next(
            row for row in unit.read_text(encoding="utf-8").splitlines() if row.startswith("ExecStart=")
        )
        path = line.split("=", 1)[1].split()[0]
        assert path.startswith("/"), line

    def test_the_unit_sets_an_explicit_path(self):
        """A user unit gets a minimal PATH, and a tailscale in
        /usr/local/bin then becomes invisible — which presents as
        "Tailscale is broken" when only PATH is."""
        source = SCRIPT.read_text(encoding="utf-8")
        assert "Environment=PATH=" in source
        assert "/usr/local/bin" in source

    def test_a_machine_with_no_user_bus_says_what_to_do(self, configured):
        """systemctl being on PATH is not the same as there being a
        session to talk to. Containers, plain ssh and WSL all fail here,
        and the bare systemd error -- "Failed to connect to bus: No
        medium found" -- says nothing about what to do next.

        The guard probes for the bus directly rather than inferring it
        from the exit code, which is what the first version of this test
        did and why it failed on every GitHub runner. A runner *has* a
        user bus, so the no-bus branch is never reached there -- but the
        run still exits non-zero, because HOME is redirected to a tmp
        directory and systemd cannot see the unit written into it
        ("Unit file hypernix-t1.service does not exist"). Reading a
        non-zero exit as "took the branch I meant" turned a skip into a
        failure on Linux, macOS and Windows at once.
        """
        import shutil
        import subprocess

        home, config = configured
        if shutil.which("systemctl") is None:
            pytest.skip("no systemctl to probe")
        probe = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True, timeout=30, check=False,
        )
        if probe.returncode == 0:
            pytest.skip(
                "this machine has a working user bus, so the no-bus branch "
                "cannot be exercised here"
            )

        result = run("autostart", "on", home=home, config=config)
        assert result.returncode != 0
        message = result.stdout + result.stderr
        assert "enable-linger" in message or "session startup" in message
        assert "--write-only" in message

    def test_an_unknown_autostart_argument_is_refused(self, configured):
        """It used to take ``${1:-on}`` and ignore everything else, so a
        typo silently enabled autostart instead of reporting itself."""
        home, config = configured
        result = run("autostart", "onn", home=home, config=config)
        assert result.returncode != 0

    def test_it_runs_the_foreground_form_under_systemd(self):
        """No PID file and no backgrounding: systemd supervises."""
        source = SCRIPT.read_text(encoding="utf-8")
        assert "start-foreground" in source
        foreground = _function_body(source, "cmd_start_foreground")
        assert "exec " in foreground
        assert "PID_FILE" not in foreground


class TestRemoveKeepsTheKeys:
    def test_the_key_store_is_never_deleted(self):
        """Keys are not recoverable and may still be in use elsewhere.

        Everything else in the config directory can be rebuilt.
        """
        body = _function_body(SCRIPT.read_text(encoding="utf-8"), "cmd_remove")
        assert "! -name keymaster" in body
        assert "Keeping the key store" in body

    def test_it_requires_typing_the_word(self):
        body = _function_body(SCRIPT.read_text(encoding="utf-8"), "cmd_remove")
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
            capture_output=True, text=True, encoding="utf-8", timeout=120,
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
        env = (config / ".env").read_text(encoding="utf-8")
        assert "T1_PORT=8971" in env
        assert "T1_HOST=127.0.0.1" in env
        assert f"T1_KEYMASTER_DIR={config}/keymaster" in env

    def test_the_secret_is_real_and_the_file_is_not_readable(self, tmp_path):
        home, config = tmp_path / "home", tmp_path / "cfg"
        home.mkdir()
        copied = self._isolated(tmp_path)

        self._run(copied, "create", home=home, config=config)

        env_file = config / ".env"
        if os.name != "nt":
            # Windows has no owner/group/other permission bits to set;
            # chmod there moves the read-only flag and nothing else, so
            # st_mode reads 666 however the file was created. Asserting
            # 600 on Windows tests the platform, not this script.
            assert oct(env_file.stat().st_mode)[-3:] == "600"
        secret = next(
            line.split("=", 1)[1]
            for line in env_file.read_text(encoding="utf-8").splitlines()
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
            secrets.append((config / ".env").read_text(encoding="utf-8"))
        assert secrets[0] != secrets[1]

    def test_it_refuses_to_overwrite_without_force(self, tmp_path):
        home, config = tmp_path / "home", tmp_path / "cfg"
        home.mkdir()
        copied = self._isolated(tmp_path)

        self._run(copied, "create", home=home, config=config)
        first = (config / ".env").read_text(encoding="utf-8")
        again = self._run(copied, "create", home=home, config=config)

        assert again.returncode != 0
        assert "already exists" in again.stdout + again.stderr
        assert (config / ".env").read_text(encoding="utf-8") == first

        forced = self._run(copied, "create", "--force", home=home, config=config)
        assert forced.returncode == 0
        assert (config / ".env").read_text(encoding="utf-8") != first

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
            capture_output=True, text=True, encoding="utf-8", timeout=120,
            env={**os.environ, "HOME": str(home),
                 "T1_CONFIG_DIR": str(config), "NO_COLOR": "1"},
        )
        # install-t1.sh --help, not the minimal path's "Unknown option".
        assert "install-t1.sh" in result.stdout
        assert "--non-interactive" in result.stdout


class TestTheTwoCreatePathsAgree:
    """``hypernix-t1 create`` runs one of two programs.

    From a checkout it execs ``install-t1.sh``; from a wheel there is no
    installer and it writes a minimal config itself. Both are documented
    by the same ``--help``, so both have to accept the same flags and
    write the same keys — and neither of those was true.
    """

    def test_the_installer_accepts_the_flags_the_manager_documents(self):
        """``create --host H --port N --force`` is in ``hypernix-t1
        --help``. From a checkout it reached install-t1.sh, which had
        never heard of any of them and died with "Unknown option:
        --port" — so the documented interface failed on exactly the
        machine a developer is sitting at."""
        installer = REPO_ROOT / "install-t1.sh"
        if not installer.is_file():
            pytest.skip("no checkout")
        source = installer.read_text(encoding="utf-8")
        for flag in ("--host)", "--port)", "--force)"):
            assert flag in source, flag

    def test_both_paths_write_the_key_the_manager_reads(self, tmp_path):
        """The consequential half. install-t1.sh put the bind address
        only into start-t1.sh, so ``hypernix-t1 start`` found no T1_HOST
        or T1_PORT, fell back to its own 127.0.0.1:8000 default, and
        started the server somewhere else — after which status, logs,
        key and test all pointed at an address nothing was listening on.
        """
        installer = REPO_ROOT / "install-t1.sh"
        if not installer.is_file():
            pytest.skip("no checkout")
        source = installer.read_text(encoding="utf-8")
        assert "T1_HOST=$BIND_HOST" in source
        assert "T1_PORT=$BIND_PORT" in source

        manager = SCRIPT.read_text(encoding="utf-8")
        assert 'setting T1_HOST' in manager
        assert 'setting T1_PORT' in manager

    def test_the_installer_refuses_to_clobber_an_env(self, tmp_path):
        """Regenerating the token secret invalidates every key already
        minted against it — a failure that surfaces later as "the server
        rejects my keys" rather than here as "the file was replaced".
        ``create_minimal`` already refused; the installer did not."""
        installer = REPO_ROOT / "install-t1.sh"
        if not installer.is_file():
            pytest.skip("no checkout")
        source = installer.read_text(encoding="utf-8")
        body = _function_body(source, "write_env")
        assert "FORCE_OVERWRITE" in body
        assert "already exists" in body


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
