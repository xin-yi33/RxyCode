from __future__ import annotations

import asyncio
import base64
import io
import threading
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.prompt_attachments import (
    MAX_INLINE_TEXT_TOTAL_BYTES,
    PromptAttachmentError,
    content_text_for_summary,
    estimate_content_tokens,
    human_message_content,
    prepare_prompt_attachments,
)


def _file(tmp_path, name: str, content: bytes):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_no_attachment_and_text_only_attachment_keep_string_wire_shape(tmp_path):
    prompt = "Explain this"
    empty = prepare_prompt_attachments([], supports_vision=False)
    assert human_message_content(prompt, empty) == prompt

    text_file = _file(tmp_path, "notes.md", b"selected notes")
    prepared = prepare_prompt_attachments(
        [{"path": str(text_file), "name": "Notes"}], supports_vision=False
    )
    content = human_message_content(prompt, prepared)
    assert isinstance(content, str)
    assert "selected notes" in content
    assert "Notes" in prepared.metadata[0]["name"]


def test_deepseek_v4_flash_text_attachment_remains_plain_string_wire_content(tmp_path):
    from core import providers
    from core.agent_v2 import AgentV2

    provider = providers.resolve(
        {"base_url": "https://api.deepseek.com/v1", "model_name": "deepseek-v4-flash"}
    )
    caps = provider.capabilities({"model_name": "deepseek-v4-flash"})
    assert caps.supports_vision is False
    pdf = _file(tmp_path, "manual.pdf", b"%PDF-1.7\nnot embedded")
    prepared = prepare_prompt_attachments(
        [{"path": str(pdf)}], supports_vision=caps.supports_vision
    )
    message = HumanMessage(content=human_message_content("Summarize", prepared))
    wire = AgentV2._to_openai_messages([message], provider_id="deepseek")
    assert isinstance(wire[0]["content"], str)
    assert "PDF file reference" in wire[0]["content"]


def test_inline_text_is_bounded_strict_and_rejects_control_bytes(tmp_path):
    first = _file(tmp_path, "first.txt", ("行" * 10922).encode("utf-8"))
    second = _file(tmp_path, "second.txt", ("字" * 10922).encode("utf-8"))
    overflow = _file(tmp_path, "overflow.txt", b"small")
    nul_text = _file(tmp_path, "nul.txt", b"valid\x00but-not-text")
    prepared = prepare_prompt_attachments(
        [
            {"path": str(first)},
            {"path": str(second)},
            {"path": str(overflow)},
            {"path": str(nul_text)},
        ],
        supports_vision=False,
    )
    assert "[inline preview truncated" in prepared.text_context
    assert len(prepared.text_context.encode("utf-8")) < MAX_INLINE_TEXT_TOTAL_BYTES + 2000
    assert "UTF-8 text attachment nul.txt" not in prepared.text_context
    assert "File reference nul.txt" in prepared.text_context


def test_corrupt_image_signature_errors_but_extension_spoof_is_text(tmp_path):
    corrupt = _file(tmp_path, "broken.bin", b"\x89PNG\r\n\x1a\nnot a png")
    with pytest.raises(PromptAttachmentError, match="signature.*damaged"):
        prepare_prompt_attachments([{"path": str(corrupt)}], supports_vision=True)

    spoof = _file(tmp_path, "plain.png", b"ordinary UTF-8 notes, not an image")
    prepared = prepare_prompt_attachments([{"path": str(spoof)}], supports_vision=False)
    assert "ordinary UTF-8 notes" in prepared.text_context
    assert prepared.image_blocks == []


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF", "ICO"])
def test_supported_image_formats_normalize_to_native_png_blocks(tmp_path, image_format):
    Image = pytest.importorskip("PIL.Image")
    stream = io.BytesIO()
    # Pillow's ICO writer emits a real icon only at the supported 16px size;
    # smaller inputs produce a header-only fixture rather than an image.
    source = Image.new("RGB", (16, 16), "navy")
    try:
        source.save(stream, format=image_format)
    except (OSError, ValueError) as exc:
        if image_format == "WEBP":
            pytest.skip(f"Pillow WebP encoder unavailable: {exc}")
        raise
    path = _file(tmp_path, f"sample.{image_format.lower()}", stream.getvalue())
    prepared = prepare_prompt_attachments([{"path": str(path)}], supports_vision=True)
    assert len(prepared.image_blocks) == 1
    url = prepared.image_blocks[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]).startswith(b"\x89PNG\r\n\x1a\n")


def test_animated_gif_uses_first_frame_and_nonvision_fails_before_model_call(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    first = Image.new("RGB", (4, 4), "red")
    second = Image.new("RGB", (4, 4), "blue")
    gif = tmp_path / "two.gif"
    first.save(gif, format="GIF", save_all=True, append_images=[second], duration=10, loop=0)
    prepared = prepare_prompt_attachments([{"path": str(gif)}], supports_vision=True)
    assert "first frame only" in prepared.text_context

    from core.session import Session

    class Agent:
        _capabilities = SimpleNamespace(supports_vision=False)
        _thinking_history = []
        _last_thinking = ""

        def set_session(self, _session_id):
            pass

        def _estimate_tokens(self, _messages):
            return 0

    session = Session(session_id="s1", workspace_root=tmp_path, emit=lambda _event: None)
    called = False

    async def dispatch(_agent, _text, _mode):
        nonlocal called
        called = True
        return "should not run"

    monkeypatch.setattr(session, "_dispatch_user_turn", dispatch)
    result = asyncio.run(
        session.prompt(Agent(), "What is in this picture?", mode="build", run_id="r1", attachments=[{"path": str(gif)}])
    )
    assert result.status == "failed"
    assert "does not support vision" in result.detail
    assert called is False


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX FIFO regression")
def test_fifo_rejected_before_open_and_never_blocks(tmp_path):
    import os
    import time

    fifo = tmp_path / "blocking"
    os.mkfifo(fifo)
    started = time.monotonic()
    with pytest.raises(PromptAttachmentError, match="regular"):
        prepare_prompt_attachments([{"path": str(fifo)}], supports_vision=False)
    assert time.monotonic() - started < 0.5


def test_model_switch_to_text_only_keeps_reference_and_discloses_old_image():
    from core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._capabilities = SimpleNamespace(supports_vision=False)
    agent._prompt_attachment_active = False
    source_content = [
        {"type": "text", "text": 'Image attachment photo.png; local reference "C:/data/photo.png".'},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,SECRET"}},
    ]
    agent._agent_prefix_messages = [
        SystemMessage(content="frozen system"),
        HumanMessage(content=source_content),
        HumanMessage(content="follow-up"),
    ]
    continued = agent._continue_agent_prefix("frozen system", "new question")
    prior_content = continued[1].content
    assert isinstance(prior_content, str)
    assert "C:/data/photo.png" in prior_content
    assert "has not seen it" in prior_content
    assert "SECRET" not in prior_content
    wire = AgentV2._to_openai_messages(continued, provider_id="deepseek")
    assert isinstance(wire[1]["content"], str)
    assert "has not seen it" in wire[1]["content"]
    assert agent._agent_prefix_messages[1].content == source_content
    assert "SECRET" in agent._agent_prefix_messages[1].content[1]["image_url"]["url"]
    assert continued[-1].content == "new question"


def test_image_occupancy_is_fixed_not_base64_length_and_summary_never_copies_data():
    from core.compaction import occupancy_tokens, build_compaction_summary_prompt

    short = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + "a" * 20}}]
    long = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + "b" * 2_000_000}}]
    count = lambda value: len(value) // 3
    short_occupancy = estimate_content_tokens(short, count)
    long_occupancy = estimate_content_tokens(long, count)
    assert short_occupancy == long_occupancy == 1024
    assert occupancy_tokens([HumanMessage(content=short)], count=count) == occupancy_tokens(
        [HumanMessage(content=long)], count=count
    )

    summary = build_compaction_summary_prompt([HumanMessage(content=long)])[0].content
    assert "image attachment omitted" in summary
    assert "b" * 1024 not in summary
    assert "image_url" not in content_text_for_summary(long)


def test_openai_wire_and_compaction_keep_actual_current_image_block():
    from core.agent_v2 import AgentV2
    from core.compaction import compact_messages

    image_url = "data:image/png;base64,real-payload"
    image_content = [{"type": "text", "text": "inspect this"}, {"type": "image_url", "image_url": {"url": image_url}}]
    wire = AgentV2._to_openai_messages(
        [SystemMessage(content="sys"), HumanMessage(content=image_content)],
        provider_id="openai",
    )
    assert wire[1]["content"] == image_content
    assert any(block.get("type") == "image_url" for block in wire[1]["content"])

    messages = [SystemMessage(content="sys")]
    for index in range(4):
        content = image_content if index == 3 else f"turn {index}"
        messages.extend([HumanMessage(content=content), AIMessage(content=f"answer {index}")])
    compacted = compact_messages(messages, tail_turns=1)
    assert any(
        isinstance(message, HumanMessage)
        and isinstance(message.content, list)
        and any(block.get("type") == "image_url" for block in message.content if isinstance(block, dict))
        for message in compacted
    )


def _image_turn(index: int) -> HumanMessage:
    return HumanMessage(
        content=[
            {
                "type": "text",
                "text": f"Image attachment image-{index}.png; local file reference image-{index}.png.",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,RAW_IMAGE_{index}_" + (str(index) * 3000)
                },
            },
        ]
    )


def _image_messages(messages):
    return [
        message
        for message in messages
        if isinstance(message, HumanMessage)
        and isinstance(message.content, list)
        and any(
            isinstance(block, dict) and block.get("type") == "image_url"
            for block in message.content
        )
    ]


def test_repeated_image_turns_compact_to_a_finite_tail_and_safe_summary():
    from core.compaction import compact_messages

    messages = [SystemMessage(content="sys")]
    for index in range(8):
        messages.extend([_image_turn(index), AIMessage(content=f"answer {index}")])

    compacted = compact_messages(messages, tail_turns=2)
    visible_images = _image_messages(compacted)
    assert 1 <= len(visible_images) <= 2
    assert any("RAW_IMAGE_7_" in repr(message.content) for message in visible_images)
    summary = "\n".join(
        str(message.content)
        for message in compacted
        if getattr(message, "type", None) == "system"
        and (getattr(message, "additional_kwargs", None) or {}).get("is_compaction_summary")
    )
    assert "RAW_IMAGE_" not in summary
    assert "image-0.png" in summary
    assert "image attachment omitted from summary" in summary


def test_current_image_survives_compaction_with_zero_tail_turns():
    from core.agent_v2 import AgentV2
    from core.compaction import compact_messages

    messages = [
        SystemMessage(content="sys"),
        _image_turn(0),
        AIMessage(content="answer 0"),
        _image_turn(1),
        AIMessage(content="answer 1"),
        _image_turn(2),
    ]
    compacted = compact_messages(messages, tail_turns=0)

    visible_images = _image_messages(compacted)
    assert len(visible_images) == 1
    assert "RAW_IMAGE_2_" in repr(visible_images[0].content)
    assert "RAW_IMAGE_0_" not in repr(compacted)
    wire = AgentV2._to_openai_messages(compacted, provider_id="openai")
    wire_images = [
        block
        for message in wire
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "image_url"
    ]
    assert len(wire_images) == 1
    assert "RAW_IMAGE_2_" in wire_images[0]["image_url"]["url"]


def _prepared_png_attachment(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "selected.png"
    Image.new("RGB", (8, 8), "orange").save(path, format="PNG")
    return prepare_prompt_attachments(
        [{"path": str(path), "name": "selected.png"}], supports_vision=True
    )


def _assert_one_image_message(message):
    assert isinstance(message, HumanMessage)
    assert isinstance(message.content, list)
    blocks = [block for block in message.content if block.get("type") == "image_url"]
    assert len(blocks) == 1
    assert blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_compose_plan_and_build_each_capture_the_current_image(tmp_path, monkeypatch):
    from core import agent_v2
    from core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._prompt_attachment_context = _prepared_png_attachment(tmp_path)
    agent._prompt_attachment_active = True
    agent._prompt_attachment_renderer = human_message_content
    agent._capabilities = SimpleNamespace(supports_vision=True)
    agent._memory = SimpleNamespace(add_interaction=lambda *_args: None, save_session=lambda: None)
    agent._is_simple_query = lambda _text: True
    agent._include_few_shot = lambda: False
    agent._few_shot_limit = lambda: 0
    agent._prompt_variant = lambda: "default"
    monkeypatch.setattr(agent_v2, "get_role_prompt", lambda *_args, **_kwargs: "role")
    monkeypatch.setattr(agent_v2, "build_user_message", lambda *_args, **_kwargs: "compose stage")
    captured = []

    async def capture_plan(prompt):
        captured.append(agent._build_prompt_human_message(prompt))
        return "plan"

    async def capture_build(prompt, **_kwargs):
        captured.append(agent._build_prompt_human_message(prompt))
        return "built"

    agent._fast_reply = capture_plan
    agent._fast_reply_with_tools = capture_build
    result = asyncio.run(agent._run_compose("What is in the image?"))

    assert result == "built"
    assert len(captured) == 2
    for message in captured:
        _assert_one_image_message(message)


def test_reconstructed_retry_message_captures_image_again_without_duplicate_blocks(tmp_path):
    from core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._prompt_attachment_context = _prepared_png_attachment(tmp_path)
    agent._prompt_attachment_active = True
    agent._prompt_attachment_renderer = human_message_content
    agent._capabilities = SimpleNamespace(supports_vision=True)
    agent._agent_prefix_messages = [SystemMessage(content="system")]

    # Each failed/reconstructed call gets a fresh real HumanMessage. A tool
    # reminder, by contrast, reuses its original message list and never calls
    # this constructor again.
    first_attempt = agent._continue_agent_prefix("system", "retry this request")[-1]
    retry_attempt = agent._continue_agent_prefix("system", "retry this request")[-1]
    _assert_one_image_message(first_attempt)
    _assert_one_image_message(retry_attempt)
    assert first_attempt.content == retry_attempt.content


def test_attachment_turn_uses_primary_agent_even_when_session_team_route_is_enabled(
    monkeypatch, tmp_path
):
    from core import session as session_module
    from core.session import Session

    session = Session(
        session_id="s1", workspace_root=tmp_path, emit=lambda _event: None
    )
    session._session_subagents_opt_in = True
    called = []

    class Agent:
        _prompt_attachment_active = True

        async def run(self, text, *, mode):
            called.append((text, mode))
            return "direct result"

    monkeypatch.setattr(
        session_module,
        "get_default_router",
        lambda: pytest.fail("attachment turn must not enter team router"),
    )
    answer = asyncio.run(
        session._dispatch_user_turn(Agent(), "Describe the selected image", "build")
    )
    assert answer == "direct result"
    assert called == [("Describe the selected image", "build")]


def test_real_provider_usage_remains_authoritative_for_image_messages():
    from core.agent_v2 import _usage_counts

    huge_image = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + "x" * 2_000_000}}]
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 73, "output_tokens": 9},
        content="answer",
    )
    assert _usage_counts(response, [HumanMessage(content=huge_image)]) == (73, 9)


def test_session_prompt_restores_attachment_context_after_cancellation(tmp_path):
    from core.session import Session

    path = _file(tmp_path, "notes.txt", b"temporary prompt attachment")
    session = Session(
        session_id="s1", workspace_root=tmp_path, emit=lambda _event: None
    )
    session._agents_enabled = lambda: False
    original_context = object()

    class Agent:
        _capabilities = SimpleNamespace(supports_vision=True)
        _prompt_attachment_context = original_context
        _prompt_attachment_active = False

        def __init__(self):
            self.entered = asyncio.Event()

        async def run(self, _text, *, mode):
            assert mode == "build"
            assert self._prompt_attachment_active is True
            assert self._prompt_attachment_context.metadata[0]["path"] == str(path)
            self.entered.set()
            await asyncio.Event().wait()

    agent = Agent()

    async def cancel_prompt():
        task = asyncio.create_task(
            session.prompt(
                agent,
                "Use these notes",
                mode="build",
                run_id="cancelled-turn",
                attachments=[{"path": str(path), "name": "notes.txt"}],
            )
        )
        await agent.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_prompt())
    assert agent._prompt_attachment_context is original_context
    assert agent._prompt_attachment_active is False
    assert not hasattr(agent, "_prompt_attachment_renderer")


def test_slow_attachment_prepare_runs_off_loop_and_cancel_discards_late_result(
    monkeypatch, tmp_path
):
    from core import prompt_attachments
    from core.session import Session

    path = _file(tmp_path, "slow.txt", b"prepare away from the event loop")
    started = threading.Event()
    finished = threading.Event()
    original_context = object()
    session = Session(
        session_id="s1", workspace_root=tmp_path, emit=lambda _event: None
    )
    session._agents_enabled = lambda: False

    def slow_prepare(_items, *, supports_vision):
        assert supports_vision is True
        started.set()
        time.sleep(0.2)
        finished.set()
        return SimpleNamespace(
            has_attachments=True,
            metadata=[{"path": str(path), "name": "slow.txt"}],
        )

    monkeypatch.setattr(prompt_attachments, "prepare_prompt_attachments", slow_prepare)

    class Agent:
        _capabilities = SimpleNamespace(supports_vision=True)
        _prompt_attachment_context = original_context
        _prompt_attachment_active = False

        async def run(self, *_args, **_kwargs):
            pytest.fail("cancelled preparation must not start the model")

    agent = Agent()

    async def cancel_while_preparing():
        task = asyncio.create_task(
            session.prompt(
                agent,
                "Read this",
                mode="build",
                run_id="cancel-prepare",
                attachments=[{"path": str(path)}],
            )
        )
        await asyncio.to_thread(started.wait, 1)
        ticks = 0

        async def tick():
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0.01)
                ticks += 1

        ticker = asyncio.create_task(tick())
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await ticker
        assert ticks == 5
        assert agent._prompt_attachment_context is original_context
        assert agent._prompt_attachment_active is False
        assert not hasattr(agent, "_prompt_attachment_renderer")
        await asyncio.to_thread(finished.wait, 1)
        # The worker-thread result completed after cancellation, but is not
        # rebound into the Agent's request-local context.
        assert agent._prompt_attachment_context is original_context

    asyncio.run(cancel_while_preparing())


def test_first_ordinary_session_prompt_skips_attachment_thread_dispatch(monkeypatch, tmp_path):
    from core import session as session_module
    from core.session import Session

    session = Session(
        session_id="ordinary-first-turn", workspace_root=tmp_path, emit=lambda _event: None
    )
    session._agents_enabled = lambda: False
    ran = []

    class Agent:
        _capabilities = SimpleNamespace(supports_vision=False)
        _thinking_history = []
        _last_thinking = ""

        async def run(self, text, *, mode):
            ran.append((text, mode))
            return "ordinary response"

    async def unexpected_thread_dispatch(*_args, **_kwargs):
        pytest.fail("an ordinary prompt must not dispatch attachment preparation")

    monkeypatch.setattr(session_module.asyncio, "to_thread", unexpected_thread_dispatch)
    result = asyncio.run(
        session.prompt(Agent(), "Hello", mode="build", run_id="ordinary-first-turn")
    )
    assert result.status == "succeeded"
    assert result.answer == "ordinary response"
    assert ran == [("Hello", "build")]


def test_complex_compose_rejects_attachments_before_model_or_tool_dispatch(monkeypatch, tmp_path):
    from core import agent_v2
    from core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._prompt_attachment_active = True
    agent._routing_directive = None
    agent._detect_file_operation = lambda _text: None
    agent._detect_download_intent = lambda _text: None
    agent._is_simple_query = lambda _text: False
    monkeypatch.setattr(
        agent_v2,
        "route",
        lambda *_args, **_kwargs: SimpleNamespace(path="compose", skip_await=frozenset()),
    )

    with pytest.raises(PromptAttachmentError, match="no planning call or tool was started"):
        asyncio.run(agent._run_impl("Implement this complex request", mode="build"))
