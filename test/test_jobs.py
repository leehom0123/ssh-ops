#!/usr/bin/env python3
"""Interface tests for the background-job state machine (ssh_client.jobs).

JobStore is the deep module: these tests drive its small interface against
a scripted runner double (no real SSH), pinning the remote marker protocol
the wrapper writes, the state parsing, and the kill sequence.
Live lifecycle tests are `live`-marked (SSH_TEST_SERVER gated).
"""
import json
import re
import time
import subprocess
import shutil
import pytest
from unittest.mock import MagicMock, patch

from ssh_client import SSHConnection
from ssh_client.jobs import JobStore


@pytest.mark.parametrize("sudo_mode", ["password", "cached", "nopasswd"])
@pytest.mark.parametrize("job_timeout", [0, 10])
def test_sudo_job_password_never_reaches_command_stdin(tmp_path, sudo_mode, job_timeout):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash required for wrapper execution")
    conn = _conn()
    puts = _capture_puts(conn)
    conn.run = _Runner({"setsid": "launched", "cat": "7\n"})
    conn.job_start("cat; printf 'finished\\n'", sudo=True, timeout=job_timeout, workdir=".")
    for path, (data, _) in puts.items():
        (tmp_path / path.rsplit("/", 1)[-1]).write_bytes(data)
    wrapper = (tmp_path / "wrapper.sh").read_text(encoding="utf-8")
    wrapper = re.sub(r"^J=.*$", "J=.", wrapper, count=1, flags=re.M)
    # Model sudo's stdin consumption, not privilege elevation. Both skipped
    # prompt modes must leave the password unread to exercise the leak.
    fake_sudo = "sudo() { shift 3; "
    if sudo_mode == "password":
        fake_sudo += 'IFS= read -r supplied; [ "$supplied" = pw ] || return 91; '
    fake_sudo += '"$@"; };\n'
    result = subprocess.run([bash, "-c", fake_sudo + wrapper], cwd=tmp_path,
                            input=b"", capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "exit").read_text().strip() == "0"
    assert (tmp_path / "out.log").read_text() == "finished\n"
    assert not (tmp_path / "pass").exists()


@pytest.mark.parametrize("consume_password", [True, False])
def test_ordinary_sudo_password_never_reaches_command_stdin(consume_password):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash required for sudo command execution")
    command, password = _conn()._prepare_sudo("cat; printf 'finished\\n'")
    fake_sudo = "sudo() { shift 3; "
    if consume_password:
        fake_sudo += 'IFS= read -r supplied; [ "$supplied" = pw ] || return 91; '
    fake_sudo += '"$@"; };\n'
    result = subprocess.run([bash, "-c", fake_sudo + command], input=(password + "\n").encode(),
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"finished\n"


def _conn(cfg=None, **attrs):
    conn = SSHConnection({"host": "example.test", "user": "tester",
                          "sudo_password": "pw",
                          "jobs_dir": "/opt/scripts/.jobs", **(cfg or {})})
    conn.connect = MagicMock()
    conn._client = MagicMock()
    conn.scripts_dir = "/opt/scripts"
    for k, v in attrs.items():
        setattr(conn, k, v)
    return conn


class _Runner:
    """Scripted conn.run: answer each command whose text contains a key."""

    def __init__(self, answers, default=""):
        self.answers = answers
        self.default = default
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        for key, stdout in self.answers.items():
            if key in cmd:
                return {"stdout": stdout, "stderr": "", "code": 0}
        return {"stdout": self.default, "stderr": "", "code": 0}


def _capture_puts(conn):
    puts = {}

    def put(path, data, mode=None):
        puts[path] = (data, mode)

    conn._remote_put_bytes = MagicMock(side_effect=lambda p, d, mode=None:
                                       puts.__setitem__(p, (d, mode)))
    return puts


# ── guards ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("shell", ["cmd", "powershell"])
def test_job_start_requires_bash(shell):
    conn = _conn({"shell": shell})
    with pytest.raises(ValueError, match="shell: bash"):
        conn.job_start("dir")


def test_job_start_requires_sudo_password_when_sudo():
    conn = _conn({"sudo_password": None})
    with pytest.raises(ValueError, match="sudo_password"):
        conn.job_start("ls", sudo=True)


def test_job_id_validation_rejects_traversal():
    store = JobStore(_conn())
    for bad in ("../../etc", "job-", "notajob-1", "job-a b", 42):
        with pytest.raises(ValueError, match="Invalid job id"):
            store._job_dir(bad)
    assert store._job_dir("job-20261113-101500-abcd12") == \
        "/opt/scripts/.jobs/job-20261113-101500-abcd12"


def test_job_start_honours_blacklist():
    conn = _conn({"blacklist": [r"rm\s+-rf"]})
    with pytest.raises(ValueError, match="blacklist"):
        conn.job_start("rm -rf /")


# ── job_start: files and wrapper ──────────────────────────────────
def test_job_start_writes_files_and_reports_pid():
    conn = _conn()
    puts = _capture_puts(conn)
    conn.run = _Runner({
        "setsid nohup bash": "launched\n",
        "cat": "4242\n",  # pid probe
    })
    result = conn.job_start("echo hi", name="demo")
    assert result["code"] == 0
    assert re.fullmatch(r"job-\d{8}-\d{6}-[0-9a-f]{6}", result["job_id"])
    assert result["pid"] == "4242"
    base = f"/opt/scripts/.jobs/{result['job_id']}"
    cmd_bytes, _ = puts[f"{base}/cmd"]
    assert cmd_bytes == b"echo hi"
    meta = json.loads(puts[f"{base}/meta"][0])
    assert meta["name"] == "demo" and meta["sudo"] is False
    wrapper, mode = puts[f"{base}/wrapper.sh"]
    assert mode == 0o700
    text = wrapper.decode()
    assert base in text and "J=" in text
    assert 'echo $$ > "$J/pid"' in text          # pid first: kill targets the group
    assert 'CMD=$(cat "$J/cmd")' in text          # user command never gets quoted
    assert 'bash -c "$CMD" >"$J/out.log" 2>"$J/err.log" </dev/null\n' in text
    assert 'echo $EC > "$J/exit.tmp" && mv "$J/exit.tmp" "$J/exit"' in text
    assert "/dev/null" in text                     # detached from the channel
    assert any("setsid nohup bash" in c[0] and "wrapper.sh" in c[0]
               for c in conn.run.calls)


def test_job_start_sudo_writes_mode600_pass_and_stdin_password():
    conn = _conn()
    puts = _capture_puts(conn)
    conn.run = _Runner({"setsid": "launched", "cat": "7\n"})
    conn.job_start("apt upgrade", timeout=600, sudo=True)
    base = "/opt/scripts/.jobs"
    pass_paths = [p for p in puts if p.endswith("/pass")]
    assert pass_paths and puts[pass_paths[0]][1] == 0o600
    wrapper = puts[[p for p in puts if p.endswith("wrapper.sh")][0]][0].decode()
    assert "printf '%s\\n' \"$SP\" | sudo -S -p '' bash -c" in wrapper
    # The password pipe must survive: no </dev/null on the sudo launch line
    assert 'timeout 600 bash -c "$CMD" >"$J/out.log" 2>"$J/err.log"\n' in wrapper
    assert '2>"$J/err.log" </dev/null' not in wrapper
    assert 'rm -f "$J/pass"' in wrapper  # password file lives only moments


def test_job_start_cd_failure_marks_exited():
    # The probe must distinguish "started" from "wrapper died instantly"
    # using the real markers; a constant echo cannot.
    conn = _conn()
    puts = _capture_puts(conn)
    conn.run = _Runner({"setsid": "", "cat": "EXITED1\n"})
    result = conn.job_start("pwd", workdir="/nope")
    assert result["pid"] == ""
    assert "exited immediately" in result["stdout"]
    wrapper = puts[[p for p in puts if p.endswith("wrapper.sh")][0]][0].decode()
    assert "cannot cd" in wrapper and 'echo 1 > "$J/exit.tmp"' in wrapper


# ── state parsing ──────────────────────────────────────────────────
@pytest.mark.parametrize("stdout,expected", [
    ("exited|0|\n", {"state": "exited", "exit_code": "0", "pid": ""}),
    ("running||4242", {"state": "running", "exit_code": "", "pid": "4242"}),
    ("killed||9\n", {"state": "killed", "exit_code": "", "pid": "9"}),
    ("lost||555", {"state": "lost", "exit_code": "", "pid": "555"}),
    ("\n", {"state": "lost", "exit_code": "", "pid": ""}),
])
def test_job_shell_state_parsing(stdout, expected):
    conn = _conn()
    conn.run = MagicMock(return_value={"stdout": stdout, "stderr": "",
                                       "code": 0})
    got = JobStore(conn)._state("/j", "job-x", sudo=False)
    assert got == expected
    cmd = conn.run.call_args.args[0]
    # A live pid must still name the job, otherwise a recycled pid would
    # pin a dead job in 'running' forever.
    assert "/proc/$pid/cmdline" in cmd and "grep -q" in cmd


def test_job_status_reads_meta_then_logs_with_job_privilege():
    conn = _conn()
    meta = {"id": "job-a", "name": "n", "sudo": True, "started": "t",
            "timeout": 0, "workdir": "", "command": "id -u"}
    conn.run = _Runner({"meta": json.dumps(meta), "tail -n": "0\n"})
    with patch.object(JobStore, "_state",
                      return_value={"state": "exited", "exit_code": "0",
                                    "pid": "1"}) as state:
        got = conn.job_status("job-a", tail_lines=5)
    assert got["sudo"] is True and got["state"] == "exited"
    assert got["stdout"] == "0\n"
    tail_calls = [c for c in conn.run.calls if "tail -n" in c[0]]
    assert tail_calls and all(c[1].get("sudo") for c in tail_calls)


def test_job_status_unknown_id_raises():
    conn = _conn()
    conn.run = MagicMock(return_value={"stdout": "", "stderr": "", "code": 0})
    with pytest.raises(FileNotFoundError, match="Job not found"):
        conn.job_status("job-20200101-000000-ffffff")


def test_job_kill_only_signals_running_jobs():
    meta = json.dumps({"id": "job-a", "name": "", "sudo": False,
                       "started": "", "timeout": 0, "workdir": "",
                       "command": ""})
    conn = _conn()
    conn.run = _Runner({"meta": meta})
    with patch.object(JobStore, "_state",
                      return_value={"state": "exited", "exit_code": "0",
                                    "pid": "5"}):
        not_running = conn.job_kill("job-a")
        assert not_running["killed"] is False
    conn2 = _conn()
    conn2.run = _Runner({"meta": meta})
    with patch.object(JobStore, "_state",
                      side_effect=[{"state": "running", "exit_code": "",
                                    "pid": "4242"},
                                   {"state": "killed", "exit_code": "",
                                    "pid": "4242"}]):
        killed = conn2.job_kill("job-a")
    assert killed["killed"] is True and killed["state"] == "killed"
    cmds = [c[0] for c in conn2.run.calls]
    assert any("touch" in c and "killed" in c for c in cmds)
    assert any("kill -s TERM -- -4242" in c for c in cmds)
    assert any("kill -s KILL -- -4242" in c for c in cmds)


# ── job_list ───────────────────────────────────────────────────────
def test_job_list_parses_table_and_nojobs():
    conn = _conn()
    conn.run = MagicMock(return_value={
        "stdout": "job-1|running||123|sleep 1\n"
                  "job-2|exited|0|45|echo a|b\n",  # command may hold |
        "stderr": "", "code": 0})
    got = conn.job_list()
    assert got["count"] == 2
    assert got["jobs"][0] == {"id": "job-1", "state": "running",
                              "exit_code": "", "command": "sleep 1"}
    assert got["jobs"][1]["command"] == "echo a|b"
    conn2 = _conn()
    conn2.run = MagicMock(return_value={"stdout": "NOJOBS\n", "stderr": "",
                                        "code": 0})
    assert conn2.job_list()["count"] == 0


def test_job_list_clean_days_adds_find_prune():
    conn = _conn()
    conn.run = MagicMock(return_value={"stdout": "NOJOBS\n", "stderr": "",
                                       "code": 0})
    conn.job_list(clean_days=7, sudo=True)
    script = conn.run.call_args.args[0]
    assert "-mtime +7" in script and "rm -rf" in script
    assert conn.run.call_args.kwargs["sudo"] is True


# ── Live lifecycle ─────────────────────────────────────────────────
@pytest.mark.live
def test_live_job_lifecycle(live_server):
    import ssh_client
    conn = ssh_client.pool.get(live_server)
    if conn.shell != "bash":
        pytest.skip("jobs require a bash server")
    started = conn.job_start("echo job-hello; exit 3", name="pytest")
    job_id = started["job_id"]
    try:
        # The command finishes instantly; poll until the exit marker lands.
        status = {}
        for _ in range(20):
            status = conn.job_status(job_id)
            if status["state"] == "exited":
                break
            time.sleep(0.5)
        assert status["state"] == "exited", status
        assert status["exit_code"] == "3"
        assert "job-hello" in status["stdout"]
        listed = conn.job_list()
        assert job_id in {j["id"] for j in listed["jobs"]}
    finally:
        conn.run(f"rm -rf {conn.jobs_dir}/{job_id}", internal=True)


@pytest.mark.live
def test_live_job_kill(live_server):
    import ssh_client
    conn = ssh_client.pool.get(live_server)
    if conn.shell != "bash":
        pytest.skip("jobs require a bash server")
    started = conn.job_start("sleep 60")
    job_id = started["job_id"]
    try:
        killed = conn.job_kill(job_id)
        assert killed["killed"] is True
        assert killed["state"] in ("killed", "lost", "exited")
    finally:
        conn.run(f"rm -rf {conn.jobs_dir}/{job_id}", internal=True)
