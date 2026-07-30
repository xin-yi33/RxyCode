"""Modern UI components for RxyCode - strict MiMo alignment.

Color system:
  + Thought: X.Xs  ->  pure yellow (#FFD700)
  capability titles ->  yellow bold
  mode + model      ->  light purple (#B39DDB)
  cache size/rate   ->  cyan (#00BCD4)
  status bar text   ->  light gray (#888)
  input box left    ->  mode color
"""

import sys
import os
import re
import time
import threading
from typing import Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from .i18n import i18n


def load_config() -> dict:
    """Deferred import wrapper so tests can patch this symbol directly."""
    from RxyCode.RxyCode1_1_0.config.settings import load_config as _load

    return _load()


class TokenStats:
    """Track token usage and system statistics.

    FIX-2: Improved cache statistics tracking and display.
    The old implementation had issues with cache_size always showing 0.

    Cost: computed from the per-model ``pricing`` section in config.yaml
    ({model: {input: $/M tokens, output: $/M tokens}}). When the active
    model has no pricing entry, ``billing_amount`` is None — we never show
    a guessed/hard-coded price.
    """

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.context_used = 0
        self.context_max = 256000
        self.cache_size = 0
        # Real provider-side usage (DeepSeek/OpenAI context caching)
        self.prompt_tokens = 0          # total prompt tokens billed
        self.cache_hit_tokens = 0       # prompt tokens served from provider cache
        self._application_cache_lock = threading.RLock()
        self.application_cache_hits = {"precise": 0, "semantic": 0}
        self.application_cache_misses = {"precise": 0, "semantic": 0}
        self.application_cache_bypasses = {"precise": 0, "semantic": 0}
        self._model_name: Optional[str] = None

    def set_model(self, model_name: Optional[str]) -> None:
        """Set the active model name used for pricing lookups."""
        self._model_name = model_name

    def add_real_usage(self, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0):
        """Record real token usage reported by the LLM provider.

        cache_read_tokens are the prompt tokens that hit the provider's
        context cache (DeepSeek `prompt_cache_hit_tokens` /
        OpenAI `prompt_tokens_details.cached_tokens`).
        """
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)
        self.prompt_tokens += int(input_tokens or 0)
        self.cache_hit_tokens += int(cache_read_tokens or 0)
        if cache_read_tokens:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
        # FIX-2: Always update cache_size, even when cache_read_tokens is 0
        self.cache_size = self.cache_hit_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        # FIX-2: Handle edge case when no tokens have been processed yet
        if self.prompt_tokens == 0 and self.cache_hits == 0 and self.cache_misses == 0:
            return 0.0
        # Prefer the real provider cache-hit ratio (tokens served from cache /
        # total prompt tokens) - this is the metric mainstream agents show.
        if self.prompt_tokens > 0:
            return self.cache_hit_tokens / self.prompt_tokens * 100
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total * 100

    @property
    def context_percent(self) -> float:
        if self.context_max == 0:
            return 0.0
        return self.context_used / self.context_max * 100

    @property
    def billing_amount(self) -> "Optional[float]":
        """Estimated cost in USD from the config ``pricing`` section.

        Returns None when the active model has no pricing entry (or config
        cannot be read) — callers must treat None as "do not display".
        """
        if not self._model_name:
            return None
        try:
            cfg = load_config() or {}
        except Exception:
            return None
        pricing = (cfg.get("pricing") or {}).get(self._model_name)
        if not pricing:
            return None
        input_price = float(pricing.get("input", 0) or 0)
        output_price = float(pricing.get("output", 0) or 0)
        input_cost = self.input_tokens / 1_000_000 * input_price
        output_cost = self.output_tokens / 1_000_000 * output_price
        return input_cost + output_cost

    def add_usage(self, input_tokens: int, output_tokens: int, cache_hit: bool = False):
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if cache_hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

    def record_application_cache(
        self,
        cache_type: str,
        *,
        hit: bool | None = None,
        bypass: bool = False,
    ) -> None:
        """Record an eligible lookup outcome or an intentional bypass."""
        if cache_type not in self.application_cache_hits:
            raise ValueError(f"Unsupported application cache type: {cache_type}")
        if bypass == (hit is not None):
            raise ValueError("Record exactly one of hit=<bool> or bypass=True")
        with self._application_cache_lock:
            if bypass:
                self.application_cache_bypasses[cache_type] += 1
                return
            target = (
                self.application_cache_hits
                if hit
                else self.application_cache_misses
            )
            target[cache_type] += 1

    def get_application_cache_stats(self) -> dict[str, dict[str, int | float]]:
        """Return per-layer counts and rates with explicit denominators."""
        snapshot: dict[str, dict[str, int | float]] = {}
        with self._application_cache_lock:
            for cache_type in self.application_cache_hits:
                hits = self.application_cache_hits[cache_type]
                misses = self.application_cache_misses[cache_type]
                bypassed = self.application_cache_bypasses[cache_type]
                eligible = hits + misses
                requests = eligible + bypassed
                snapshot[cache_type] = {
                    "requests": requests,
                    "eligible": eligible,
                    "bypassed": bypassed,
                    "hits": hits,
                    "misses": misses,
                    "hit_rate": round(hits / eligible * 100, 2) if eligible else 0.0,
                    "miss_rate": round(misses / eligible * 100, 2) if eligible else 0.0,
                    "eligibility_rate": (
                        round(eligible / requests * 100, 2) if requests else 0.0
                    ),
                    "bypass_rate": (
                        round(bypassed / requests * 100, 2) if requests else 0.0
                    ),
                }
        return snapshot

    # Token budget warning threshold: warn when context usage exceeds this
    TOKEN_WARNING_THRESHOLD = 0.85

    def should_warn_about_token_budget(self) -> bool:
        """Check if context usage is approaching the limit."""
        if self.context_max == 0:
            return False
        return self.context_used / self.context_max >= self.TOKEN_WARNING_THRESHOLD

    def get_context_warning(self) -> "Optional[str]":
        """Get a warning message if approaching token budget limit."""
        if self.context_max == 0:
            return None
        pct = self.context_used / self.context_max * 100
        if pct >= 95:
            return f"CRITICAL: Context at {pct:.0f}% ({self.context_used}/{self.context_max}). Consider /clear"
        elif pct >= 85:
            return f"Warning: Context at {pct:.0f}% ({self.context_used}/{self.context_max}). Consider /clear soon"
        return None

    def update_context(self, used: int, max_ctx: Optional[int] = None):
        self.context_used = used
        if max_ctx is not None:
            self.context_max = max_ctx

    def reset(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.context_used = 0
        self.cache_size = 0
        self.prompt_tokens = 0
        self.cache_hit_tokens = 0
        with self._application_cache_lock:
            self.application_cache_hits = {"precise": 0, "semantic": 0}
            self.application_cache_misses = {"precise": 0, "semantic": 0}
            self.application_cache_bypasses = {"precise": 0, "semantic": 0}


# Module-level singleton instance
token_stats = TokenStats()


def _get_memory_info() -> tuple[float, float]:
    """Get memory usage in MB and percentage."""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem = process.memory_info().rss
        mem_mb = mem / (1024 * 1024)
        total = psutil.virtual_memory().total
        mem_pct = mem / total * 100 if total > 0 else 0
        return mem_mb, mem_pct
    except ImportError:
        return 0.0, 0.0


def _format_cache_size(size_tokens: int) -> str:
    """Format cache size to human readable.
    
    FIX-2: The input is token count, not bytes.
    Display as token count with appropriate formatting.
    """
    if size_tokens == 0:
        return "0"
    elif size_tokens < 1000:
        return f"{size_tokens}"
    elif size_tokens < 1000000:
        return f"{size_tokens/1000:.1f}K"
    else:
        return f"{size_tokens/1000000:.2f}M"


def _safe_print(text=None):
    """Safely print text to stdout."""
    try:
        if text is None:
            print()
        elif isinstance(text, Text):
            Console().print(text)
        else:
            print(text)
    except Exception:
        pass


def print_step(num: int, total: int, desc: str):
    """Print step indicator."""
    text = Text()
    text.append(f"  {num}/{total} ", style="dim")
    text.append(desc, style="yellow")
    _safe_print(text)


def print_step_done(num: int, total: int, desc: str):
    """Print step done indicator."""
    text = Text()
    text.append(f"  ✓ {num}/{total} ", style="green")
    text.append(desc, style="bright_white")
    _safe_print(text)


def print_thought(elapsed: float):
    """Print thought indicator with yellow color."""
    text = Text()
    text.append(f"  ✓ Thought: {elapsed:.1f}s", style="#FFD700")
    _safe_print(text)


def print_tool_call(name: str, args: str):
    """Print tool call."""
    text = Text()
    text.append(f"    {name}(", style="cyan")
    text.append(args, style="dim cyan")
    text.append(")", style="cyan")
    _safe_print(text)


def print_tool_result(result: str, status: str = "success"):
    """Print tool result."""
    preview = result[:200] + "..." if len(result) > 200 else result
    text = Text()
    if status == "error":
        text.append(f"    ✗ ", style="bold red")
        text.append(preview, style="red")
    elif status == "warning":
        text.append(f"    ⚠ ", style="bold yellow")
        text.append(preview, style="yellow")
    else:
        text.append(f"    ✓ ", style="bold green")
        text.append(preview, style="green")
    _safe_print(text)


def print_success(msg: str):
    """Print success message."""
    text = Text()
    text.append("  [OK] ", style="bold green")
    text.append(msg, style="green")
    _safe_print(text)


def print_error(msg: str):
    """Print error message."""
    text = Text()
    text.append("  [ERR] ", style="bold red")
    text.append(msg, style="red")
    _safe_print(text)


def print_info(msg: str):
    """Print info message."""
    text = Text()
    text.append("  ", style="dim")
    text.append(msg, style="dim")
    _safe_print(text)


def print_warning(msg: str):
    """Print warning."""
    text = Text()
    text.append("  ! ", style="bold yellow")
    text.append(msg, style="yellow")
    _safe_print(text)


def print_goodbye():
    """Print goodbye."""
    _safe_print()


def print_command_hint():
    """Print command hints."""
    text = Text()
    text.append("  $ ", style="bold magenta")
    text.append(i18n.t('help_slash_hint'), style="dim")
    text.append("  · ", style="dim")
    text.append(i18n.t('help_mode_hint'), style="dim")
    _safe_print(text)


def print_chat_history_header(title: str):
    """Print chat history header."""
    text = Text()
    text.append(f"\n  ", style="dim")
    text.append(f"{title}", style="bold cyan")
    text.append("\n", style="dim")
    _safe_print(text)


def print_chat_saved(name: str):
    """Print chat saved message."""
    print_success(f"{i18n.t('msg_chat_saved')}: {name}")


def print_chat_loaded(name: str):
    """Print chat loaded message."""
    print_success(f"{i18n.t('msg_chat_loaded')}: {name}")


def print_chat_list(chats: list[dict]):
    """Print chat list with clean formatting."""
    if not chats:
        print_info(i18n.t('msg_no_saved_chats'))
        return

    _safe_print()
    _safe_print(Text(f"  {i18n.t('msg_saved_chats')}:", style="bold cyan"))
    _safe_print()
    for chat in chats:
        name = chat.get('name', '')
        preview = chat.get('preview', '')[:40]
        text = Text()
        text.append(f"    · ", style="dim")
        text.append(f"{name}", style="bright_white")
        if preview:
            text.append(f" ({preview}...)", style="dim")
        _safe_print(text)
    _safe_print()


def print_subagent_start(task: str):
    """Print sub-agent start message."""
    print_info(f"{i18n.t('subagent_creating')}: {task[:60]}")


def print_subagent_complete(result: str):
    """Print sub-agent complete message."""
    print_success(i18n.t('subagent_complete'))


def print_auto_resume_prompt(chats: list[dict]):
    """Print auto-resume prompt with clean formatting."""
    _safe_print()
    _safe_print(Text(f"  {i18n.t('help_auto_resume')}", style="bright_cyan"))
    _safe_print()
    for i, chat in enumerate(chats[:10], 1):
        name = chat.get('name', '')
        preview = chat.get('preview', '')[:40]
        text = Text()
        text.append(f"    {i}. ", style="dim")
        text.append(f"{name}", style="bright_white")
        if preview:
            text.append(f" ({preview}...)", style="dim")
        _safe_print(text)
    _safe_print()
    text = Text()
    text.append("    0. ", style="dim")
    text.append(i18n.t('msg_new_chat'), style="bright_white")
    _safe_print(text)
    _safe_print()
