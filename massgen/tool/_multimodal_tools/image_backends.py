"""
Per-backend image calling functions for understand_image.

Each function takes a list of LoadedImage objects, a prompt, and a model name,
and returns the response text from the respective API.

This module handles only the API call layer. Image loading, validation, and
result formatting are handled by understand_image.py.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from massgen.logger_config import logger

if TYPE_CHECKING:
    from massgen.tool._multimodal_tools.understand_image import LoadedImage


async def call_openai(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    previous_response_id: str | None = None,
    reasoning_effort: str | None = None,
) -> tuple[str, str | None]:
    """Call OpenAI Responses API for image understanding.

    Returns (response_text, response_id) tuple. The response_id can be passed
    back as previous_response_id for follow-up conversations.

    ``reasoning_effort`` defaults to ``None`` (API default — legacy behavior).
    Pass ``"low"`` for latency-bounded callers (the `--fast` preset wires this
    in via ``multimodal_config.image.reasoning_effort``) or ``"medium"`` /
    ``"high"`` when depth matters more than latency.
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key)

    content: list[dict] = [{"type": "input_text", "text": prompt}]
    for img in loaded_images:
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{img.mime_type};base64,{img.base64_data}",
            },
        )

    logger.info(
        f"[image_backends] Using OpenAI {model} for {len(loaded_images)} image(s) " f"(reasoning_effort={reasoning_effort!r})",
    )

    create_kwargs: dict = {
        "model": model,
        "input": [{"role": "user", "content": content}],
    }
    if system_prompt:
        create_kwargs["instructions"] = system_prompt
    if previous_response_id:
        create_kwargs["previous_response_id"] = previous_response_id
    # Only GPT-5.x models support reasoning_effort on the Responses API.
    # Older models (gpt-4o, gpt-4.1, etc.) will reject the param.
    if reasoning_effort is not None and model.startswith("gpt-5"):
        create_kwargs["reasoning"] = {"effort": reasoning_effort}

    response = await client.responses.create(**create_kwargs)

    text = response.output_text if hasattr(response, "output_text") else str(response.output)
    resp_id = getattr(response, "id", None)
    return (text, resp_id)


async def call_claude(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    conversation_messages: list[dict] | None = None,
) -> tuple[str, None]:
    """Call Anthropic Claude API for image understanding.

    Returns (response_text, None) tuple. Claude does not support server-side
    conversation threading, so conversation_messages must be re-sent for
    follow-ups.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not found in environment")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    content: list[dict] = []
    for img in loaded_images:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.mime_type,
                    "data": img.base64_data,
                },
            },
        )
    content.append({"type": "text", "text": prompt})

    logger.info(f"[image_backends] Using Claude {model} for {len(loaded_images)} image(s)")

    messages: list[dict] = []
    if conversation_messages:
        messages.extend(conversation_messages)
    messages.append({"role": "user", "content": content})

    create_kwargs: dict = {
        "model": model,
        "max_tokens": 4096,
        "messages": messages,
    }
    if system_prompt:
        create_kwargs["system"] = system_prompt

    response = await client.messages.create(**create_kwargs)

    return (response.content[0].text, None)


async def call_gemini(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    conversation_messages: list[dict] | None = None,
) -> tuple[str, None]:
    """Call Google Gemini API for image understanding.

    Returns (response_text, None) tuple. Gemini does not support server-side
    conversation threading; conversation_messages are prepended to contents
    for follow-ups.
    """
    from google import genai

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not found in environment")

    client = genai.Client(api_key=api_key)

    contents = []
    if conversation_messages:
        for msg in conversation_messages:
            contents.append(msg.get("content", ""))
    for img in loaded_images:
        contents.append(
            genai.types.Part.from_bytes(
                data=base64.b64decode(img.base64_data),
                mime_type=img.mime_type,
            ),
        )
    contents.append(prompt)

    logger.info(f"[image_backends] Using Gemini {model} for {len(loaded_images)} image(s)")

    generate_kwargs: dict = {"model": model, "contents": contents}
    if system_prompt:
        generate_kwargs["config"] = genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
        )

    response = client.models.generate_content(**generate_kwargs)

    return (response.text, None)


async def call_grok(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    conversation_messages: list[dict] | None = None,
) -> tuple[str, None]:
    """Call xAI Grok API for image understanding.

    Returns (response_text, None) tuple. Grok uses OpenAI-compatible chat
    completions; conversation_messages are prepended for follow-ups.
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise ValueError("XAI_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if conversation_messages:
        messages.extend(conversation_messages)

    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in loaded_images:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img.mime_type};base64,{img.base64_data}",
                },
            },
        )
    messages.append({"role": "user", "content": content})

    logger.info(f"[image_backends] Using Grok {model} for {len(loaded_images)} image(s)")

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
    )

    return (response.choices[0].message.content, None)


async def call_claude_code(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str | None = None,
    agent_cwd: str | None = None,
    system_prompt: str | None = None,
) -> tuple[str, None]:
    """Call Claude Code SDK for image understanding.

    Returns (response_text, None) tuple. Claude Code subprocess does not
    support conversation threading.
    """
    from claude_agent_sdk import (  # type: ignore
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
        UserMessage,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        image_refs = []
        for img in loaded_images:
            dest = Path(tmpdir) / img.path.name
            shutil.copy2(img.path, dest)
            image_refs.append(dest.name)

        image_list = ", ".join(image_refs)
        prefix = f"[System instruction]\n{system_prompt}\n\n" if system_prompt else ""
        full_prompt = f"{prefix}Read and analyze the image(s) in this directory: {image_list}\n\n{prompt}"

        options_kwargs: dict = {
            "allowed_tools": ["Read"],
            "cwd": tmpdir,
            # Unset CLAUDECODE to allow launching from within a Claude Code session
            # (the nested-session guard checks this env var)
            "env": {"CLAUDECODE": ""},
        }
        if model:
            options_kwargs["model"] = model

        options = ClaudeAgentOptions(**options_kwargs)
        client = ClaudeSDKClient(options)

        logger.info(f"[image_backends] Using Claude Code for {len(loaded_images)} image(s)")

        try:
            await client.connect()
            await client.query(full_prompt)

            response_text = ""
            async for msg in client.receive_response():
                logger.debug(
                    f"[image_backends] Claude Code msg type={type(msg).__name__}, " f"has content={hasattr(msg, 'content')}",
                )
                if isinstance(msg, (AssistantMessage, UserMessage)):
                    for block in msg.content:
                        logger.debug(
                            f"[image_backends]   block type={type(block).__name__}, " f"has text={hasattr(block, 'text')}",
                        )
                        if isinstance(block, TextBlock):
                            response_text += block.text
                elif isinstance(msg, ResultMessage):
                    break
        finally:
            await client.disconnect()

    return (response_text, None)


async def call_codex(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str | None = None,
    agent_cwd: str | None = None,
    system_prompt: str | None = None,
) -> tuple[str, None]:
    """Call OpenAI Codex CLI for image understanding.

    Returns (response_text, None) tuple. Codex subprocess does not support
    conversation threading.

    Sandboxing:
    - ``--skip-git-repo-check``: temp dir is not a git repo
    - ``--disable shell_tool``: prevent shell/bash execution
    - ``-c web_search="disabled"``: disable web search
    - ``cwd=tmpdir``: isolate filesystem access to temp dir with only copied images

    Auth: Creates a ``.codex/`` dir inside the temp dir with ``auth.json``
    copied from ``~/.codex/`` and sets ``CODEX_HOME`` to point there,
    matching the pattern used by ``massgen/backend/codex.py``.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        image_paths = []
        for img in loaded_images:
            dest = Path(tmpdir) / img.path.name
            shutil.copy2(img.path, dest)
            image_paths.append(str(dest))

        # Set up CODEX_HOME with auth — same pattern as massgen/backend/codex.py
        codex_home = Path(tmpdir) / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        host_auth = Path.home() / ".codex" / "auth.json"
        if host_auth.exists():
            shutil.copy2(str(host_auth), str(codex_home / "auth.json"))
        host_config = Path.home() / ".codex" / "config.toml"
        if host_config.exists():
            shutil.copy2(str(host_config), str(codex_home / "config.toml"))

        logger.info(f"[image_backends] Using Codex CLI for {len(loaded_images)} image(s)")

        effective_prompt = prompt
        if system_prompt:
            effective_prompt = f"[System instruction]\n{system_prompt}\n\n{prompt}"

        cmd = [
            "codex",
            "exec",
            effective_prompt,
            "--full-auto",
            "--skip-git-repo-check",
            "--disable",
            "shell_tool",
            "-c",
            "web_search=disabled",
        ]
        if model:
            cmd.extend(["--model", model])
        for img_path in image_paths:
            cmd.extend(["--image", img_path])

        env = {**os.environ, "NO_COLOR": "1", "CODEX_HOME": str(codex_home)}

        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            cwd=tmpdir,
            env=env,
            timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Codex CLI failed (exit {result.returncode}): {result.stderr}")

    return (result.stdout, None)
