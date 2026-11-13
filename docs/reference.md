# Runtime and configuration reference

[中文](../zh-CN/docs/reference.md) · [CLI syntax](cli.md) · [MCP tools](../SKILL.mcp.md)

This is the authority for configuration and runtime behaviour. Deployment-specific policy belongs in the [deployment chapter](deploy.md).

## Implementation map

Both [cli.py](../cli.py) and [mcp_server.py](../mcp_server.py) use the [ssh_client/](../ssh_client/) package:

- [config.py](../ssh_client/config.py): local paths, YAML, shell templates, encoding helpers.
- [connection.py](../ssh_client/connection.py): SSH lifecycle, host keys, command execution, aliases.
- [transfer.py](../ssh_client/transfer.py): SFTP, script wrappers, text I/O.
- [jobs.py](../ssh_client/jobs.py): `JobStore` and the remote marker-file protocol.
- [pool.py](../ssh_client/pool.py): process-local connection cache and server YAML CRUD.

<a id="configuration"></a>
## Configuration

### Global file

`config.yaml` and `known_hosts` live in the checkout root, regardless of the current working directory. The following is a field example, not a copy of your installed configuration:

```yaml
servers_dir: servers
proxy:
  enabled: false
  host: 127.0.0.1
  port: 1080
server:
  timeout: 30
  auto_reconnect: true
  reconnect_interval: 5
  keepalive_interval: 15
  host_key_checking: tofu
security:
  blacklist: []
  whitelist: []
  command_template: ""
```

- `servers_dir`: absolute path, or relative to `config.yaml`; omitted: `servers`. Windows drive paths are normalized for Linux/WSL; `/mnt/<drive>/...` is normalized on Windows.
- `proxy`: global SOCKS5 enable flag, host, and port. There is no separate effective `proxy.timeout`; sockets use the server timeout.
- `server`: defaults for the five connection-policy fields shown above.
- `security`: global command-filter/template defaults, described under [Security](#security).

Global defaults and the server directory are read at import time. Connection objects are cached. After editing files externally, restart a persistent MCP process for predictable reloads. The connection path re-reads global proxy configuration, but a proxy already resolved onto a cached connection can retain its earlier value; do not rely on live proxy toggling.

### Server YAML fields

Store one lowercase `<name>.yml` per server in `servers_dir`. Discovery scans only top-level `*.yml`, not subdirectories or `*.yaml`. Name-taking operations strip an optional `.yml`/`.yaml`, lowercase the name, require an initial ASCII letter/digit, and allow subsequent ASCII letters/digits, `.`, `_`, `-`.

The top-level keys are `server`, `aliases`, and optional `extends`. All connection and security settings below belong **inside `server`**.

```yaml
server:
  host: example.invalid
  user: deploy
  key: /absolute/path/to/private_key
  scripts_dir: /home/deploy/scripts
  scripts_local_dir: scripts
aliases:
  - name: health
    inline: "df -h /"
    desc: Check disk usage
  - name: deploy
    script: deploy.sh
    timeout: 300
    sudo: false
```

| Field in `server` | Default / meaning |
|---|---|
| `host` | Required hostname/IP after inheritance |
| `user` | Required SSH login user after inheritance |
| `port` | 22 |
| `password` | Optional login password |
| `key` | Optional private-key path on the machine running ssh-ops; takes precedence over password |
| `key_password` | Optional private-key passphrase |
| `sudo_password` | Falls back to `password` when absent or empty |
| `timeout` | Global `server.timeout`, otherwise 30 seconds; connection timeout and default command timeout |
| `auto_reconnect` | Global setting, otherwise true |
| `reconnect_interval` | Global setting, otherwise 5 seconds; clamped to at least 0 |
| `keepalive_interval` | Global setting, otherwise 15 seconds; 0 disables keepalive |
| `host_key_checking` | Global setting, otherwise `tofu`; also accepts `strict`, `insecure` |
| `shell` | `bash`; alternatives `cmd`, `powershell` |
| `scripts_dir` | `/home/<user>/scripts`; set explicitly for Windows or a different home layout |
| `scripts_local_dir` | Unset: server YAML directory; otherwise resolved relative to that directory |
| `jobs_dir` | `<scripts_dir>/.jobs` when absent or empty |
| `proxy` | Optional nonempty `{host: ..., port: ...}` overriding global proxy; `{}` falls back to global, not a per-server disable switch |
| `whitelist` | Global list if absent/null; an explicit `[]` disables that inherited whitelist |
| `blacklist` | Global list if absent/null; an explicit `[]` disables that inherited blacklist |
| `command_template` | Global template when absent or empty; `<command>` is the substitution token |
| `allowed_local_paths` | `[]`, unrestricted; local transfer paths |
| `allowed_remote_paths` | `[]`, unrestricted; remote transfer/text-I/O paths |
| `name` | Display name; listing falls back to the YAML filename stem |
| `desc` | Display description, default empty |
| `system` | Display OS information, default empty |
| `group` | Listing sort group; defaults to the server name |

Display fields do not change connection behaviour. Listings sort by group/name and include a one-based `index`; that index is not a server identifier.

### Inheritance and updates

```yaml
extends:
  - _shared/base.yml
  - _shared/commands.yml
server:
  host: example.invalid
aliases:
  - name: health
    inline: "df -h /"
```

`extends` must be a list of file paths relative to the server YAML directory. Loading is **one level only**, not recursive. Local `server` fields override inherited fields; earlier files win over later files for fields already inherited. `server` merging is shallow. Local aliases win by exact name; earlier inherited aliases also win over later duplicates. Missing files produce a warning and are skipped. Inherited script paths still resolve against the consuming server YAML, not the shared file.

Legacy top-level security/proxy/path keys are copied by the inheritance loader, but the connection constructor reads those settings from `server`. Put shared settings in the shared file's `server` mapping; top-level copies do not configure the connection.

CRUD updates differ from inheritance: mappings merge recursively, arrays/scalars replace as a whole, and `replace` replaces the entire object. Create/copy refuse overwrite; delete removes only local YAML. New configs request mode 0600; updates retain existing permission bits; copies retain source bytes/mode. Writes use a temporary file and atomic replacement. Permission enforcement depends on the local filesystem. CRUD discards the affected cached connection; MCP CRUD also invalidates alias-tool discovery.

## Aliases and shell selection

Each alias has `name`, optional `desc`, `timeout` (default 300 seconds), `sudo` (default false), and either `inline` or `script`. If both exist, execution chooses `inline`; do not define both. `list-aliases` only reads local configuration.

- `inline` is sent to the remote shell after command filtering/template application.
- `script` identifies a local script, not an already-uploaded remote file. A simple relative filename such as `deploy.sh` is the reliable on-demand alias form. The local file must still exist even if the remote copy exists. If the remote copy exists, alias execution skips upload; it does not compare content or refresh it.
- On-demand script aliases reject absolute paths, backslashes, empty segments, `.` and `..`. They compute a relative remote path, but a missing nested script is currently uploaded by basename. For nested scripts, pre-upload to the exact relative remote name or use an explicit upload/run operation.
- Bulk alias upload has separate path handling: relative paths preserve their location below `scripts_local_dir`; files resolving outside it go to `<scripts_dir>/external/<basename>`. This does not make absolute paths valid for on-demand `alias` execution.

`shell` selects generated helper syntax and argument quoting; it does not switch the SSH account's login shell or translate user commands. Bash script execution uses `bash`, cmd uses `call`, and PowerShell uses `&`. Set up the remote SSH shell accordingly. Sudo requires remote `sudo` and `bash`; it is not Windows elevation. The deployment templates are bash-oriented.

<a id="security"></a>
## Security and connection policy

### Filters and paths

For non-internal `run` calls, filtering occurs in this order: blacklist `re.search`, nonempty whitelist `re.fullmatch`, then replacement of `<command>` in `command_template`. A broad pattern such as `ls.*` still permits shell operators; neither regex list is a sandbox. Restrict credentials and OS permissions independently.

The same checks apply to inline aliases and job command payloads. Generated helper commands bypass filters **and the command template** via `internal=True`. `run-script` also takes that internal path: do not treat a whitelist as a restriction on uploaded script contents. Script aliases and upload-and-run execute their generated invocation through ordinary `run`, so their invocation is filtered, not the script body.

Path allow-lists use directory-boundary comparison, not arbitrary string prefixes. Local paths resolve on the client; remote paths use lexical POSIX normalization. Remote case folding follows the client's OS, and no remote symlink resolution is performed. They are not a filesystem sandbox and do not restrict arbitrary `run` commands or job directories. Download checks include the local root and individual remote files; sudo recursive downloads check staged paths, which can conflict with an allow-list for the original directory. Avoid combining restricted recursive downloads with sudo unless verified for your configuration.

Generated helper arguments are quoted for the chosen shell. Script-name validation rejects traversal/absolute names; this validation is not applied to every arbitrary remote path. Protect YAML credentials with local permissions and keep them out of version control. MCP error argument summaries redact values under known secret keys; exception messages and tool output are not scrubbed. Secrets embedded inside command/content strings are not redacted.

### Host keys

| Mode | Current behaviour |
|---|---|
| `tofu` | Pre-authentication probe checks checkout-local `known_hosts`; unknown key types are recorded; a changed stored key of the same type is rejected |
| `strict` | Pre-authentication probe requires a matching key in checkout-local `known_hosts`; system known_hosts alone is not sufficient |
| `insecure` | Skips the probe and uses permissive missing-key handling; existing loaded key mismatches can still be rejected by Paramiko on the direct path |

The direct SSH client also loads system host keys and the checkout-local file. Nondefault ports use `[host]:port`. Verify fingerprints out of band before trusting a first connection. For a legitimate rotation, verify the replacement before changing the local entry; do not blindly delete it. A warning is printed if TOFU persistence fails, so successful connection does not guarantee durable enrollment.

The probe uses a separate connection, and the proxy path verifies independently as well: its transport negotiates first, the authenticating transport's own key is checked against the stored entries with the same rules as the probe, and credentials are sent only after that check passes. Thus `tofu`/`strict` bind verification to the authenticated proxy connection, not only to the probe. Direct SSH additionally verifies its authentication connection through Paramiko's loaded host-key policy.

### Proxy, reconnect, and concurrency

A nonempty per-server SOCKS5 proxy takes precedence over the enabled global proxy. When the proxy-authentication connection attempt fails, the code logs `proxy_error.log` and tries direct SSH. **The host-key probe occurs before this fallback block**: a failed proxied probe aborts the cycle rather than falling back. Proxy authentication fields and a separate proxy timeout are not implemented.

Failed connection cycles can start a daemon reconnect thread. While consecutive failures are fewer than five it waits `reconnect_interval`; from the fifth failure it waits 60 seconds. Explicit requests attempt immediately even during cooldown. `auto_reconnect: false` disables background retries and the automatic retry after a failed channel open. Threads end with the process; a short-lived CLI is not a persistent reconnect service.

The pool caches one connection per normalized server name per process. Established connections support independent command channels; connection establishment is serialized per connection, so reconnects can make other requests to that server wait. Stdio MCP uses eight request workers. HTTP uses a threaded server.

### Timeouts and sudo

CLI option defaults are defined in the [CLI reference](cli.md); MCP argument defaults in [SKILL.mcp.md](../SKILL.mcp.md). For MCP passthrough tools with a positive `timeout` `t`, the forwarded value is:

```text
max(1, t - min(5, t * 0.1))
```

For example, 300 becomes 295 and 30 becomes 27. This reserves response time; it is not a measured client deadline or an overall request-duration guarantee. `None`/0 pass through; command execution then uses the server timeout. SFTP timeout is applied to the channel, not a whole-transfer deadline; 0 is not normalized to the server timeout by the SFTP helper. Multi-step uploads/downloads have additional fixed helper timeouts. Alias timeouts, job lifetime, and read/write operations do not use this MCP adjustment.

Ordinary command timeout closes its channel and returns code `-1`; the remote process may continue. Sudo commands use `sudo -S -p '' bash -c ...`, feeding the configured password through channel stdin rather than argv. Background sudo jobs use a different temporary password-file protocol below.

<a id="transfers"></a>
## Transfer and text semantics

### Files, scripts, overwrite, and deduplication

- Upload accepts one local file, not a recursive directory. Script upload targets `<scripts_dir>/<script_name>`, requests executable mode, and can run immediately. Script names may be safe relative subpaths.
- Download handles files and directories. `download-file` delegates to it and does not independently reject a directory. Recursive downloads preserve the tree, regex-search individual filenames, and stop recursion when depth exceeds 48 (root depth 0). Rejected files/depth errors produce an aggregate nonzero result.
- Overwrite defaults to true. With overwrite disabled, upload checks remote file existence; download refuses an existing local destination, including an existing directory root. These checks are not atomic create-only guarantees. Bulk upload reports existing-file errors as failures rather than successful skips.
- Bulk alias upload deduplicates local content by MD5 within that invocation. Later identical files are reported as failures; this is neither remote synchronization nor a security hash check.
- Non-sudo upload optionally applies 0755 for executable files on bash servers; otherwise SFTP/server creation rules apply. Sudo bash upload stages in `/tmp`, then moves into place: overwrites restore the target's owner/mode; new files inherit the parent's owner/group and receive 0755. `executable=false` does not override that sudo new-file mode.
- Sudo download copies to a unique `/tmp` staging path, changes staging ownership to the login user, downloads it, and attempts cleanup. It does not chmod/chown the source.

Bash staging names contain random suffixes but are not exclusively reserved; private staging permissions are not guaranteed. Successful sudo upload installation moves the staged file into place, but failed uploads/installs can leave it behind. Download/read paths attempt removal; staging failures before cleanup is entered can also leave files behind.

### Text reads and writes

Reads use byte offsets, default to 65536 bytes, and cap positive requested size at **1 MiB (1048576 bytes)**. `max_bytes=0` uses the default. Results contain `size`, `offset`, `next_offset`, `eof`, and text stdout; MCP presents paging fields in its text summary, while CLI shows continuation on stderr. Explicit MCP null offset/size use the defaults.

NUL bytes are rejected. At EOF, invalid UTF-8 is rejected; a partial page decodes with invalid sequences ignored. **Current limitation:** `next_offset` advances by raw bytes read, including a discarded partial UTF-8 character. Paging can therefore lose characters across a multibyte boundary. For exact text preservation, download the file rather than concatenate pages; binary data also belongs in downloads.

Writes encode content as UTF-8. Non-sudo overwrite preserves existing owner/mode; a new file requests 0644 where chmod is supported. Append uses SFTP append mode. Sudo write uses a **local temporary file** and the sudo upload/install path above; sudo append first reads the entire prior text and rewrites it, so it is not atomic and is unsuitable for concurrently written logs. There is no corresponding 1 MiB write cap. Use file transfer for large content. The MCP `content` argument is required and rejects an empty string; CLI stdin can be empty.

<a id="jobs"></a>
## Background job protocol

Bash servers require `setsid`, `nohup`, and the helper commands used by the wrapper; a nonzero job lifetime additionally requires `timeout`. A job ID has the form `job-YYYYMMDD-HHMMSS-<six hex characters>`.

`JobStore.start` filters the user command, writes `cmd` and JSON `meta`, writes `wrapper.sh` with requested mode 0700, then launches under `setsid nohup bash`. It probes for a PID or exit marker before returning; “start” acknowledges wrapper startup, not successful completion. State lives in `<jobs_dir>/<id>/`, independently of the MCP process.

| File / state | Meaning |
|---|---|
| `cmd`, `meta`, `wrapper.sh` | Command, label/start time/privilege/workdir/lifetime metadata, wrapper |
| `pid`, `out.log`, `err.log` | Wrapper PID and output streams |
| `exit` | Atomically renamed from `exit.tmp`; takes priority and yields `exited` with exit code |
| `killed` | Termination marker; yields `killed` when no exit marker/live PID branch applies |
| `running` | PID is live and its command line contains the job ID |
| `lost` | No recognized completion or matching live wrapper |

Status reads metadata, resolves state, and tails each log: default 100 lines, bounded to 1–1000 (0 selects default). A nonzero job timeout bounds the command's lifetime; 0 is unlimited. Remote state survives client disconnects/restarts but not deletion of job directories or necessarily a server reboot.

Kill checks state, writes `killed`, signals the wrapper process group with TERM, waits up to five one-second intervals, then escalates to KILL if the PID remains live. Signals run as the login user even for sudo jobs; root-owned descendants are not guaranteed to be terminated. Inspect resulting state and remote processes when elevated work matters.

`clean_days > 0` uses `find ... -name exit -mtime +N` and removes the containing job directories. This follows `find`'s rounded-day semantics and cleans only jobs with an exit marker, not all `killed`/`lost` jobs. Cleanup is destructive even though `ssh_job_list` currently has a read-only tool annotation. List output includes ID, state, exit code and a command preview, not the human label.

Sudo start writes `pass` over SFTP with a requested 0600 mode for a newly created file; existing files retain their mode. The wrapper reads it and attempts deletion before running the command. Mode application happens after writing, chmod errors are tolerated by the shared writer, and a failed launch can leave the file behind. Do not treat this as a guarantee that the secret is never temporarily readable; use restrictive remote directory permissions/umask. The password travels through `printf '%s\n' "$SP" | sudo -S`; the command inherits the closing end of that pipe as stdin, so it sees EOF after the password line instead of blocking. Status uses stored sudo metadata for state/log reads. Logs are opened by the login-user wrapper, so they are not inherently root-owned.

<a id="http"></a>
## MCP HTTP semantics

Launch flags and registration are listed in [SKILL.mcp.md](../SKILL.mcp.md). This implementation supports JSON POST responses, not server-initiated SSE or resumable event streams.

- Default endpoint: `http://127.0.0.1:8802/mcp`. `--path` is matched literally against the URL path (query ignored); supply a leading slash.
- Send one `initialize` request with an ID first. A successful single-request response returns `Mcp-Session-Id`; send that header on subsequent POSTs, including notifications. Initialization inside a batch does not get the same session-header creation path; use standalone initialization.
- Sessions are in memory with no expiry mechanism; restart loses them. Missing/unknown session yields HTTP 404. DELETE on the endpoint with the session header drops it: 200 if found, otherwise 404. It does not cancel SSH commands or jobs.
- POST requests with a response return HTTP 200 JSON, including JSON-RPC/tool errors. Notifications with no response return empty 202. Invalid JSON returns 400; unknown path returns 404. GET returns 405; there is no SSE stream.
- `Mcp-Protocol-Version`, if supplied, must be one of `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`; unsupported values return 400. Initialization negotiates supported versions, otherwise selects the newest.
- With `--token`, POST and DELETE require an exact `Authorization: Bearer <token>` header; failure returns 401. Non-loopback bind addresses require a nonempty token; only `127.0.0.1`, `localhost`, `::1` are classified as loopback by the launch check. The check does not guarantee IPv6 binding support.
- HTTP is plaintext: use a trusted local network or an HTTPS reverse proxy. Token authorization grants access to the service's tools, not per-server permissions. No per-user authorization, Origin validation, TLS, or automatic token management is implemented. The token is a launch argument and can be visible in local process listings.

Stdio uses one JSON-RPC message per line and may complete concurrent requests out of order. MCP returns text content blocks, not a universal structured JSON result schema; some tools put serialized JSON inside their text. Operation failures use `isError`; invalid arguments/unknown tools use JSON-RPC errors. Tool annotations are hints, not enforced access controls.
