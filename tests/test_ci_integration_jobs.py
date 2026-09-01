"""The release gate: a live API, a real key, a fake model, an iPhone.

Nothing here runs GitHub Actions — it cannot. What it does check is that
the workflow says what it is supposed to say, and that the scripts those
jobs invoke actually work, which is the half that breaks silently.

The shape is not the obvious one, deliberately. Hosted runners cannot
reach each other over the network, so "job A hosts the server and job B
connects to it" is not expressible: there is no route between two
runners. Each job brings up its own server. The split that matters
survives — one job drives the API from outside the process, the other
drives the app against a real server, and no publish step runs until both
are green.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RELEASE = REPO_ROOT / ".github" / "workflows" / "public-release.yml"
SCRIPTS = REPO_ROOT / "scripts" / "ci"

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestTheJobsExist:
    @pytest.mark.parametrize("path", [CI, RELEASE])
    def test_both_workflows_have_both_jobs(self, path):
        jobs = workflow(path)["jobs"]
        assert "integration-api" in jobs
        assert "integration-ios" in jobs

    def test_ci_runs_them_after_the_tests(self):
        jobs = workflow(CI)["jobs"]
        assert jobs["integration-api"]["needs"] == "test"
        assert jobs["integration-ios"]["needs"] == "test"

    def test_the_ios_job_runs_on_macos(self):
        """A simulator needs a Mac. Anywhere else the job would look
        green because xcodebuild never ran."""
        assert workflow(CI)["jobs"]["integration-ios"]["runs-on"] == "macos-latest"

    def test_each_job_mints_its_own_key(self):
        jobs = workflow(CI)["jobs"]
        for name in ("integration-api", "integration-ios"):
            steps = json.dumps(jobs[name]["steps"])
            assert "integration_probe.py" in steps, name

    def test_both_jobs_agree_with_gkey_about_the_key_store(self):
        """The server reads T1_KEYMASTER_DIR and so does gkey.

        Leaving either to infer it from $HOME is how a key gets minted
        into a store the server is not reading — which presents as a
        rejected key, several layers from the cause.
        """
        jobs = workflow(CI)["jobs"]
        for name in ("integration-api", "integration-ios"):
            assert "T1_KEYMASTER_DIR" in jobs[name]["env"], name


class TestTeardown:
    @pytest.mark.parametrize("name", ["integration-api", "integration-ios"])
    def test_teardown_runs_even_when_the_test_failed(self, name):
        """A job that leaves credentials behind on failure is worse than
        one that fails."""
        steps = workflow(CI)["jobs"][name]["steps"]
        teardown = [s for s in steps if "key" in (s.get("name") or "").lower()
                    and "delete" in (s.get("name") or "").lower()
                    or "Shut it" in (s.get("name") or "")]
        assert teardown, f"{name} has no teardown step"
        assert any(s.get("if") == "always()" for s in teardown), (
            f"{name} tears down only on success"
        )

    @pytest.mark.parametrize("name", ["integration-api", "integration-ios"])
    def test_teardown_fails_the_job_if_keys_remain(self, name):
        """Checked, not assumed. A teardown that cannot fail is a comment."""
        steps = json.dumps(workflow(CI)["jobs"][name]["steps"])
        assert "left ${remaining} keys behind" in steps, name

    def test_the_ios_job_shuts_the_simulator_down(self):
        steps = json.dumps(workflow(CI)["jobs"]["integration-ios"]["steps"])
        assert "simctl shutdown" in steps


class TestTheReleaseIsGated:
    @pytest.mark.parametrize(
        "job", ["github-release", "pypi-publish", "testpypi-publish"]
    )
    def test_nothing_publishes_until_both_pass(self, job):
        needs = workflow(RELEASE)["jobs"][job]["needs"]
        assert "integration-api" in needs, job
        assert "integration-ios" in needs, job

    def test_the_release_jobs_run_after_the_build(self):
        jobs = workflow(RELEASE)["jobs"]
        assert jobs["integration-api"]["needs"] == "cut"
        assert jobs["integration-ios"]["needs"] == "cut"


class TestTheFakeModel:
    """A stub over HTTP, not a mock patched into the bridge.

    The stub goes through the real bridge, the real routing engine and
    the real serialisation, which is where the interesting failures are.
    A mock would prove the mock works.
    """

    @pytest.fixture(scope="class")
    def server(self):
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, str(SCRIPTS / "fake_model_server.py"), "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                _OPENER.open(base + "/v1/models", timeout=1).read()
                break
            except OSError:
                time.sleep(0.2)
        else:
            process.kill()
            pytest.fail("the fake model never came up")
        yield base
        process.terminate()
        process.wait(timeout=10)

    def test_it_lists_a_model(self, server):
        body = json.loads(_OPENER.open(server + "/v1/models", timeout=5).read())
        assert [m["id"] for m in body["data"]] == ["hypernix-ci-echo"]

    def test_a_chat_returns_the_marker(self, server):
        """Distinctive on purpose: a test asserting on "hello" can pass
        against a server that echoed the prompt back."""
        request = urllib.request.Request(
            server + "/v1/chat/completions",
            data=json.dumps(
                {"model": "hypernix-ci-echo",
                 "messages": [{"role": "user", "content": "ping"}]}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        body = json.loads(_OPENER.open(request, timeout=5).read())
        content = body["choices"][0]["message"]["content"]
        assert "CI-ECHO-OK" in content

    def test_it_proves_the_prompt_arrived(self, server):
        """Otherwise the check passes against a server that ignored the
        request body entirely."""
        request = urllib.request.Request(
            server + "/v1/chat/completions",
            data=json.dumps(
                {"messages": [{"role": "user", "content": "distinctive-phrase"}]}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        body = json.loads(_OPENER.open(request, timeout=5).read())
        assert "distinctive-phrase" in body["choices"][0]["message"]["content"]

    def test_it_understands_vision_style_parts(self, server):
        """The app sends content as a list of parts, not a string."""
        request = urllib.request.Request(
            server + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{
                    "role": "user",
                    "content": [{"type": "text", "text": "look-at-this"}],
                }]
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        body = json.loads(_OPENER.open(request, timeout=5).read())
        assert "look-at-this" in body["choices"][0]["message"]["content"]

    def test_it_reports_usage(self, server):
        """The usage meter records what a call cost; zero tokens would
        make every cost assertion downstream vacuous."""
        request = urllib.request.Request(
            server + "/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "x" * 40}]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        body = json.loads(_OPENER.open(request, timeout=5).read())
        assert body["usage"]["total_tokens"] > 0


class TestTheProbeScript:
    def test_it_parses(self):
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(SCRIPTS / "integration_probe.py")],
            check=True,
        )

    def test_it_deletes_its_keys_in_a_finally(self):
        """Teardown belongs in `finally`, not after the last assert: the
        interesting case is the run that failed."""
        source = (SCRIPTS / "integration_probe.py").read_text()
        finally_block = source[source.index("    finally:"):]
        assert "revoke_key" in finally_block

    def test_it_bypasses_the_proxy(self):
        """CI runners set HTTP_PROXY more often than not, and a proxy in
        between answers a different question than "is this server up"."""
        source = (SCRIPTS / "integration_probe.py").read_text()
        assert "ProxyHandler({})" in source

    def test_it_waits_rather_than_sleeping_a_fixed_time(self):
        """A fixed sleep is either too short on a loaded runner or wasted
        time on a fast one, and is the usual reason CI is flaky."""
        source = (SCRIPTS / "integration_probe.py").read_text()
        assert "def wait_for(" in source
