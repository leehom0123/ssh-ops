# CLI reference

[中文](../zh-CN/docs/cli.md) · [CLI skill](../SKILL.md) · [Runtime semantics](reference.md)

Run commands from the checkout, or replace `cli.py` with its absolute path. `python cli.py`, `-h`, and `--help` show help. The CLI uses a custom trailing-option parser, not argparse.

## Parsing and options

```text
python cli.py <global-command> ...
python cli.py <server> <command> <positional-arguments> [options]
```

Put options after all positional arguments. Only the contiguous trailing block of recognized options is consumed. Quote the remote command as one argument; local shells still process quotes, `$`, pipes, and redirections. For complex commands use `run -` with a quoted heredoc. `-` must be the only command argument and stdin must not be blank.

| Option | Meaning and applicable commands |
|---|---|
| `-s`, `--sudo` | Sudo for `run`, `run-script`, `upload`, `upload-file`, `download`, `download-file`, `download-script`, `read-file`, `write-file`, `job-start`, `job-list`, `upload-all`, `list-scripts` |
| `-t`, `--timeout SECS` | Integer seconds for `run`, `run-script`, `upload`, `upload-file`, `download`, `download-file`, `download-script`; omitted: server timeout. For `job-start`: job lifetime, omitted/0: unlimited |
| `-n`, `--name VALUE` | Remote script name for `upload`; label for `job-start`; log line count per stream for `job-status` (default 100) |
| `-r`, `--run` | `upload`: execute after upload |
| `-p`, `--pattern REGEX` | `download`: filter filenames |
| `-x`, `--executable` | `upload-file`: request execute permission on Unix |
| `-o`, `--offset BYTES` | `read-file`: byte offset, default 0 |
| `-l`, `--length BYTES` | `read-file`: maximum bytes, default 65536; 0 selects the default |
| `-a`, `--append` | `write-file`: append instead of overwrite |
| `-w`, `--workdir DIR` | `job-start`: working directory, default remote home |
| `--clean-days N` | `job-list`: cleanup threshold, default 0 (keep everything) |
| `--no-overwrite` | `upload-file`, `download`, `download-file`, `download-script`: fail if destination exists |
| `--replace` | `update-server`: replace the whole YAML object |

Recognition is not applicability: the parser consumes these flags even for commands that do not use them. In particular, `alias` ignores CLI sudo/timeout and uses its YAML settings; `upload-all` and `list-scripts` ignore CLI timeout. Read/write and job control use internal operation timeouts. There is no `--overwrite`, `--tail-lines`, or `--max-bytes` CLI option.

## Local configuration commands

| Command | Behaviour |
|---|---|
| `python cli.py list-servers` | JSON object with `count` and `servers`; no SSH |
| `python cli.py create-server <name> <config.yml>` | Create from a YAML file; existing destination is an error |
| `python cli.py update-server <name> <patch.yml> [--replace]` | Recursively merge mappings; replace arrays/scalars, or replace the whole object |
| `python cli.py copy-server <source> <new-name>` | Copy YAML bytes and permission bits; existing destination is an error |
| `python cli.py delete-server <name>` | Delete the local YAML, not anything on the remote server |

Mutation commands print JSON results. Name validation, storage, inheritance, and cache invalidation are defined in the [configuration reference](reference.md#configuration).

## Execution and scripts

All commands below start with `python cli.py <server>`.

| Command suffix | Behaviour |
|---|---|
| `run <command> [-s] [-t SECS]` | Execute remote command; stream stdout/stderr |
| `run - [-s] [-t SECS]` | Read the complete command from stdin; stream stdout/stderr |
| `run-script <name> [-s] [-t SECS]` | Execute from `scripts_dir`; stream stdout/stderr |
| `alias <name>` | Execute a configured alias; stream stdout/stderr |
| `upload <local> [-n NAME] [-r] [-s] [-t SECS]` | Upload into `scripts_dir`; default name is local basename; always allows overwrite |
| `upload-all [-s]` | Upload alias scripts; print aggregate successes/failures |
| `list-scripts [-s]` | List remote scripts; internal timeout 30 seconds |
| `list-aliases` | JSON object with `count` and `aliases`; no SSH |

```bash
python cli.py my-server run - -t 30 <<'EOF'
printf '%s\n' "$HOME"
EOF
```

## Files and text

| Command suffix | Behaviour |
|---|---|
| `upload-file <local> <remote> [-s] [-x] [-t SECS] [--no-overwrite]` | Upload one file to an explicit path |
| `download <remote> <local> [-s] [-p REGEX] [-t SECS] [--no-overwrite]` | Download a file or directory |
| `download-file <remote> <local> [-s] [-t SECS] [--no-overwrite]` | Explicit-path download; delegates to the same downloader |
| `download-script <name> <local> [-s] [-t SECS] [--no-overwrite]` | Download from `scripts_dir` |
| `read-file <remote> [-o BYTES] [-l BYTES] [-s]` | Text on stdout; if partial, stderr includes the next byte offset |
| `write-file <remote> [-a] [-s]` | Read UTF-8 text from stdin, then print the operation result |

Transfers overwrite by default. Read limits, UTF-8 boundary caveats, file modes, sudo staging, and deduplication are specified only in the [runtime reference](reference.md#transfers).

```bash
python cli.py my-server read-file /var/log/app.log -o 0 -l 4096
python cli.py my-server write-file /etc/motd -s < note.txt
```

## Background jobs

| Command suffix | Output / behaviour |
|---|---|
| `job-start <command> [-n NAME] [-w DIR] [-t SECS] [-s]` | JSON `job_id`, `pid`; `-` instead of command reads stdin |
| `job-status <id> [-n LINES]` | JSON state, exit code, metadata, stdout/stderr tails |
| `job-kill <id>` | JSON termination result; uses the stored job metadata |
| `job-list [--clean-days N] [-s]` | JSON `count`, `jobs`; cleanup deletes remote task directories |

These commands require a bash server. See [job protocol and limitations](reference.md#jobs).

## Output, errors, and local paths

- Execution and transfer commands normally return their operation's exit code. Known operational errors print `Error: ...` to stderr and exit 1; malformed timeout values and invalid stdin command payloads exit 2.
- Listing, text reads, and successful job handler returns do not propagate a remote command exit code as the CLI exit code. Inspect job JSON and health-check output, not just the local exit status.
- Local upload/download/config-file paths use the project's Windows/WSL normalization. Under Git Bash on Windows, the CLI attempts to undo MSYS path rewriting using `cygpath`; if a real Windows target path starts with the Git or temp prefix, use PowerShell/cmd to avoid ambiguity.
- For deployment, use the [deployment chapter](deploy.md), not an ad hoc sequence copied from this reference.
