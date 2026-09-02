# Quick start

Product version **1.3.0**. Protocol version stays `1.1.0`. Default CLI is OpenTUI: type `rxycode` in `cmd` or any terminal.

Desktop GUI binaries ship on this tag: Windows `setup.exe` / portable zip and a Linux AppImage. **No macOS build.** See [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0).

## Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | Backend runtime |
| Bun | latest | Auto-installed by the one-command installer when missing (OpenTUI) |
| Node.js | 20+ | Desktop GUI, Ink fallback (`RXYCODE_TUI=ink`) |
| OpenAI-compatible API key | — | Any provider you configure |

## Install the CLI (v1.3.0)

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.ps1 | iex"
rxycode
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.sh | sh
rxycode
```

**From the GitHub Release tarball:**

```bash
python -m pip install rxycode-1.3.0.tar.gz
rxycode
```

**uv:**

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0" rxycode
```

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0"
rxycode
```

The installer / tarball is **CLI / OpenTUI**. It does not include Electron. `rxycode gui` only works after you install a Desktop build from this release.

## Install Desktop (v1.3.0)

Download from [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0):

- Windows installer: `rxycode-desktop-1.3.0-setup.exe`
- Windows portable: `RxyCode.Desktop-1.3.0-win.zip`
- Linux: `rxycode-desktop-1.3.0.AppImage`

Then `rxycode gui`, or double-click the shortcut. Details: [GUI.md](GUI.md).

## First launch

1. Run `rxycode`. The TUI opens even with no model configured.
2. If the model list is empty, OpenTUI opens `/addmodel` (credentials are masked).
3. Type a natural-language task in the current folder.

| Command | What opens |
|---------|------------|
| `rxycode` | Default OpenTUI |
| `rxycode --version` | Package version, no runtime init |
| `rxycode gui` | Desktop, only if a v1.3.0 Desktop build is installed |
| `rxycode --api` | API server only |
| `RXYCODE_TUI=ink rxycode` | Ink fallback TUI |

## More

- [README](../README.md) — full English overview
- [Desktop GUI](GUI.md)
- [Expert teams](agent/README.md) — off by default
- [Release notes](release-notes/RELEASE_NOTES_v1.3.0.md)
