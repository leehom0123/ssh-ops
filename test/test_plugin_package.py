"""Exercise the bundled plugin entry points without contacting SSH servers."""
import json
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_declared_plugin_skill_links_resolve():
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    skills = list((ROOT / manifest["skills"]).glob("*/SKILL.md"))
    assert len(skills) == 1
    for link in re.findall(r"\]\(([^)]+)\)", skills[0].read_text(encoding="utf-8")):
        target = (skills[0].parent / link).resolve()
        assert target.is_relative_to(ROOT) and target.is_file()


def test_bundled_mcp_starts_from_installed_root(tmp_path):
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    config = json.loads((ROOT / manifest["mcpServers"]).read_text(encoding="utf-8"))
    shutil.copyfile(ROOT / "mcp_server.py", tmp_path / "mcp_server.py")
    shutil.copytree(ROOT / "ssh_client", tmp_path / "ssh_client",
                    ignore=shutil.ignore_patterns("__pycache__"))
    server = config["mcpServers"]["ssh-ops"]
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "package-test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    result = subprocess.run([server["command"], *server["args"]],
                            cwd=tmp_path / server["cwd"],
                            input="".join(json.dumps(r) + "\n" for r in requests),
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    responses = {r["id"]: r for line in result.stdout.splitlines()
                 if "id" in (r := json.loads(line))}
    assert responses[1]["result"]["serverInfo"]["name"] == "ssh-ops"
    tools = responses[2]["result"]["tools"]
    assert len(tools) == 22 and any(t["name"] == "ssh_run" for t in tools)
