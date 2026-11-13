# Agent installation

[中文](../zh-CN/docs/install.md) · [Home](../README.md)

## 1. Prepare a checkout and interpreter

Use Python 3.9 or later and a working SSH/SFTP server. Dependency versions may raise their own Python requirements; use a currently supported Python release when possible.

```bash
git clone https://github.com/leehom0123/ssh-ops.git
cd ssh-ops
python -m venv .venv
```

Use `.venv/bin/python` on POSIX, or `.venv/Scripts/python.exe` on Windows, to run `-m pip install -r requirements.txt`. Runtime dependencies are Paramiko, PyYAML and PySocks. Pytest is needed separately for development tests. Keep the selected interpreter's absolute path for MCP registration.

## 2. Choose the agent entry point

- **Codex plugin:** the manifest registers `skills/ssh-ops/` as a single entry point to the guides below and `.mcp.json` as a local stdio server. Before enabling it, ensure `python` on the client's PATH has the runtime dependencies installed; an activated virtual environment works when the client inherits its PATH. The MCP working directory resolves to the installed plugin root, not the user's project. Installation does not create an environment, install dependencies, or configure servers. For a fixed interpreter, use the manual MCP registration below instead and avoid registering the server twice. The root `SKILL.md` and language copies are references, not additional plugin skills. Choose either plugin installation or direct skill installation; using both can expose duplicate skills.
- **CLI skill:** put the checkout in a skill directory supported by your agent, or configure that directory in the agent. Load the root English [SKILL.md](../SKILL.md) by default. The `zh-CN/` tree contains same-named Chinese reference documents, not a separately installed skill. Keep the complete directory structure; do not copy the skill file alone. Skill directory conventions depend on the client/version; this project does not install a global `ssh-ops` command.
- **MCP:** keep the checkout wherever suitable, register [mcp_server.py](../mcp_server.py), and use the root English [SKILL.mcp.md](../SKILL.mcp.md) as the operating guide, consulting the [Chinese reference](../zh-CN/SKILL.mcp.md) when needed. The CLI skill, MCP skill, and language copies share a `name`; do not load them as multiple skills.

The MCP entry point contains registration commands for stdio and HTTP. For clients using the common `mcpServers` JSON format, the equivalent stdio entry is:

```json
{
  "mcpServers": {
    "ssh-ops": {
      "command": "/absolute/path/to/python",
      "args": ["/absolute/path/ssh-ops/mcp_server.py"]
    }
  }
}
```

This is a format example, not a configuration file shared by every agent. Use the client's own MCP settings location and schema; OpenCode, for example, has its own configuration format. Do not paste this blindly into an arbitrary `mcp.json` or settings file. The checkout need not be the client's working directory.

## 3. Configure servers

Check the installed `config.yaml` for `servers_dir`; do not assume it points at the checkout's `servers/`. Create server YAML using the [configuration reference](reference.md#configuration). Keep credentials outside version control and verify first-use host fingerprints through an independent channel.

## 4. Verify the installation

```bash
python cli.py --help
python cli.py list-servers
```

Use the interpreter installed above. An empty server list is valid; neither command contacts a remote server. Restart/reload the agent, then verify MCP `initialize` and `tools/list`: expect the 22 static tools documented in [SKILL.mcp.md](../SKILL.mcp.md), plus any discovered aliases. CLI-only installations do not register MCP tools.

After selecting a configured server, run a harmless command such as `whoami` to verify SSH. This contacts the server and may enroll a TOFU host key; obtain authorization first. For HTTP, complete the session initialization described in the [protocol reference](reference.md#http).

For development validation, install pytest and run `python -m pytest test/ -m 'not live' -q`. Live tests require explicit server configuration and authorization.
