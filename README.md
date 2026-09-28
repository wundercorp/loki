# Loki Agent 𖤍
<p align="center">
  <a href="https://www.npmjs.com/package/@wundercorp/loki"><img src="https://img.shields.io/npm/v/%40wundercorp%2Floki?style=for-the-badge&logo=npm&label=npm" alt="npm version"></a>
  <a href="https://www.npmjs.com/package/@wundercorp/loki"><img src="https://img.shields.io/npm/dw/%40wundercorp%2Floki?style=for-the-badge&logo=npm&label=weekly%20downloads" alt="npm weekly downloads"></a>
  <a href="https://www.npmjs.com/package/@wundercorp/loki"><img src="https://img.shields.io/npm/dt/%40wundercorp%2Floki?style=for-the-badge&logo=npm&label=total%20downloads" alt="npm total downloads"></a>
</p>
<p align="center">
  <a href="https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243"><img src="https://img.shields.io/badge/Docs-doku.sh-16A34A?style=for-the-badge" alt="Documentation"></a>
  <a href="https://discord.gg/yEaT8dv5Xn"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/wundercorp/loki/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://wundercorp.co"><img src="https://img.shields.io/badge/Built%20by-WunderCorp%2C%20Inc.-16A34A?style=for-the-badge" alt="Built by WunderCorp, Inc."></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Lang-中文-red?style=for-the-badge" alt="中文"></a>
  <a href="README.ur-pk.md"><img src="https://img.shields.io/badge/Lang-اردو-green?style=for-the-badge" alt="اردو"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/Lang-Español-orange?style=for-the-badge" alt="Español"></a>
</p>

**The self-improving AI agent built by [WunderCorp, Inc.](https://wundercorp.co).** It's the only agent with a built-in learning loop — it creates skills from experience, improves them during use, nudges itself to persist knowledge, searches its own past conversations, and builds a deepening model of who you are across sessions. Run it on a $5 VPS, a GPU cluster, or serverless infrastructure that costs nearly nothing when idle. It's not tied to your laptop — talk to it from Telegram while it works on a cloud VM.

Use any model you want — OpenRouter, OpenAI, your own endpoint, and [many others](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243). Switch with `loki model` — no code changes, no lock-in.

<table>
<tr><td><b>A real terminal interface</b></td><td>Full TUI with multiline editing, slash-command autocomplete, conversation history, interrupt-and-redirect, and streaming tool output.</td></tr>
<tr><td><b>Lives where you do</b></td><td>Telegram, Discord, Slack, WhatsApp, Signal, and CLI — all from a single gateway process. Voice memo transcription, cross-platform conversation continuity.</td></tr>
<tr><td><b>A closed learning loop</b></td><td>Agent-curated memory with periodic nudges. Autonomous skill creation after complex tasks. Skills self-improve during use. FTS5 session search with LLM summarization for cross-session recall. <a href="https://github.com/plastic-labs/honcho">Honcho</a> dialectic user modeling. Compatible with the <a href="https://agentskills.io">agentskills.io</a> open standard.</td></tr>
<tr><td><b>Scheduled automations</b></td><td>Built-in cron scheduler with delivery to any platform. Daily reports, nightly backups, weekly audits — all in natural language, running unattended.</td></tr>
<tr><td><b>Delegates and parallelizes</b></td><td>Spawn isolated subagents for parallel workstreams. Write Python scripts that call tools via RPC, collapsing multi-step pipelines into zero-context-cost turns.</td></tr>
<tr><td><b>Runs anywhere, not just your laptop</b></td><td>Seven terminal backends — local, Docker, SSH, Singularity, Modal, Daytona, and Vercel Sandbox. Daytona and Modal offer serverless persistence — your agent's environment hibernates when idle and wakes on demand, costing nearly nothing between sessions. Run it on a $5 VPS or a GPU cluster.</td></tr>
<tr><td><b>Research-ready</b></td><td>Batch trajectory generation, trajectory compression for training the next generation of tool-calling models.</td></tr>
</table>

---

## ⚡ Quick Install

### Linux, macOS, WSL2, Termux

```bash
curl -fsSL https://loki.computer/install.sh | bash
```

### Windows (native, PowerShell)

> **Heads up:** Native Windows runs Loki without WSL — CLI, gateway, TUI, and tools all work natively. If you'd rather use WSL2, the Linux/macOS one-liner above works there too. Found a bug? Please [file issues](https://github.com/wundercorp/loki/issues).

Run this in PowerShell:

```powershell
iex (irm https://loki.computer/install.ps1)
```

The installer handles everything: uv, Python 3.11, Node.js, ripgrep, ffmpeg, **and a portable Git Bash** (MinGit, unpacked to `%LOCALAPPDATA%\loki\git` — no admin required, completely isolated from any system Git install). Loki uses this bundled Git Bash to run shell commands.

If you already have Git installed, the installer detects it and uses that instead. Otherwise a ~45MB MinGit download is all you need — it won't touch or interfere with any system Git.

> **Android / Termux:** The tested manual path is documented in the [Termux guide](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243). On Termux, Loki installs a curated `.[termux]` extra because the full `.[all]` extra currently pulls Android-incompatible voice dependencies.
>
> **Windows:** Native Windows is fully supported — the PowerShell one-liner above installs everything. If you'd rather use WSL2, the Linux command works there too. Native Windows install lives under `%LOCALAPPDATA%\loki`; WSL2 installs under `~/.loki` as on Linux.

After installation, the installer reloads your shell configuration and starts `loki` automatically. The first-run quick setup uses OpenRouter by default; press `o` at the API-key prompt to open [openrouter.ai/keys](https://openrouter.ai/keys), then paste the key and choose your model.

Want Jev alongside your chat model? Choose **Quick Setup + TypeSafe Jev** in the CLI, or select **TypeSafe Jev (companion)** during Loki Desktop onboarding, then paste your `TYPESAFE_API_KEY` from [TypeSafe](https://console.typesafe.ai). You can also run `loki setup jev` later or manage the key under **Settings → Keys → Tools**. Existing CLI users can run `/jev status`, `/jev enable`, `/jev disable`, or `/jev setup` directly in a session. **Loki Autorouter — powered by Jev** is an optional model router that classifies the first task of a new session and selects a sufficiently capable lower-cost model from the *currently selected gateway only*; the route then stays sticky for that session to preserve prompt caching.

### Troubleshooting

#### Windows Defender or antivirus flags `uv.exe` as malware

If your antivirus (Bitdefender, Windows Defender, etc.) quarantines `uv.exe` from the Loki `bin` folder (`%LOCALAPPDATA%\loki\bin\uv.exe`), this is a **false positive**. The file is Astral's `uv` — the Rust Python package manager Loki bundles to manage its Python environment. ML-based antivirus engines commonly flag unsigned Rust binaries that download and install packages.

**To verify your copy is authentic:**

```powershell
# Install GitHub CLI if needed
winget install --id GitHub.cli

# Login to GitHub
gh auth login

# Run verification
$uv = "$env:LOCALAPPDATA\loki\bin\uv.exe"
$ver = (& $uv --version).Split(' ')[1]
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$zip = "$env:TEMP\uv.zip"
Invoke-WebRequest "https://github.com/astral-sh/uv/releases/download/$ver/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
gh attestation verify $zip --repo astral-sh/uv
Expand-Archive $zip "$env:TEMP\uv_x" -Force
(Get-FileHash "$env:TEMP\uv_x\uv.exe").Hash -eq (Get-FileHash $uv).Hash
```

If attestation says "Verification succeeded" and the last line prints `True`, you're good.

**To whitelist Loki:**
- **Windows Defender:** Run PowerShell as Admin → `Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\loki\bin"`
- **Bitdefender:** Add an exception in the Bitdefender console (Protection > Antivirus > Settings > Manage Exceptions)
- Whitelist the **folder**, not the file hash — Loki updates `uv` and the hash changes every version

For more context, see the upstream Astral reports: [astral-sh/uv#13553](https://github.com/astral-sh/uv/issues/13553), [astral-sh/uv#15011](https://github.com/astral-sh/uv/issues/15011), [astral-sh/uv#10079](https://github.com/astral-sh/uv/issues/10079).

---

## 🧰 Getting Started

```bash
loki              # Interactive CLI — start a conversation
loki model        # Choose your LLM provider and model
loki tools        # Configure which tools are enabled
loki config set   # Set individual config values
loki config get   # Print individual config values
loki gateway      # Start the messaging gateway (Telegram, Discord, etc.)
loki setup        # Run the full setup wizard (configures everything at once)
loki claw migrate # Migrate from OpenClaw (if coming from OpenClaw)
loki update       # Update to the latest version
loki doctor       # Diagnose any issues
```

📖 **[Full documentation →](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)**

---

## 💬 CLI vs Messaging Quick Reference

Run `loki` for the terminal UI, or start the gateway and talk to Loki Agent from Telegram, Discord, Slack, WhatsApp, Signal, or Email. Once you're in a conversation, many slash commands are shared across both interfaces.

| Action                         | CLI                                           | Messaging platforms                                                              |
| ------------------------------ | --------------------------------------------- | -------------------------------------------------------------------------------- |
| Start chatting                 | `loki`                                      | Run `loki gateway setup` + `loki gateway start`, then send the bot a message |
| Start fresh conversation       | `/new` or `/reset`                            | `/new` or `/reset`                                                               |
| Change model                   | `/model [provider:model]`                     | `/model [provider:model]`                                                        |
| Set a personality              | `/personality [name]`                         | `/personality [name]`                                                            |
| Open CLI settings              | `/settings`                                   | —                                                                                |
| Manage tools                   | `/settings tools` or `/tools list`            | —                                                                                |
| Advertisement preference       | `/ads on`, `/ads off`, `/ads status`          | —                                                                                |
| Retry or undo the last turn    | `/retry`, `/undo`                             | `/retry`, `/undo`                                                                |
| Compress context / check usage | `/compress`, `/usage`, `/insights [--days N]` | `/compress`, `/usage`, `/insights [days]`                                        |
| Browse skills                  | `/skills` or `/<skill-name>`                  | `/<skill-name>`                                                                  |
| Interrupt current work         | `Ctrl+C` or send a new message                | `/stop` or send a new message                                                    |
| Platform-specific status       | `/platforms`                                  | `/status`, `/sethome`                                                            |

For the full command lists, see the [CLI guide](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243) and the [Messaging Gateway guide](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243).

---

## 📚 Documentation

All documentation lives at **[doku.sh](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)**:

| Section                                                                                             | What's Covered                                             |
| --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| [Quickstart](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)                 | Install → setup → first conversation in 2 minutes          |
| [CLI Usage](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)                              | Commands, keybindings, personalities, sessions             |
| [Configuration](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)                | Config file, providers, models, all options                |
| [Messaging Gateway](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)                | Telegram, Discord, Slack, WhatsApp, Signal, Home Assistant |
| [Security](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)                          | Command approval, DM pairing, container isolation          |
| [Tools & Toolsets](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)            | 40+ tools, toolset system, terminal backends               |
| [Skills System](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)              | Procedural memory, Skills Hub, creating skills             |
| [Memory](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)                     | Persistent memory, user profiles, best practices           |
| [MCP Integration](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)               | Connect any MCP server for extended capabilities           |

### MCP from Loki

Inside the Loki terminal UI, use `/mcp` to inspect and manage MCP connections without leaving the conversation. `/mcp supercharger` securely configures the Supercharger MCP server and reloads its tools into the current session. The same setup is available before launch with `loki mcp supercharger`.

```text
/mcp list
/mcp supercharger
/mcp test supercharger
/mcp reload
```
| [Cron Scheduling](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)              | Scheduled tasks with platform delivery                     |
| [Context Files](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)       | Project context that shapes every conversation             |
| [Architecture](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)             | Project structure, agent loop, key classes                 |
| [Contributing](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)             | Development setup, PR process, code style                  |
| [CLI Reference](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243)                  | All commands and flags                                     |
| [Environment Variables](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243) | Complete env var reference                                 |

---

## 🔄 Migrating from OpenClaw

If you're coming from OpenClaw, Loki can automatically import your settings, memories, skills, and API keys.

**During first-time setup:** The setup wizard (`loki setup`) automatically detects `~/.openclaw` and offers to migrate before configuration begins.

**Anytime after install:**

```bash
loki claw migrate              # Interactive migration (full preset)
loki claw migrate --dry-run    # Preview what would be migrated
loki claw migrate --preset user-data   # Migrate without secrets
loki claw migrate --overwrite  # Overwrite existing conflicts
```

What gets imported:

- **SOUL.md** — persona file
- **Memories** — MEMORY.md and USER.md entries
- **Skills** — user-created skills → `~/.loki/skills/openclaw-imports/`
- **Command allowlist** — approval patterns
- **Messaging settings** — platform configs, allowed users, working directory
- **API keys** — allowlisted secrets (Telegram, OpenRouter, OpenAI, Anthropic, ElevenLabs)
- **TTS assets** — workspace audio files
- **Workspace instructions** — AGENTS.md (with `--workspace-target`)

See `loki claw migrate --help` for all options, or use the `openclaw-migration` skill for an interactive agent-guided migration with dry-run previews.

---

## 🛠️ Contributing

We welcome contributions! See the [Contributing Guide](https://doku.sh/#/i/cbe1e051e4be2bb725-26f1d908878243) for development setup, code style, and PR process.

Quick start for contributors — use the standard installer, then work from the
full git checkout it creates at `$LOKI_HOME/loki-agent` (usually
`~/.loki/loki-agent`). This matches the layout used by `loki update`, the
managed venv, lazy dependencies, gateway, and docs tooling.

```bash
curl -fsSL https://loki.computer/install.sh | bash
cd "${LOKI_HOME:-$HOME/.loki}/loki-agent"
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

Manual clone fallback (for throwaway clones/CI where you intentionally do not
want the managed install layout):

Create the venv outside the cloned source tree — a venv inside the directory
the agent operates from can be wiped by a relative-path command the agent runs
against its own checkout, destroying the running runtime mid-session.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv ~/.loki/venvs/loki-dev --python 3.11
source ~/.loki/venvs/loki-dev/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

---

## 🧩 Tools & Ecosystem

Loki can be paired with purpose-built tools for desktop control, browser automation, isolated execution, and mobile access. These integrations live here instead of under Community so project resources and community links stay clearly separated.

### ⚡ Structured decisions

- **[TypeSafe Jev](https://docs.typesafe.ai/introduction)** — optional System One decision engine for typed Choice, Score, and Noul judgments; `loki setup jev` exposes the credential-gated `typesafe_ask` tool and can opt you into **Loki Autorouter — powered by Jev**, a same-gateway, session-sticky cost/capability model router.

### 🖥️ Computer & browser control

- **[Computer Use Linux](https://github.com/agent-sh/computer-use-linux)** — Linux desktop-control MCP server with AT-SPI accessibility trees, Wayland/X11 input, screenshots, and compositor-aware window targeting.
- **[Browser Use macOS](https://guardianbrowser.sh)** — Guardian Browser for agent-oriented browser and search workflows on macOS, including deterministic Agent Mode controls.

### 🧱 Virtualization & sandboxes

- **[AgentVM](https://agentvm.sh)** — disposable Linux servers and MCP sandboxes for workloads that should be isolated from the host filesystem, with bounded runtimes, SSH access, and lifecycle controls.

### 📱 Mobile access

- **[WaltonBot](https://walton.bot)** — mobile companion for Loki Agent on iPhone and iPad, useful for continuing agent workflows away from the terminal while Loki remains on its host machine.

---

## 🤝 Community

- 💬 **[Discord](https://discord.gg/yEaT8dv5Xn)** — discussion, support, and project updates.
- 🧠 **[Skills Hub](https://agentskills.io)** — reusable agent skills compatible with Loki's skills system.
- 🐞 **[Issues](https://github.com/wundercorp/loki/issues)** — bug reports, feature requests, and reproducible regressions.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

Built by [WunderCorp, Inc.](https://wundercorp.co).
