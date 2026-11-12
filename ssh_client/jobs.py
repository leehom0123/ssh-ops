"""Job domain: background jobs whose state lives on the remote server.

``JobStore`` is the deep module: one small interface
(``start / status / kill / list``) hiding the remote marker-file protocol
(cmd, meta, wrapper.sh, pid, exit, killed, out.log, err.log), the sudo
password handling, and the process-group kill sequence.

Its only dependency is a connection object that provides
``run() / _cmd() / _check_command() / _remote_put_bytes() / connect()``
plus the attributes ``shell / jobs_dir / sudo_password`` — i.e.
``SSHConnection`` itself, or any test double that answers those calls.
``JobsMixin`` on ``SSHConnection`` is just one-line forwarding, so the
public call surface (``conn.job_start(...)``) does not change.
"""
import json
import re
import shlex
import time
import uuid

from . import config


class JobStore:
    """Remote state machine for background jobs (bash servers only)."""

    _ID_RE = re.compile(r"job-[A-Za-z0-9._-]+\Z")

    # POSIX sh function resolving a job dir to "state|exit_code|pid".
    # Shared by status/kill and list so the rules — and their bugs — can
    # never drift apart. A live pid only counts as running when its
    # command line mentions the job id: pids get reused, and a recycled
    # pid must not pin a dead job in 'running'.
    _STATE_FN = (
        "job_state() { J=\"$1\"; ID=\"$2\"; state='lost'; code=''; "
        "pid=$(cat \"$J/pid\" 2>/dev/null); "
        "if [ -f \"$J/exit\" ]; then state='exited'; code=$(cat \"$J/exit\"); "
        "elif [ -n \"$pid\" ] && kill -0 \"$pid\" 2>/dev/null; then "
        "if tr '\\0' ' ' < \"/proc/$pid/cmdline\" 2>/dev/null | grep -q -- \"$ID\"; "
        "then state='running'; "
        "elif ps -o args= -p \"$pid\" 2>/dev/null | grep -q -- \"$ID\"; "
        "then state='running'; fi; "
        "elif [ -f \"$J/killed\" ]; then state='killed'; fi; "
        "echo \"$state|$code|$pid\"; }"
    )

    def __init__(self, conn):
        self._conn = conn

    # ── internals (remote marker protocol) ─────────────────────────

    def _job_dir(self, job_id: str) -> str:
        if not isinstance(job_id, str) or not self._ID_RE.match(job_id):
            raise ValueError(f"Invalid job id: {job_id!r}")
        return f"{self._conn.jobs_dir}/{job_id}"

    def _state(self, job_dir_q: str, job_id: str, sudo: bool) -> dict:
        """Resolve one job's {state, exit_code, pid} from remote markers."""
        out = self._conn.run(
            self._STATE_FN + f"\njob_state {job_dir_q} {shlex.quote(job_id)}",
            timeout=15, sudo=sudo, internal=True)
        state, _, rest = out["stdout"].strip().partition("|")
        code, _, pid = rest.partition("|")
        return {"state": state or "lost", "exit_code": code, "pid": pid}

    def _meta(self, job_id: str) -> dict:
        """Read a job's meta JSON (user-owned even for sudo jobs)."""
        job_dir_q = shlex.quote(self._job_dir(job_id))
        out = self._conn.run(f"cat -- {job_dir_q}/meta 2>/dev/null || true",
                             timeout=15, internal=True)
        if not out["stdout"].strip():
            raise FileNotFoundError(f"Job not found: {job_id}")
        return json.loads(out["stdout"])

    # ── interface ──────────────────────────────────────────────────

    def start(self, command: str, name: str = None, timeout: int = 0,
              workdir: str = None, sudo: bool = False) -> dict:
        """Start a background job that outlives one command timeout.

        State (pid, exit code, output logs) is kept in ``jobs_dir/<id>/``
        on the remote, so it survives MCP restarts and dropped
        connections. The wrapper runs under ``setsid`` as its own process
        group, which lets ``kill`` take down the whole tree.

        Args:
            command: shell command line to run in the background
            name: optional human label (kept in listings)
            timeout: seconds after which the job is killed (0 = no limit)
            workdir: directory to run the command in (default: home)
            sudo: run as root (password via a 0600 file the wrapper reads
                and deletes before anything else can see it)
        """
        conn = self._conn
        if conn.shell != "bash":
            raise ValueError("Background jobs require a server with shell: bash")
        command = config._repair_surrogateescaped_command(command)
        command = conn._check_command(command)
        conn.connect()
        if sudo and not conn.sudo_password:
            raise ValueError("sudo_password not configured for this server")

        job_id = (time.strftime("job-%Y%m%d-%H%M%S") + "-"
                  + uuid.uuid4().hex[:6])
        job_dir = self._job_dir(job_id)
        mkdir = conn.run(conn._cmd("mkdir", path=job_dir), timeout=15,
                         internal=True)
        if mkdir["code"] != 0:
            raise RuntimeError(
                f"cannot create job dir {job_dir}: {mkdir['stderr'].strip()[:200]}")

        meta = {
            "id": job_id,
            "name": name or "",
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "timeout": int(timeout or 0),
            "workdir": workdir or "",
            "sudo": bool(sudo),
            "command": command,
        }
        # The command travels in its own file, so no quoting of user
        # content is needed anywhere in the wrapper.
        conn._remote_put_bytes(f"{job_dir}/cmd", command.encode("utf-8"))
        conn._remote_put_bytes(f"{job_dir}/meta",
                               json.dumps(meta).encode("utf-8"))
        if sudo:
            conn._remote_put_bytes(f"{job_dir}/pass",
                                   (conn.sudo_password + "\n").encode("utf-8"),
                                   mode=0o600)
        inner = "bash -c \"$CMD\""
        if meta["timeout"]:
            inner = f"timeout {meta['timeout']} {inner}"
        launch = (f"printf '%s\\n' \"$SP\" | sudo -S -p '' {inner}"
                  if sudo else inner)
        wrapper = (
            "#!/bin/bash\n"
            f"J={shlex.quote(job_dir)}\n"
            "echo $$ > \"$J/pid\"\n"
            "SP=''\n"
            "if [ -f \"$J/pass\" ]; then SP=$(<\"$J/pass\"); rm -f \"$J/pass\"; fi\n"
            f"WORKDIR={shlex.quote(workdir or '')}\n"
            "if ! cd \"${WORKDIR:-$HOME}\"; then\n"
            "  echo \"cannot cd to ${WORKDIR:-$HOME}\" > \"$J/err.log\"\n"
            "  echo 1 > \"$J/exit.tmp\" && mv \"$J/exit.tmp\" \"$J/exit\"\n"
            "  exit 1\n"
            "fi\n"
            "CMD=$(cat \"$J/cmd\")\n"
            f"{launch} >\"$J/out.log\" 2>\"$J/err.log\" </dev/null\n"
            "EC=$?\n"
            "echo $EC > \"$J/exit.tmp\" && mv \"$J/exit.tmp\" \"$J/exit\"\n"
        )
        conn._remote_put_bytes(f"{job_dir}/wrapper.sh",
                               wrapper.encode("utf-8"), mode=0o700)

        launched = conn.run(
            "setsid nohup bash " + shlex.quote(f"{job_dir}/wrapper.sh")
            + " >/dev/null 2>&1 </dev/null & ",
            timeout=15, internal=True)
        if launched["code"] != 0:
            raise RuntimeError(
                f"job launch failed: {launched['stderr'].strip()[:200]}")
        # Proof of life: the wrapper writes pid (started) or exit
        # (immediate failure, e.g. bad workdir). A constant echo could
        # not tell either from a silently missing bash.
        pid_q = shlex.quote(job_dir + "/pid")
        exit_q = shlex.quote(job_dir + "/exit")
        probe = conn.run(
            "i=0; "
            f"while [ $i -lt 30 ] && [ ! -s {pid_q} ] && [ ! -f {exit_q} ]; do "
            "i=$((i+1)); sleep 0.1 2>/dev/null || sleep 1; done; "
            f"if [ -s {pid_q} ]; then cat {pid_q}; "
            "elif [ -f " + exit_q + " ]; then echo \"EXITED$(cat " + exit_q + ")\"; fi",
            timeout=15, internal=True)["stdout"].strip()
        if not probe:
            raise RuntimeError(
                f"job {job_id} did not report a pid or exit marker")
        if probe.startswith("EXITED"):
            return {
                "stdout": f"Job {job_id} exited immediately "
                          f"(code {probe[6:]})\n",
                "stderr": "", "code": 0,
                "job_id": job_id, "pid": "",
            }
        return {
            "stdout": f"Started {job_id} (pid {probe})\n",
            "stderr": "", "code": 0,
            "job_id": job_id, "pid": probe,
        }

    def status(self, job_id: str, tail_lines: int = 100) -> dict:
        """Report one job's state plus the tail of its output logs."""
        self._conn.connect()
        meta = self._meta(job_id)
        job_dir_q = shlex.quote(self._job_dir(job_id))
        state = self._state(job_dir_q, job_id, meta["sudo"])
        tail = max(1, min(int(tail_lines or 100), 1000))
        streams = {}
        for key, fname in (("stdout", "out.log"), ("stderr", "err.log")):
            streams[key] = self._conn.run(
                f"tail -n {tail} -- {job_dir_q}/{fname} 2>/dev/null || true",
                timeout=15, sudo=meta["sudo"], internal=True)["stdout"]
        return {
            "job_id": job_id, "name": meta["name"],
            "state": state["state"], "exit_code": state["exit_code"],
            "pid": state["pid"], "started": meta["started"],
            "sudo": meta["sudo"], "command": meta.get("command", ""),
            "stdout": streams["stdout"], "stderr": streams["stderr"],
        }

    def kill(self, job_id: str) -> dict:
        """Terminate a running job (whole process group, TERM then KILL)."""
        self._conn.connect()
        meta = self._meta(job_id)
        job_dir_q = shlex.quote(self._job_dir(job_id))
        state = self._state(job_dir_q, job_id, meta["sudo"])
        if state["state"] != "running":
            return {
                "stdout": f"Job {job_id} is not running "
                          f"(state: {state['state']}"
                          + (f", exit code {state['exit_code']}"
                             if state["exit_code"] else "") + ")\n",
                "stderr": "", "code": 0, "job_id": job_id,
                "state": state["state"], "killed": False,
            }
        pid = state["pid"]
        # The marker is written as the pool user (the job dir is user-owned)
        # so a later status still reports 'killed' when the exit file never
        # got written because the wrapper itself was terminated.
        self._conn.run(f"touch {job_dir_q}/killed", timeout=10, internal=True)
        self._conn.run(
            f"kill -s TERM -- -{pid} 2>/dev/null; "
            f"i=0; while kill -0 {pid} 2>/dev/null && [ $i -lt 5 ]; do "
            "i=$((i+1)); sleep 1; done; "
            f"if kill -0 {pid} 2>/dev/null; then kill -s KILL -- -{pid} 2>/dev/null; fi",
            timeout=30, internal=True)
        state = self._state(job_dir_q, job_id, meta["sudo"])
        return {
            "stdout": f"Job {job_id} killed (state: {state['state']})\n",
            "stderr": "", "code": 0, "job_id": job_id,
            "state": state["state"], "killed": True,
        }

    def list(self, clean_days: int = 0, sudo: bool = False) -> dict:
        """List all jobs; optionally drop finished jobs whose exit marker
        is older than clean_days days (0 = keep everything)."""
        self._conn.connect()
        script = (
            f"ROOT={shlex.quote(self._conn.jobs_dir)}\n"
            "if [ ! -d \"$ROOT\" ]; then echo 'NOJOBS'; exit 0; fi\n"
            + (
                f"find \"$ROOT\" -mindepth 2 -maxdepth 2 -type f -name exit "
                f"-mtime +{int(clean_days)} 2>/dev/null | while read f; do "
                "j=${f%/exit}; case \"${j##*/}\" in job-*) rm -rf -- \"$j\";; esac; "
                "done\n" if clean_days else ""
            )
            + self._STATE_FN + "\n"
            "found=0\n"
            "for J in \"$ROOT\"/job-*; do\n"
            "  [ -d \"$J\" ] || continue\n"
            "  found=1; ID=${J##*/}\n"
            "  cmd=$(head -n 1 \"$J/cmd\" 2>/dev/null | cut -c 1-80)\n"
            "  echo \"$ID|$(job_state \"$J\" \"$ID\")|$cmd\"\n"
            "done\n"
            "[ $found -eq 0 ] && echo 'NOJOBS' || true\n"
        )
        out = self._conn.run(f"bash -c {shlex.quote(script)}", timeout=30,
                             sudo=sudo, internal=True)
        if out["code"] != 0:
            return out
        jobs = []
        for line in out["stdout"].splitlines():
            if line == "NOJOBS":
                continue
            parts = line.split("|", 4)  # id|state|code|pid|command (may hold |)
            if len(parts) < 5:
                continue
            jobs.append({"id": parts[0], "state": parts[1],
                         "exit_code": parts[2], "command": parts[4]})
        return {
            "stdout": out["stdout"], "stderr": out["stderr"],
            "code": 0, "jobs": jobs, "count": len(jobs),
        }


class JobsMixin:
    """job_* methods on SSHConnection, forwarded to a JobStore view."""

    def job_start(self, command, name=None, timeout=0, workdir=None, sudo=False):
        return JobStore(self).start(command, name, timeout, workdir, sudo)

    def job_status(self, job_id, tail_lines=100):
        return JobStore(self).status(job_id, tail_lines)

    def job_kill(self, job_id):
        return JobStore(self).kill(job_id)

    def job_list(self, clean_days=0, sudo=False):
        return JobStore(self).list(clean_days, sudo)
