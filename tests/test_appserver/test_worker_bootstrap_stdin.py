"""Bootstrap must not overlap piped stdin.readline (Windows import deadlock)."""

from appserver.agent_worker import dispatch_overlaps_stdin_readline


def test_bootstrap_does_not_overlap_stdin_readline():
    assert dispatch_overlaps_stdin_readline("prompt") is True
    assert dispatch_overlaps_stdin_readline("interrupt") is True
    assert dispatch_overlaps_stdin_readline("bootstrap") is False
    assert dispatch_overlaps_stdin_readline("model/switch") is False
    assert dispatch_overlaps_stdin_readline("shutdown") is False
