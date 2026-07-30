# lsp/ - LSP Integration

## What Is This Module?
Language Server Protocol (LSP) client for code intelligence features: diagnostics, completions, and references.

## Key Files
| File | Purpose |
|------|---------|
| client.py | LSPClient - connects to language servers for code analysis |

## Core Code: client.py (LSPClient)

**Capabilities:**
- Get diagnostics (errors, warnings) for a file
- Get code completions at a position
- Find references to a symbol
- Get hover information

**Key Methods:**
- connect(language): Start LSP server for a language
- get_diagnostics(uri) -> list: Get diagnostics for a file
- get_completions(uri, position) -> list: Get completions
- disconnect(): Stop LSP server

**Status:** Experimental - not fully integrated into the agent pipeline.
