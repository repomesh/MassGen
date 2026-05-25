"""
Claude backend implementation using Anthropic's Messages API.
Production-ready implementation with full multi-tool support.

✅ FEATURES IMPLEMENTED:
- ✅ Messages API integration with streaming support
- ✅ Multi-tool support (server-side + user-defined tools combined)
- ✅ Web search tool integration with pricing tracking
- ✅ Code execution tool integration with session management
- ✅ Tool message format conversion for MassGen compatibility
- ✅ Advanced streaming with tool parameter streaming
- ✅ Error handling and token usage tracking
- ✅ Production-ready pricing calculations (2025 rates)

Multi-Tool Capabilities:
- Can combine web search + code execution + user functions in single request
- No API limitations unlike other providers
- Parallel and sequential tool execution supported
- Perfect integration with MassGen StreamChunk pattern
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import os
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

import anthropic
import httpx

from ..api_params_handler import ClaudeAPIParamsHandler
from ..formatter import ClaudeFormatter
from ..logger_config import log_backend_agent_message, log_stream_chunk, logger
from ..mcp_tools.backend_utils import MCPErrorHandler
from ..structured_logging import trace_llm_api_call
from ._streaming_buffer_mixin import StreamingBufferMixin
from .base import FilesystemSupport, StreamChunk
from .base_with_custom_tool_and_mcp import (
    CustomToolAndMCPBackend,
    CustomToolChunk,
    ToolExecutionConfig,
    UploadFileError,
)
from .llm_circuit_breaker import (
    CircuitBreakerOpenError,
    LLMCircuitBreaker,
)


class ClaudeBackend(StreamingBufferMixin, CustomToolAndMCPBackend):
    """Claude backend using Anthropic's Messages API with full multi-tool support."""

    def __init__(self, api_key: str | None = None, **kwargs):
        # Extract circuit breaker config before passing to super
        cb_config = self._build_circuit_breaker_config(kwargs)
        super().__init__(api_key, **kwargs)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.search_count = 0  # Track web search usage for pricing
        self.code_session_hours = 0.0  # Track code execution usage
        self.formatter = ClaudeFormatter()
        self.api_params_handler = ClaudeAPIParamsHandler(self)
        self._uploaded_file_ids: list[str] = []
        self.circuit_breaker = LLMCircuitBreaker(
            config=cb_config,
            backend_name="claude",
        )

    def supports_upload_files(self) -> bool:
        """Claude Vision supports inline images; Files API handles PDFs and text docs."""

        return True

    async def stream_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs,
    ) -> AsyncGenerator[StreamChunk]:
        """Override to ensure Files API cleanup happens after streaming completes."""
        self._clear_streaming_buffer(**kwargs)
        if self._nlip_enabled:
            logger.info(
                f"[Claude] NLIP routing enabled for agent {kwargs.get('agent_id', self.agent_id)}",
            )
        agent_id = kwargs.get("agent_id", self.agent_id)
        try:
            async for chunk in super().stream_with_tools(messages, tools, **kwargs):
                yield chunk
        finally:
            # Save streaming buffer before cleanup
            self._finalize_streaming_buffer(agent_id=agent_id)
            await self._cleanup_files_api_resources(**kwargs)

    async def _process_upload_files(
        self,
        messages: list[dict[str, Any]],
        all_params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Convert upload_files entries into Claude-compatible multimodal content."""

        processed_messages = await super()._process_upload_files(messages, all_params)
        if not processed_messages:
            return processed_messages

        allowed_mime_types = {
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
        }
        max_image_size_bytes = 5 * 1024 * 1024

        for message in processed_messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue

            converted_items: list[dict[str, Any]] = []
            for item in content:
                if not isinstance(item, dict):
                    converted_items.append(item)
                    continue

                item_type = item.get("type")
                if item_type == "file_pending_upload":
                    converted_items.append(item)
                    continue

                if item_type != "image":
                    converted_items.append(item)
                    continue

                if "source" in item and isinstance(item["source"], dict):
                    converted_items.append(item)
                    continue

                # Handle base64-encoded images
                if "base64" in item:
                    mime_type = (item.get("mime_type") or "").lower()
                    if mime_type not in allowed_mime_types:
                        raise UploadFileError(
                            f"Unsupported Claude image MIME type: {mime_type or 'unknown'}",
                        )

                    try:
                        decoded = base64.b64decode(item["base64"], validate=True)
                    except binascii.Error as exc:
                        raise UploadFileError("Invalid base64 image data") from exc

                    if len(decoded) > max_image_size_bytes:
                        raise UploadFileError(
                            "Claude Vision image exceeds 5MB size limit",
                        )

                    converted_item = {key: value for key, value in item.items() if key not in {"base64", "mime_type"}}
                    converted_item["type"] = "image"
                    converted_item["source"] = {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": item["base64"],
                    }
                    logger.debug(
                        "Converted base64 image for Claude Vision: %s",
                        converted_item.get("source_path", "inline"),
                    )
                    converted_items.append(converted_item)
                    continue

                # Handle URL-referenced images
                if "url" in item:
                    converted_item = {key: value for key, value in item.items() if key != "url"}
                    converted_item["type"] = "image"
                    converted_item["source"] = {
                        "type": "url",
                        "url": item["url"],
                    }
                    logger.debug(
                        "Converted URL image for Claude Vision: %s",
                        item["url"],
                    )
                    converted_items.append(converted_item)
                    continue

                # Handle Files API references
                if "file_id" in item:
                    converted_item = {key: value for key, value in item.items() if key != "file_id"}
                    converted_item["type"] = "image"
                    converted_item["source"] = {
                        "type": "file",
                        "file_id": item["file_id"],
                    }
                    logger.debug(
                        "Attached Claude file_id reference for image: %s",
                        item["file_id"],
                    )
                    converted_items.append(converted_item)
                    continue

                converted_items.append(item)

            message["content"] = converted_items

        return processed_messages

    async def _upload_files_via_files_api(
        self,
        messages: list[dict[str, Any]],
        client,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Upload files via Claude Files API and replace pending markers with document blocks.

        Claude Files API only supports PDF and TXT files. Unsupported files are gracefully
        skipped and replaced with informative text notes to maintain workflow continuity.
        """
        # Claude Files API only supports PDF and TXT files
        CLAUDE_FILES_API_SUPPORTED_EXTENSIONS = {".pdf", ".txt"}
        CLAUDE_FILES_API_SUPPORTED_MIME_TYPES = {
            "application/pdf",
            "text/plain",
            "text/txt",
        }

        # Find all file_pending_upload markers
        file_locations: list[tuple[int, int]] = []
        for msg_idx, message in enumerate(messages):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item_idx, item in enumerate(content):
                if isinstance(item, dict) and item.get("type") == "file_pending_upload":
                    file_locations.append((msg_idx, item_idx))

        if not file_locations:
            return messages

        httpx_client = None
        try:
            httpx_client = httpx.AsyncClient()

            # Track uploaded file IDs, skipped files, failed uploads, and their corresponding locations
            uploaded_files: list[tuple[int, int, str]] = []  # (msg_idx, item_idx, file_id)
            skipped_files: list[tuple[int, int, str, str]] = []  # (msg_idx, item_idx, filename, reason)
            failed_uploads: list[tuple[int, int, str, str]] = []  # (msg_idx, item_idx, filename, reason)

            for msg_idx, item_idx in file_locations:
                marker = messages[msg_idx]["content"][item_idx]
                source = marker.get("source")
                file_path = marker.get("path")
                url = marker.get("url")
                mime_type = marker.get("mime_type", "application/octet-stream")
                filename_hint = marker.get("filename") or marker.get("name")

                # Validate file extension and MIME type for Claude Files API
                file_ext = None
                filename = None

                if source == "local" and file_path:
                    file_ext = Path(file_path).suffix.lower()
                    filename = Path(file_path).name
                    # Re-validate MIME type using mimetypes module for accuracy
                    guessed_mime, _ = mimetypes.guess_type(file_path)
                    if guessed_mime:
                        mime_type = guessed_mime
                elif source == "url" and url:
                    # Extract extension from URL (strip query parameters and fragments)
                    url_path = url.split("?")[0].split("#")[0]
                    file_ext = Path(url_path).suffix.lower()
                    filename = Path(url_path).name or url
                    if not filename_hint:
                        filename_hint = filename
                    # Re-validate MIME type using mimetypes module
                    guessed_mime, _ = mimetypes.guess_type(url_path)
                    if guessed_mime:
                        mime_type = guessed_mime

                # Check if file type is supported (both extension and MIME type)
                is_supported = False
                skip_reason = None

                if file_ext and file_ext.lower() in CLAUDE_FILES_API_SUPPORTED_EXTENSIONS:
                    # Extension is supported, now check MIME type
                    if mime_type and mime_type.lower() in CLAUDE_FILES_API_SUPPORTED_MIME_TYPES:
                        is_supported = True
                    else:
                        skip_reason = f"MIME type '{mime_type}' not supported (extension {file_ext} is valid)"
                else:
                    skip_reason = f"File extension '{file_ext or 'unknown'}' not supported"

                # If file is not supported, skip it gracefully and log warning
                if not is_supported:
                    logger.warning(
                        f"[Agent {agent_id or 'default'}] Skipping unsupported file for Claude Files API: "
                        f"{filename or file_path or url} - {skip_reason}. "
                        f"Only PDF and TXT files are supported.",
                    )
                    skipped_files.append(
                        (
                            msg_idx,
                            item_idx,
                            filename or file_path or url or "unknown",
                            skip_reason,
                        ),
                    )
                    continue

                try:
                    if source == "local" and file_path:
                        # Upload local file
                        path_obj = Path(file_path)
                        filename = path_obj.name
                        with open(file_path, "rb") as f:
                            file_bytes = f.read()

                        uploaded_file = await client.beta.files.upload(
                            file=(filename, file_bytes, mime_type),
                        )
                        file_id = getattr(uploaded_file, "id", None)
                        if file_id:
                            self._uploaded_file_ids.append(file_id)
                            uploaded_files.append((msg_idx, item_idx, file_id))
                            logger.info(
                                f"[Agent {agent_id or 'default'}] Uploaded local file via Files API: {filename} -> {file_id}",
                            )
                        else:
                            failure_reason = "Claude Files API response missing file_id"
                            failed_uploads.append(
                                (
                                    msg_idx,
                                    item_idx,
                                    filename or filename_hint or file_path or "unknown",
                                    failure_reason,
                                ),
                            )
                            logger.warning(
                                f"[Agent {agent_id or 'default'}] Failed to upload file via Files API: {failure_reason}",
                            )

                    elif source == "url" and url:
                        # Download and upload URL file
                        response = await httpx_client.get(url, timeout=30.0)
                        response.raise_for_status()

                        # Enforce Claude Files API 500 MB size limit
                        max_size_bytes = 500 * 1024 * 1024  # 500 MB
                        content_length = response.headers.get("Content-Length")
                        if content_length:
                            file_size = int(content_length)
                            if file_size > max_size_bytes:
                                raise UploadFileError(
                                    f"File size {file_size / (1024 * 1024):.2f} MB exceeds Claude Files API limit of 500 MB",
                                )

                        file_bytes = response.content

                        # Cap bytes read if Content-Length was missing
                        if len(file_bytes) > max_size_bytes:
                            raise UploadFileError(
                                f"Downloaded file size {len(file_bytes) / (1024 * 1024):.2f} MB exceeds Claude Files API limit of 500 MB",
                            )

                        filename = url.split("/")[-1] or "document"

                        uploaded_file = await client.beta.files.upload(
                            file=(filename, file_bytes, mime_type),
                        )
                        file_id = getattr(uploaded_file, "id", None)
                        if file_id:
                            self._uploaded_file_ids.append(file_id)
                            uploaded_files.append((msg_idx, item_idx, file_id))
                            logger.info(
                                f"[Agent {agent_id or 'default'}] Uploaded URL file via Files API: {url} -> {file_id}",
                            )
                        else:
                            failure_reason = "Claude Files API response missing file_id"
                            failed_uploads.append(
                                (
                                    msg_idx,
                                    item_idx,
                                    filename or filename_hint or url or "unknown",
                                    failure_reason,
                                ),
                            )
                            logger.warning(
                                f"[Agent {agent_id or 'default'}] Failed to upload file via Files API: {failure_reason}",
                            )

                except Exception as upload_error:
                    logger.warning(
                        f"[Agent {agent_id or 'default'}] Failed to upload file via Files API: {upload_error}",
                    )
                    failure_context = filename or filename_hint or file_path or url or "unknown"
                    failed_uploads.append(
                        (msg_idx, item_idx, failure_context, str(upload_error)),
                    )
                    continue

        except Exception as e:
            logger.warning(
                f"[Agent {agent_id or 'default'}] Files API upload error: {e}",
            )
            raise UploadFileError(f"Files API upload failed: {e}") from e
        finally:
            if httpx_client:
                await httpx_client.aclose()

        # Clone messages and replace markers with document blocks or text notes
        updated_messages = [msg.copy() for msg in messages]

        # Replace successfully uploaded files with document blocks
        for msg_idx, item_idx, file_id in reversed(uploaded_files):
            content = updated_messages[msg_idx]["content"]
            if isinstance(content, list):
                # Create document block
                document_block = {
                    "type": "document",
                    "source": {
                        "type": "file",
                        "file_id": file_id,
                    },
                }
                # Replace marker with document block
                new_content = content[:item_idx] + [document_block] + content[item_idx + 1 :]
                updated_messages[msg_idx]["content"] = new_content

        # Replace skipped files with informative text notes
        for msg_idx, item_idx, filename, reason in reversed(skipped_files):
            content = updated_messages[msg_idx]["content"]
            if isinstance(content, list):
                # Create text note explaining the limitation
                text_note = {
                    "type": "text",
                    "text": (f"\n[Note: File '{filename}' was not uploaded to Claude Files API. " f"Reason: {reason}. " f"Claude Files API only supports PDF and TXT files.]\n"),
                }
                # Replace marker with text note
                new_content = content[:item_idx] + [text_note] + content[item_idx + 1 :]
                updated_messages[msg_idx]["content"] = new_content

        # Replace failed uploads with informative text notes
        for msg_idx, item_idx, filename, reason in reversed(failed_uploads):
            content = updated_messages[msg_idx]["content"]
            if isinstance(content, list):
                text_note = {
                    "type": "text",
                    "text": (f"\n[Note: File '{filename}' failed to upload to Claude Files API. " f"Reason: {reason}.]\n"),
                }
                new_content = content[:item_idx] + [text_note] + content[item_idx + 1 :]
                updated_messages[msg_idx]["content"] = new_content

        # Final sweep to ensure all file_pending_upload markers were replaced
        self._ensure_no_pending_upload_markers(updated_messages)

        return updated_messages

    async def _cleanup_files_api_resources(self, **kwargs) -> None:
        """Clean up uploaded files via Files API."""
        if not self._uploaded_file_ids:
            return

        agent_id = kwargs.get("agent_id")
        logger.info(
            f"[Agent {agent_id or 'default'}] Cleaning up {len(self._uploaded_file_ids)} Files API resources...",
        )

        client = None
        try:
            client = self._create_client(**kwargs)

            for file_id in self._uploaded_file_ids:
                try:
                    await client.beta.files.delete(file_id)
                    logger.debug(
                        f"[Agent {agent_id or 'default'}] Deleted Files API file: {file_id}",
                    )
                except Exception as delete_error:
                    logger.warning(
                        f"[Agent {agent_id or 'default'}] Failed to delete Files API file {file_id}: {delete_error}",
                    )
                    continue

            self._uploaded_file_ids.clear()
            logger.info(f"[Agent {agent_id or 'default'}] Files API cleanup completed")

        except Exception as e:
            logger.warning(
                f"[Agent {agent_id or 'default'}] Files API cleanup error: {e}",
            )
        finally:
            if client and hasattr(client, "aclose"):
                await client.aclose()  # type: ignore[attr-defined]

    def _ensure_no_pending_upload_markers(self, messages: list[dict[str, Any]]) -> None:
        """Raise UploadFileError if any file_pending_upload markers remain."""
        if not messages:
            return

        for msg_idx, message in enumerate(messages):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item_idx, item in enumerate(content):
                if isinstance(item, dict) and item.get("type") == "file_pending_upload":
                    identifier = item.get("filename") or item.get("name") or item.get("path") or item.get("url") or "unknown"
                    raise UploadFileError(
                        "Claude Files API upload left unresolved file_pending_upload marker " f"(message {msg_idx}, item {item_idx}, source {identifier}).",
                    )

    async def _stream_without_custom_and_mcp_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        client,
        **kwargs,
    ) -> AsyncGenerator[StreamChunk]:
        """Override to integrate Files API uploads into non-MCP streaming."""
        # Extract internal flags before merging kwargs (prevents API errors from unknown params)
        kwargs.pop("_compression_retry", None)

        agent_id = kwargs.get("agent_id", None)
        all_params = {**self.config, **kwargs}

        # Validate advanced features compatibility with model
        self._validate_advanced_features(all_params)

        # Notify frontend about programmatic flow status
        if all_params.get("enable_programmatic_flow"):
            log_stream_chunk(
                "backend.claude",
                "programmatic_flow",
                "Programmatic tool calling enabled - tools can be invoked from code execution",
                agent_id,
            )
            yield StreamChunk(
                type="content",
                content="\n🔄 [Programmatic Flow] Enabled - Claude can call tools from code execution\n",
            )

        # Notify frontend about tool search status
        if all_params.get("enable_tool_search"):
            variant = all_params.get("tool_search_variant", "regex")
            log_stream_chunk(
                "backend.claude",
                "tool_search",
                f"Tool search enabled (variant: {variant}) - deferred tools discovered on-demand",
                agent_id,
            )
            yield StreamChunk(
                type="content",
                content=f"\n🔍 [Tool Search] Enabled ({variant}) - Claude can discover deferred tools on-demand\n",
            )

        processed_messages = await self._process_upload_files(messages, all_params)

        # Check if we need to upload files via Files API
        if all_params.get("_has_file_search_files"):
            logger.info("Processing Files API uploads...")
            processed_messages = await self._upload_files_via_files_api(
                processed_messages,
                client,
                agent_id,
            )
            all_params["_has_files_api_files"] = True
            all_params.pop("_has_file_search_files", None)

        self._ensure_no_pending_upload_markers(processed_messages)

        api_params = await self.api_params_handler.build_api_params(
            processed_messages,
            tools,
            all_params,
        )

        if all_params.get("_strict_tool_use_enabled"):
            strict_count = all_params.get("_strict_tool_count", 0)
            strict_names = all_params.get("_strict_tool_names", [])
            log_stream_chunk(
                "backend.claude",
                "strict_tool_use",
                f"Strict tool use enabled for {strict_count} tools: {strict_names}",
                agent_id,
            )
            yield StreamChunk(
                type="content",
                content=f"\n🔒 [Strict Tool Use] Enabled for {strict_count} tools\n",
            )
            # Clear flags to prevent duplicate notifications
            all_params.pop("_strict_tool_use_enabled", None)
            all_params.pop("_strict_tool_count", None)
            all_params.pop("_strict_tool_names", None)

        # Remove any MCP tools from the tools list
        if "tools" in api_params:
            non_mcp_tools = []
            for tool in api_params.get("tools", []):
                # Check different formats for MCP tools
                if tool.get("type") == "function":
                    name = tool.get("function", {}).get("name") if "function" in tool else tool.get("name")
                    if name and name in self._mcp_function_names:
                        continue
                    if name and name in self._custom_tool_names:
                        continue
                elif tool.get("type") == "mcp":
                    continue
                non_mcp_tools.append(tool)
            if non_mcp_tools:
                api_params["tools"] = non_mcp_tools
            else:
                api_params.pop("tools", None)

        # Add custom tool schemas (they were filtered out above, now add them back)
        if self._custom_tool_names:
            custom_tool_schemas = self._get_custom_tools_schemas()
            if custom_tool_schemas:
                if "tools" not in api_params:
                    api_params["tools"] = []
                # Convert from OpenAI format to Claude format
                for schema in custom_tool_schemas:
                    if schema.get("type") == "function":
                        func = schema.get("function", {})
                        claude_tool = {
                            "name": func.get("name"),
                            "description": func.get("description", ""),
                            "input_schema": func.get(
                                "parameters",
                                {"type": "object", "properties": {}},
                            ),
                        }
                        api_params["tools"].append(claude_tool)
                logger.debug(
                    f"[Claude] Added {len(custom_tool_schemas)} custom tool schemas",
                )

        # Start API call timing
        model = api_params.get("model", "unknown")
        self.start_api_call_timing(model)

        # Wrap LLM API call with tracing for agent attribution
        with trace_llm_api_call(
            agent_id=agent_id or "unknown",
            provider="anthropic",
            model=model,
            operation="stream",
        ):
            # Create stream (handle betas) with circuit breaker protection
            try:

                async def _make_api_call():
                    if "betas" in api_params:
                        return await client.beta.messages.create(**api_params)
                    return await client.messages.create(**api_params)

                stream = await self.circuit_breaker.call_with_retry(
                    _make_api_call,
                    agent_id=agent_id,
                )
            except CircuitBreakerOpenError:
                self.end_api_call_timing(success=False, error="circuit_breaker_open")
                raise
            except Exception as e:
                self.end_api_call_timing(success=False, error=str(e))
                raise

        # Process stream chunks
        async for chunk in self._process_stream(stream, all_params, agent_id):
            yield chunk

    def _merge_parallel_tool_results(
        self,
        updated_messages: list[dict[str, Any]],
        all_per_call_messages: list[list[dict[str, Any]]],
    ) -> None:
        """Consolidate parallel tool results into a single user message for Claude API.

        Claude API has two strict requirements (documented):
          1. All tool_result blocks for a given assistant turn MUST be in ONE user message.
          2. That message MUST immediately follow the assistant message — no intervening
             messages of any kind are allowed between the assistant's tool_use blocks and
             the user's tool_result blocks.

        When tools run in parallel each tool writes to an isolated buffer, producing
        separate per-call user messages. Post-tool hook reminders (strategy='user_message')
        also land in those buffers as plain user messages.

        This override collects all tool_result blocks first, writes them as a single
        consolidated user message immediately after the assistant message, and only then
        appends any deferred non-tool-result messages (e.g. hook reminders).
        """
        tool_result_blocks: list[dict[str, Any]] = []
        deferred_messages: list[dict[str, Any]] = []  # Hook reminders, etc.

        for msgs in all_per_call_messages:
            for msg in msgs:
                if msg.get("role") == "user" and isinstance(msg.get("content"), list) and msg["content"] and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in msg["content"]):
                    tool_result_blocks.extend(msg["content"])
                else:
                    deferred_messages.append(msg)

        # Step 1: consolidated tool_result message IMMEDIATELY after the assistant.
        if tool_result_blocks:
            # Merge into an existing tool_result user message that already follows the
            # last assistant message (e.g. from a prior sequential step), or create one.
            existing_tr_idx = None
            for i in range(len(updated_messages) - 1, -1, -1):
                m = updated_messages[i]
                if m.get("role") == "assistant":
                    break
                if m.get("role") == "user" and isinstance(m.get("content"), list) and m["content"] and isinstance(m["content"][0], dict) and m["content"][0].get("type") == "tool_result":
                    existing_tr_idx = i
                    break

            if existing_tr_idx is not None:
                updated_messages[existing_tr_idx]["content"].extend(tool_result_blocks)
            else:
                updated_messages.append({"role": "user", "content": tool_result_blocks})

        # Step 2: deferred messages (hook reminders) go AFTER the tool_result message.
        updated_messages.extend(deferred_messages)

    def filter_enforcement_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        unknown_tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Filter out unknown tool calls from enforcement to avoid Claude API 400 errors.

        Claude requires every tool_result block to reference a tool_use block in the
        immediately preceding assistant message. Unknown tools (not registered as workflow,
        MCP, or custom) are silently dropped by the orchestrator and never reach the
        assistant message history. Sending a tool_result for such a call produces:
          "messages.N: unexpected `tool_use_id` found in `tool_result` blocks"

        Use object identity (id()) to match — the same dict objects that were appended to
        the orchestrator's tool_calls list are passed here unchanged.
        """
        if not unknown_tool_calls:
            return tool_calls
        unknown_ids = {id(tc) for tc in unknown_tool_calls}
        return [tc for tc in tool_calls if id(tc) not in unknown_ids]

    def _append_tool_result_message(
        self,
        updated_messages: list[dict[str, Any]],
        call: dict[str, Any],
        result: Any,
        tool_type: str,
    ) -> None:
        """Append tool result to messages in Claude format.

        Args:
            updated_messages: Message list to append to
            call: Tool call dictionary with call_id, name, arguments
            result: Tool execution result
            tool_type: "custom" or "mcp"

        Note:
            Claude uses tool_result format with tool_use_id.
            All tool_result blocks for a given assistant turn MUST be in a SINGLE user message immediately after the assistant message with tool_use blocks.
        """
        # Extract text from result - handle MCP CallToolResult objects properly
        if hasattr(result, "content") and not isinstance(result, (dict, str)):
            # MCP CallToolResult - extract text from content list
            extracted = self._extract_text_from_content(result.content)
            result_text = extracted if extracted is not None else str(result)
        else:
            result_text = getattr(result, "text", None) or str(result)

        tool_result_block = {
            "type": "tool_result",
            "tool_use_id": call.get("call_id", "") or call.get("id", ""),
            "content": result_text,
        }

        tool_result_msg_idx = None
        for i in range(len(updated_messages) - 1, -1, -1):
            msg = updated_messages[i]

            if msg.get("role") == "assistant":
                break
            # Found a user message with tool_result content
            if msg.get("role") == "user" and isinstance(msg.get("content"), list) and msg["content"] and isinstance(msg["content"][0], dict) and msg["content"][0].get("type") == "tool_result":
                tool_result_msg_idx = i
                break

        if tool_result_msg_idx is not None:
            # Merge into existing tool_result user message
            updated_messages[tool_result_msg_idx]["content"].append(tool_result_block)
            return

        # Otherwise create a new user message with this tool_result
        tool_result_msg = {
            "role": "user",
            "content": [tool_result_block],
        }
        updated_messages.append(tool_result_msg)

        # Track in streaming buffer for compression recovery
        tool_name = call.get("name", "unknown")
        self._append_tool_to_buffer(tool_name, result_text)

    def _append_tool_error_message(
        self,
        updated_messages: list[dict[str, Any]],
        call: dict[str, Any],
        error_msg: str,
        tool_type: str,
    ) -> None:
        """Append tool error to messages in Claude format.

        Args:
            updated_messages: Message list to append to
            call: Tool call dictionary with call_id, name, arguments
            error_msg: Error message string
            tool_type: "custom" or "mcp"

        Note:
            Claude uses tool_result format with tool_use_id for errors too.
        """
        error_result_block = {
            "type": "tool_result",
            "tool_use_id": call.get("call_id", "") or call.get("id", ""),
            "content": error_msg,
            "is_error": True,
        }

        tool_result_msg_idx = None
        for i in range(len(updated_messages) - 1, -1, -1):
            msg = updated_messages[i]
            if msg.get("role") == "assistant":
                break
            # Found a user message with tool_result content
            if msg.get("role") == "user" and isinstance(msg.get("content"), list) and msg["content"] and isinstance(msg["content"][0], dict) and msg["content"][0].get("type") == "tool_result":
                tool_result_msg_idx = i
                break

        if tool_result_msg_idx is not None:
            # Merge into existing tool_result user message
            updated_messages[tool_result_msg_idx]["content"].append(error_result_block)
            return

        # Otherwise create a new user message with this tool_result
        error_result_msg = {
            "role": "user",
            "content": [error_result_block],
        }
        updated_messages.append(error_result_msg)

        # Track in streaming buffer for compression recovery
        tool_name = call.get("name", "unknown")
        self._append_tool_to_buffer(tool_name, error_msg, is_error=True)

    async def _execute_custom_tool(
        self,
        call: dict[str, Any],
    ) -> AsyncGenerator[CustomToolChunk]:
        """Execute custom tool with streaming support - async generator for base class.

        This method is called by _execute_tool_with_logging and yields CustomToolChunk
        objects for intermediate streaming output. The base class detects the async
        generator and streams intermediate results to users in real-time.

        Args:
            call: Tool call dictionary with name and arguments

        Yields:
            CustomToolChunk objects with streaming data

        Note:
            - Intermediate chunks (completed=False) are streamed to users in real-time
            - Final chunk (completed=True) contains the accumulated result for message history
            - The base class automatically handles extracting and displaying intermediate chunks
        """
        async for chunk in self.stream_custom_tool_execution(call):
            yield chunk

    async def _stream_with_custom_and_mcp_tools(
        self,
        current_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        client,
        **kwargs,
    ) -> AsyncGenerator[StreamChunk]:
        """Recursively stream responses, executing MCP and custom tool function calls when detected."""

        # Build API params for this iteration
        all_params = {**self.config, **kwargs}

        # Track if this is the first iteration
        is_first_iteration = not kwargs.get("_programmatic_flow_logged", False)
        agent_id = kwargs.get("agent_id", None)

        # Validate advanced features compatibility with model
        if is_first_iteration:
            self._validate_advanced_features(all_params)

            # Notify frontend about programmatic flow status (only on first iteration)
            if all_params.get("enable_programmatic_flow"):
                log_stream_chunk(
                    "backend.claude",
                    "programmatic_flow",
                    "Programmatic tool calling enabled - tools can be invoked from code execution",
                    agent_id,
                )
                yield StreamChunk(
                    type="content",
                    content="\n🔄 [Programmatic Flow] Enabled - Claude can call tools from code execution\n",
                )
                # Mark that we've logged programmatic flow for recursive calls
                kwargs["_programmatic_flow_logged"] = True

            # Notify frontend about tool search status
            if all_params.get("enable_tool_search") and not kwargs.get(
                "_tool_search_logged",
                False,
            ):
                variant = all_params.get("tool_search_variant", "regex")
                log_stream_chunk(
                    "backend.claude",
                    "tool_search",
                    f"Tool search enabled (variant: {variant}) - deferred tools discovered on-demand",
                    agent_id,
                )
                yield StreamChunk(
                    type="content",
                    content=f"\n🔍 [Tool Search] Enabled ({variant}) - Claude can discover deferred tools on-demand\n",
                )
                # Mark that we've logged tool search for recursive calls
                kwargs["_tool_search_logged"] = True

        # Check if we need to upload files via Files API
        if all_params.get("_has_file_search_files"):
            logger.info("Processing Files API uploads in MCP mode...")
            agent_id = kwargs.get("agent_id")
            current_messages = await self._upload_files_via_files_api(
                current_messages,
                client,
                agent_id,
            )
            all_params["_has_files_api_files"] = True
            all_params.pop("_has_file_search_files", None)

        self._ensure_no_pending_upload_markers(current_messages)

        api_params = await self.api_params_handler.build_api_params(
            current_messages,
            tools,
            all_params,
        )

        if all_params.get("_strict_tool_use_enabled") and not kwargs.get(
            "_strict_tool_use_logged",
            False,
        ):
            strict_count = all_params.get("_strict_tool_count", 0)
            strict_names = all_params.get("_strict_tool_names", [])
            log_stream_chunk(
                "backend.claude",
                "strict_tool_use",
                f"Strict tool use enabled for {strict_count} tools: {strict_names}",
                agent_id,
            )
            yield StreamChunk(
                type="content",
                content=f"\n🔒 [Strict Tool Use] Enabled for {strict_count} tools \n",
            )
            kwargs["_strict_tool_use_logged"] = True

        # Start API call timing
        model = api_params.get("model", "unknown")
        self.start_api_call_timing(model)

        # Wrap LLM API call with tracing for agent attribution
        with trace_llm_api_call(
            agent_id=agent_id or "unknown",
            provider="anthropic",
            model=model,
            operation="stream",
        ):
            # Create stream (handle code execution beta) with circuit breaker
            try:

                async def _make_api_call_ce():
                    if "betas" in api_params:
                        return await client.beta.messages.create(**api_params)
                    return await client.messages.create(**api_params)

                stream = await self.circuit_breaker.call_with_retry(
                    _make_api_call_ce,
                    agent_id=agent_id,
                )
            except CircuitBreakerOpenError:
                self.end_api_call_timing(success=False, error="circuit_breaker_open")
                raise
            except Exception as e:
                self.end_api_call_timing(success=False, error=str(e))
                raise

        content = ""
        current_tool_uses: dict[str, dict[str, Any]] = {}
        mcp_tool_calls: list[dict[str, Any]] = []
        custom_tool_calls: list[dict[str, Any]] = []
        response_completed = False

        # Track usage from message events (Anthropic splits input/output across events)
        _input_tokens = 0
        _cache_creation_input_tokens = 0
        _cache_read_input_tokens = 0

        async for event in stream:
            try:
                if event.type == "message_start":
                    # Extract input token counts from message_start event
                    if hasattr(event, "message") and hasattr(event.message, "usage"):
                        _input_tokens = getattr(event.message.usage, "input_tokens", 0) or 0
                        _cache_creation_input_tokens = (
                            getattr(
                                event.message.usage,
                                "cache_creation_input_tokens",
                                0,
                            )
                            or 0
                        )
                        _cache_read_input_tokens = getattr(event.message.usage, "cache_read_input_tokens", 0) or 0
                    continue
                elif event.type == "content_block_start":
                    if hasattr(event, "content_block"):
                        if event.content_block.type == "tool_use":
                            tool_id = event.content_block.id
                            tool_name = event.content_block.name
                            caller = getattr(event.content_block, "caller", None)
                            is_programmatic = all_params.get("enable_programmatic_flow", False) and caller is not None and isinstance(caller, dict) and caller.get("type") not in (None, "direct")

                            initial_input = ""
                            if hasattr(event.content_block, "input") and event.content_block.input:
                                if isinstance(event.content_block.input, dict):
                                    initial_input = json.dumps(
                                        event.content_block.input,
                                    )
                                else:
                                    initial_input = str(event.content_block.input)
                                if is_programmatic:
                                    logger.debug(
                                        f"[Programmatic Flow] Tool '{tool_name}' has direct input: {initial_input}",
                                    )

                            current_tool_uses[tool_id] = {
                                "id": tool_id,
                                "name": tool_name,
                                "input": initial_input,
                                "index": getattr(event, "index", None),
                                "caller": caller,
                                "is_programmatic": is_programmatic,
                            }
                            if is_programmatic:
                                logger.info(
                                    f"[Programmatic Flow] Tool '{tool_name}' called from code execution (caller: {caller})",
                                )
                                yield StreamChunk(
                                    type="content",
                                    content=f"\n🔄 [Programmatic] Tool '{tool_name}' called from code execution\n",
                                )
                        elif event.content_block.type == "server_tool_use":
                            tool_id = event.content_block.id
                            tool_name = event.content_block.name
                            current_tool_uses[tool_id] = {
                                "id": tool_id,
                                "name": tool_name,
                                "input": "",
                                "index": getattr(event, "index", None),
                                "server_side": True,
                            }
                            if tool_name == "code_execution":
                                yield StreamChunk(
                                    type="content",
                                    content="\n💻 [Code Execution] Starting...\n",
                                )
                            elif tool_name == "web_search":
                                yield StreamChunk(
                                    type="content",
                                    content="\n🔍 [Web Search] Starting search...\n",
                                )
                            elif tool_name.startswith("tool_search_tool_"):
                                variant = "regex" if "regex" in tool_name else "bm25"
                                logger.debug(
                                    f"[Tool Search] Searching for tools (variant: {variant})",
                                )
                                yield StreamChunk(
                                    type="content",
                                    content=f"\n🔎 [Tool Search] Searching for tools ({variant})...\n",
                                )
                        elif event.content_block.type == "code_execution_tool_result":
                            result_block = event.content_block
                            result_parts = []
                            if hasattr(result_block, "stdout") and result_block.stdout:
                                result_parts.append(
                                    f"Output: {result_block.stdout.strip()}",
                                )
                            if hasattr(result_block, "stderr") and result_block.stderr:
                                result_parts.append(
                                    f"Error: {result_block.stderr.strip()}",
                                )
                            if hasattr(result_block, "return_code") and result_block.return_code != 0:
                                result_parts.append(
                                    f"Exit code: {result_block.return_code}",
                                )
                            if result_parts:
                                result_text = f"\n💻 [Code Execution Result]\n{chr(10).join(result_parts)}\n"
                                yield StreamChunk(type="content", content=result_text)
                elif event.type == "content_block_delta":
                    if hasattr(event, "delta"):
                        if event.delta.type == "text_delta":
                            self.record_first_token()  # Record TTFT on first content
                            text_chunk = event.delta.text
                            content += text_chunk
                            self._append_to_streaming_buffer(text_chunk)
                            log_backend_agent_message(
                                agent_id or "default",
                                "RECV",
                                {"content": text_chunk},
                                backend_name="claude",
                            )
                            log_stream_chunk(
                                "backend.claude",
                                "content",
                                text_chunk,
                                agent_id,
                            )
                            yield StreamChunk(type="content", content=text_chunk)
                        elif event.delta.type == "thinking_delta":
                            # Handle extended thinking content from Claude models
                            thinking_chunk = event.delta.thinking
                            self._append_reasoning_to_buffer(thinking_chunk)
                            log_stream_chunk(
                                "backend.claude",
                                "reasoning",
                                thinking_chunk,
                                agent_id,
                            )
                            yield StreamChunk(type="reasoning", content=thinking_chunk)
                        elif event.delta.type == "input_json_delta":
                            if hasattr(event, "index"):
                                for tool_id, tool_data in current_tool_uses.items():
                                    if tool_data.get("index") == event.index:
                                        partial_json = getattr(
                                            event.delta,
                                            "partial_json",
                                            "",
                                        )
                                        tool_data["input"] += partial_json
                                        break
                elif event.type == "content_block_stop":
                    if hasattr(event, "index"):
                        for tool_id, tool_data in current_tool_uses.items():
                            if tool_data.get("index") == event.index and tool_data.get(
                                "server_side",
                            ):
                                tool_name = tool_data.get("name", "")
                                tool_input = tool_data.get("input", "")
                                try:
                                    parsed_input = json.loads(tool_input) if tool_input else {}
                                except json.JSONDecodeError:
                                    parsed_input = {"raw_input": tool_input}
                                if tool_name == "code_execution":
                                    code = parsed_input.get("code", "")
                                    if code:
                                        yield StreamChunk(
                                            type="content",
                                            content=f"💻 [Code] {code}\n",
                                        )
                                    yield StreamChunk(
                                        type="content",
                                        content="✅ [Code Execution] Completed\n",
                                    )
                                elif tool_name == "web_search":
                                    query = parsed_input.get("query", "")
                                    if query:
                                        yield StreamChunk(
                                            type="content",
                                            content=f"🔍 [Query] '{query}'\n",
                                        )
                                    yield StreamChunk(
                                        type="content",
                                        content="✅ [Web Search] Completed\n",
                                    )
                                elif tool_name.startswith("tool_search_tool_"):
                                    query = parsed_input.get("query", "")
                                    if query:
                                        yield StreamChunk(
                                            type="content",
                                            content=f"🔎 [Search Query] '{query}'\n",
                                        )
                                    yield StreamChunk(
                                        type="content",
                                        content="✅ [Tool Search] Completed - tools discovered\n",
                                    )
                                tool_data["processed"] = True
                                break
                elif event.type == "message_delta":
                    # Extract output tokens and update usage tracking
                    if hasattr(event, "usage"):
                        output_tokens = getattr(event.usage, "output_tokens", 0) or 0
                        # Combine with input tokens captured from message_start
                        combined_usage = {
                            "input_tokens": _input_tokens,
                            "output_tokens": output_tokens,
                            "cache_creation_input_tokens": _cache_creation_input_tokens,
                            "cache_read_input_tokens": _cache_read_input_tokens,
                        }
                        self._update_token_usage_from_api_response(
                            combined_usage,
                            all_params.get("model", "claude-sonnet-4-20250514"),
                        )
                elif event.type == "message_stop":
                    captured_calls = []
                    tool_use_by_name: dict[str, dict[str, Any]] = {}

                    if current_tool_uses:
                        for tool_use in current_tool_uses.values():
                            tool_name = tool_use.get("name", "")
                            is_server_side = tool_use.get("server_side", False)
                            if is_server_side:
                                continue
                            # Parse accumulated JSON input for tool
                            tool_input = tool_use.get("input", "")
                            try:
                                parsed_input = json.loads(tool_input) if tool_input else {}
                            except json.JSONDecodeError:
                                parsed_input = {"raw_input": tool_input}

                            captured_calls.append(
                                {
                                    "name": tool_name,
                                    "arguments": json.dumps(parsed_input) if isinstance(parsed_input, dict) else str(parsed_input),
                                    "call_id": tool_use["id"],
                                },
                            )

                            # Store tool_use info for reconstruction
                            tool_use_by_name[tool_use["id"]] = {
                                "id": tool_use["id"],
                                "parsed_input": parsed_input,
                            }

                    # Use helper to categorize tool calls
                    if captured_calls:
                        categorized_mcp, categorized_custom, categorized_provider = self._categorize_tool_calls(captured_calls)

                        # Reconstruct Claude-specific format for each category
                        for call in categorized_mcp:
                            tool_info = tool_use_by_name[call["call_id"]]
                            mcp_tool_calls.append(
                                {
                                    "id": tool_info["id"],
                                    "type": "function",
                                    "function": {
                                        "name": call["name"],
                                        "arguments": tool_info["parsed_input"],
                                    },
                                },
                            )

                        for call in categorized_custom:
                            tool_info = tool_use_by_name[call["call_id"]]
                            custom_tool_calls.append(
                                {
                                    "id": tool_info["id"],
                                    "type": "function",
                                    "function": {
                                        "name": call["name"],
                                        "arguments": tool_info["parsed_input"],
                                    },
                                },
                            )

                        # Build non-MCP/non-custom tool calls (including workflow tools)
                        non_mcp_non_custom_tool_calls = []
                        for call in categorized_provider:
                            tool_info = tool_use_by_name[call["call_id"]]
                            non_mcp_non_custom_tool_calls.append(
                                {
                                    "id": tool_info["id"],
                                    "type": "function",
                                    "function": {
                                        "name": call["name"],
                                        "arguments": tool_info["parsed_input"],
                                    },
                                },
                            )
                    else:
                        non_mcp_non_custom_tool_calls = []

                    # Emit non-MCP/non-custom tool calls for the caller to execute
                    if non_mcp_non_custom_tool_calls:
                        log_stream_chunk(
                            "backend.claude",
                            "tool_calls",
                            non_mcp_non_custom_tool_calls,
                            agent_id,
                        )
                        self._append_tool_call_to_buffer(non_mcp_non_custom_tool_calls)
                        yield StreamChunk(
                            type="tool_calls",
                            tool_calls=non_mcp_non_custom_tool_calls,
                        )
                    self.end_api_call_timing(success=True)
                    response_completed = True
                    break
            except Exception as event_error:
                error_msg = f"Event processing error: {event_error}"
                log_stream_chunk("backend.claude", "error", error_msg, agent_id)
                yield StreamChunk(type="error", error=error_msg)
                continue

        # If we captured MCP or custom tool calls, execute them and recurse
        if response_completed and (mcp_tool_calls or custom_tool_calls):
            # Circuit breaker pre-execution check using base class method
            if not await self._check_circuit_breaker_before_execution():
                yield StreamChunk(
                    type="mcp_status",
                    status="mcp_blocked",
                    content="⚠️ [MCP] All servers blocked by circuit breaker",
                    source="circuit_breaker",
                )
                yield StreamChunk(type="done")
                return

            updated_messages = current_messages.copy()

            # Build assistant message with tool_use blocks for all MCP and custom tool calls
            assistant_content = []
            if content:  # Add text content if any
                assistant_content.append({"type": "text", "text": content})

            # Add tool_use blocks for MCP tools
            for tool_call in mcp_tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args = tool_call["function"]["arguments"]
                tool_id = tool_call["id"]

                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_args,
                    },
                )

            # Add tool_use blocks for custom tools
            for tool_call in custom_tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args = tool_call["function"]["arguments"]
                tool_id = tool_call["id"]

                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_args,
                    },
                )

            # Append the assistant message with tool uses
            updated_messages.append({"role": "assistant", "content": assistant_content})

            # Configuration for custom tool execution
            CUSTOM_TOOL_CONFIG = ToolExecutionConfig(
                tool_type="custom",
                chunk_type="custom_tool_status",
                emoji_prefix="🔧 [Custom Tool]",
                success_emoji="✅ [Custom Tool]",
                error_emoji="❌ [Custom Tool Error]",
                source_prefix="custom_",
                status_called="custom_tool_called",
                status_response="custom_tool_response",
                status_error="custom_tool_error",
                execution_callback=self._execute_custom_tool,
            )

            # Configuration for MCP tool execution
            MCP_TOOL_CONFIG = ToolExecutionConfig(
                tool_type="mcp",
                chunk_type="mcp_status",
                emoji_prefix="🔧 [MCP Tool]",
                success_emoji="✅ [MCP Tool]",
                error_emoji="❌ [MCP Tool Error]",
                source_prefix="mcp_",
                status_called="mcp_tool_called",
                status_response="mcp_tool_response",
                status_error="mcp_tool_error",
                execution_callback=self._execute_mcp_function_with_retry,
            )

            def normalize_tool_call(tool_call: dict[str, Any]) -> dict[str, Any]:
                """Convert Claude tool call format to unified format."""
                return {
                    "name": tool_call["function"]["name"],
                    "arguments": json.dumps(tool_call["function"]["arguments"]) if isinstance(tool_call["function"].get("arguments"), (dict, list)) else tool_call["function"].get("arguments", "{}"),
                    "call_id": tool_call["id"],  # Normalize "id" to "call_id"
                }

            processed_call_ids: set[str] = set()

            normalized_custom_calls = [normalize_tool_call(tc) for tc in custom_tool_calls]
            normalized_mcp_calls = [normalize_tool_call(tc) for tc in mcp_tool_calls]

            def chunk_adapter(chunk: StreamChunk) -> StreamChunk:
                return chunk

            nlip_available = self._nlip_enabled and self._nlip_router

            pending_custom_calls: list[dict[str, Any]] = []
            for call in normalized_custom_calls:
                handled_via_nlip = False
                if nlip_available:
                    logger.info(
                        f"[NLIP] Using NLIP routing for custom tool {call['name']}",
                    )
                    try:
                        async for chunk in self._stream_tool_execution_via_nlip(
                            call,
                            CUSTOM_TOOL_CONFIG,
                            updated_messages,
                            processed_call_ids,
                        ):
                            yield chunk_adapter(chunk)
                        handled_via_nlip = True
                    except Exception as exc:
                        logger.warning(
                            f"[NLIP] Routing failed for {call['name']}: {exc}. Falling back to direct execution.",
                        )
                        async for chunk in self._execute_tool_with_logging(
                            call,
                            CUSTOM_TOOL_CONFIG,
                            updated_messages,
                            processed_call_ids,
                        ):
                            yield chunk_adapter(chunk)
                        handled_via_nlip = True

                if not handled_via_nlip:
                    reason = "disabled" if not self._nlip_enabled else "router unavailable"
                    logger.info(
                        f"[Custom Tool] Direct execution for {call['name']} (NLIP {reason})",
                    )
                    pending_custom_calls.append(call)

            pending_mcp_calls: list[dict[str, Any]] = []
            for call in normalized_mcp_calls:
                handled_via_nlip = False
                if nlip_available:
                    logger.info(
                        f"[NLIP] Using NLIP routing for MCP tool {call['name']}",
                    )
                    try:
                        async for chunk in self._stream_tool_execution_via_nlip(
                            call,
                            MCP_TOOL_CONFIG,
                            updated_messages,
                            processed_call_ids,
                        ):
                            yield chunk_adapter(chunk)
                        handled_via_nlip = True
                    except Exception as exc:
                        logger.warning(
                            f"[NLIP] Routing failed for {call['name']}: {exc}. Falling back to direct execution.",
                        )
                        async for chunk in self._execute_tool_with_logging(
                            call,
                            MCP_TOOL_CONFIG,
                            updated_messages,
                            processed_call_ids,
                        ):
                            yield chunk_adapter(chunk)
                        handled_via_nlip = True

                if not handled_via_nlip:
                    reason = "disabled" if not self._nlip_enabled else "router unavailable"
                    logger.info(
                        f"[MCP Tool] Direct execution for {call['name']} (NLIP {reason})",
                    )
                    pending_mcp_calls.append(call)

            remaining_calls = pending_custom_calls + pending_mcp_calls

            if remaining_calls:
                all_params_local = {**self.config, **kwargs}

                def tool_config_for_call(call: dict[str, Any]) -> ToolExecutionConfig:
                    tool_name = call.get("name", "")
                    return CUSTOM_TOOL_CONFIG if tool_name in (self._custom_tool_names or set()) else MCP_TOOL_CONFIG

                async for adapted_chunk in self._execute_tool_calls(
                    all_calls=remaining_calls,
                    tool_config_for_call=tool_config_for_call,
                    all_params=all_params_local,
                    updated_messages=updated_messages,
                    processed_call_ids=processed_call_ids,
                    log_prefix="[Claude]",
                    chunk_adapter=chunk_adapter,
                ):
                    yield adapted_chunk

            updated_messages = self._trim_message_history(updated_messages)

            async for chunk in self._stream_with_custom_and_mcp_tools(
                updated_messages,
                tools,
                client,
                **kwargs,
            ):
                yield chunk
            return
        else:
            # No MCP function calls; finalize this turn
            # Ensure termination with a done chunk when no further tool calls
            complete_message = {
                "role": "assistant",
                "content": content.strip(),
            }
            log_stream_chunk(
                "backend.claude",
                "complete_message",
                complete_message,
                agent_id,
            )
            yield StreamChunk(
                type="complete_message",
                complete_message=complete_message,
            )
            yield StreamChunk(
                type="mcp_status",
                status="mcp_session_complete",
                content="✅ [MCP] Session completed",
                source="mcp_session",
            )
            yield StreamChunk(type="done")
            return

    async def _process_stream(
        self,
        stream,
        all_params: dict[str, Any],
        agent_id: str | None,
    ) -> AsyncGenerator[StreamChunk]:
        """Process stream events and yield StreamChunks."""
        content_local = ""
        current_tool_uses_local: dict[str, dict[str, Any]] = {}

        # Track usage from message events (Anthropic splits input/output across events)
        _input_tokens = 0
        _cache_creation_input_tokens = 0
        _cache_read_input_tokens = 0

        async for chunk in stream:
            try:
                if chunk.type == "message_start":
                    # Extract input token counts from message_start event
                    if hasattr(chunk, "message") and hasattr(chunk.message, "usage"):
                        _input_tokens = getattr(chunk.message.usage, "input_tokens", 0) or 0
                        _cache_creation_input_tokens = (
                            getattr(
                                chunk.message.usage,
                                "cache_creation_input_tokens",
                                0,
                            )
                            or 0
                        )
                        _cache_read_input_tokens = getattr(chunk.message.usage, "cache_read_input_tokens", 0) or 0
                    continue
                elif chunk.type == "content_block_start":
                    if hasattr(chunk, "content_block"):
                        if chunk.content_block.type == "tool_use":
                            tool_id = chunk.content_block.id
                            tool_name = chunk.content_block.name
                            caller = getattr(chunk.content_block, "caller", None)
                            is_programmatic = all_params.get("enable_programmatic_flow", False) and caller is not None and isinstance(caller, dict) and caller.get("type") not in (None, "direct")

                            initial_input = ""
                            if hasattr(chunk.content_block, "input") and chunk.content_block.input:
                                if isinstance(chunk.content_block.input, dict):
                                    initial_input = json.dumps(
                                        chunk.content_block.input,
                                    )
                                else:
                                    initial_input = str(chunk.content_block.input)
                                if is_programmatic:
                                    logger.debug(
                                        f"[Programmatic Flow] Tool '{tool_name}' has direct input: {initial_input}",
                                    )

                            current_tool_uses_local[tool_id] = {
                                "id": tool_id,
                                "name": tool_name,
                                "input": initial_input,
                                "index": getattr(chunk, "index", None),
                                "caller": caller,
                                "is_programmatic": is_programmatic,
                            }
                            if is_programmatic:
                                logger.info(
                                    f"[Programmatic Flow] Tool '{tool_name}' called from code execution (caller: {caller})",
                                )
                                yield StreamChunk(
                                    type="content",
                                    content=f"\n🔄 [Programmatic] Tool '{tool_name}' called from code execution\n",
                                )
                        elif chunk.content_block.type == "server_tool_use":
                            tool_id = chunk.content_block.id
                            tool_name = chunk.content_block.name
                            current_tool_uses_local[tool_id] = {
                                "id": tool_id,
                                "name": tool_name,
                                "input": "",
                                "index": getattr(chunk, "index", None),
                                "server_side": True,
                            }
                            if tool_name == "code_execution":
                                yield StreamChunk(
                                    type="content",
                                    content="\n💻 [Code Execution] Starting...\n",
                                )
                            elif tool_name == "web_search":
                                yield StreamChunk(
                                    type="content",
                                    content="\n🔍 [Web Search] Starting search...\n",
                                )
                            elif tool_name.startswith("tool_search_tool_"):
                                variant = "regex" if "regex" in tool_name else "bm25"
                                logger.debug(
                                    f"[Tool Search] Searching for tools (variant: {variant})",
                                )
                                yield StreamChunk(
                                    type="content",
                                    content=f"\n🔎 [Tool Search] Searching for tools ({variant})...\n",
                                )
                        elif chunk.content_block.type == "code_execution_tool_result":
                            result_block = chunk.content_block
                            result_parts = []
                            if hasattr(result_block, "stdout") and result_block.stdout:
                                result_parts.append(
                                    f"Output: {result_block.stdout.strip()}",
                                )
                            if hasattr(result_block, "stderr") and result_block.stderr:
                                result_parts.append(
                                    f"Error: {result_block.stderr.strip()}",
                                )
                            if hasattr(result_block, "return_code") and result_block.return_code != 0:
                                result_parts.append(
                                    f"Exit code: {result_block.return_code}",
                                )
                            if result_parts:
                                result_text = f"\n💻 [Code Execution Result]\n{chr(10).join(result_parts)}\n"
                                yield StreamChunk(
                                    type="content",
                                    content=result_text,
                                )
                elif chunk.type == "content_block_delta":
                    if hasattr(chunk, "delta"):
                        if chunk.delta.type == "text_delta":
                            self.record_first_token()  # Record TTFT on first content
                            text_chunk = chunk.delta.text
                            content_local += text_chunk
                            self._append_to_streaming_buffer(text_chunk)
                            log_backend_agent_message(
                                agent_id or "default",
                                "RECV",
                                {"content": text_chunk},
                                backend_name="claude",
                            )
                            log_stream_chunk(
                                "backend.claude",
                                "content",
                                text_chunk,
                                agent_id,
                            )
                            yield StreamChunk(type="content", content=text_chunk)
                        elif chunk.delta.type == "thinking_delta":
                            # Handle extended thinking content from Claude models
                            thinking_chunk = chunk.delta.thinking
                            self._append_reasoning_to_buffer(thinking_chunk)
                            log_stream_chunk(
                                "backend.claude",
                                "reasoning",
                                thinking_chunk,
                                agent_id,
                            )
                            yield StreamChunk(type="reasoning", content=thinking_chunk)
                        elif chunk.delta.type == "input_json_delta":
                            if hasattr(chunk, "index"):
                                for (
                                    tool_id,
                                    tool_data,
                                ) in current_tool_uses_local.items():
                                    if tool_data.get("index") == chunk.index:
                                        partial_json = getattr(
                                            chunk.delta,
                                            "partial_json",
                                            "",
                                        )
                                        tool_data["input"] += partial_json
                                        break
                elif chunk.type == "content_block_stop":
                    if hasattr(chunk, "index"):
                        for (
                            tool_id,
                            tool_data,
                        ) in current_tool_uses_local.items():
                            if tool_data.get("index") == chunk.index and tool_data.get(
                                "server_side",
                            ):
                                tool_name = tool_data.get("name", "")
                                tool_input = tool_data.get("input", "")
                                try:
                                    parsed_input = json.loads(tool_input) if tool_input else {}
                                except json.JSONDecodeError:
                                    parsed_input = {"raw_input": tool_input}
                                if tool_name == "code_execution":
                                    code = parsed_input.get("code", "")
                                    if code:
                                        yield StreamChunk(
                                            type="content",
                                            content=f"💻 [Code] {code}\n",
                                        )
                                    yield StreamChunk(
                                        type="content",
                                        content="✅ [Code Execution] Completed\n",
                                    )
                                elif tool_name == "web_search":
                                    query = parsed_input.get("query", "")
                                    if query:
                                        yield StreamChunk(
                                            type="content",
                                            content=f"🔍 [Query] '{query}'\n",
                                        )
                                    yield StreamChunk(
                                        type="content",
                                        content="✅ [Web Search] Completed\n",
                                    )
                                elif tool_name.startswith("tool_search_tool_"):
                                    query = parsed_input.get("query", "")
                                    if query:
                                        yield StreamChunk(
                                            type="content",
                                            content=f"🔎 [Search Query] '{query}'\n",
                                        )
                                    yield StreamChunk(
                                        type="content",
                                        content="✅ [Tool Search] Completed - tools discovered\n",
                                    )
                                tool_data["processed"] = True
                                break
                elif chunk.type == "message_delta":
                    # Extract output tokens and update usage tracking
                    if hasattr(chunk, "usage"):
                        output_tokens = getattr(chunk.usage, "output_tokens", 0) or 0
                        # Combine with input tokens captured from message_start
                        combined_usage = {
                            "input_tokens": _input_tokens,
                            "output_tokens": output_tokens,
                            "cache_creation_input_tokens": _cache_creation_input_tokens,
                            "cache_read_input_tokens": _cache_read_input_tokens,
                        }
                        self._update_token_usage_from_api_response(
                            combined_usage,
                            all_params.get("model", "claude-sonnet-4-20250514"),
                        )
                elif chunk.type == "message_stop":
                    # Build final response and yield tool_calls for user-defined non-MCP tools
                    user_tool_calls = []
                    for tool_use in current_tool_uses_local.values():
                        tool_name = tool_use.get("name", "")
                        is_server_side = tool_use.get("server_side", False)
                        if not is_server_side and tool_name not in [
                            "web_search",
                            "code_execution",
                        ]:
                            tool_input = tool_use.get("input", "")
                            try:
                                parsed_input = json.loads(tool_input) if tool_input else {}
                            except json.JSONDecodeError:
                                parsed_input = {"raw_input": tool_input}
                            user_tool_calls.append(
                                {
                                    "id": tool_use["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": parsed_input,
                                    },
                                },
                            )

                    if user_tool_calls:
                        log_stream_chunk(
                            "backend.claude",
                            "tool_calls",
                            user_tool_calls,
                            agent_id,
                        )
                        yield StreamChunk(
                            type="tool_calls",
                            tool_calls=user_tool_calls,
                        )

                    complete_message = {
                        "role": "assistant",
                        "content": content_local.strip(),
                    }
                    if user_tool_calls:
                        complete_message["tool_calls"] = user_tool_calls
                    log_stream_chunk(
                        "backend.claude",
                        "complete_message",
                        complete_message,
                        agent_id,
                    )
                    yield StreamChunk(
                        type="complete_message",
                        complete_message=complete_message,
                    )

                    # Track usage for pricing
                    if all_params.get("enable_web_search", False):
                        self.search_count += 1
                    if all_params.get("enable_code_execution", False):
                        self.code_session_hours += 0.083

                    self.end_api_call_timing(success=True)
                    log_stream_chunk("backend.claude", "done", None, agent_id)
                    yield StreamChunk(type="done")
                    return
            except Exception as event_error:
                error_msg = f"Event processing error: {event_error}"
                log_stream_chunk("backend.claude", "error", error_msg, agent_id)
                yield StreamChunk(type="error", error=error_msg)
                continue

    async def _handle_mcp_error_and_fallback(
        self,
        error: Exception,
        api_params: dict[str, Any],
        provider_tools: list[dict[str, Any]],
        stream_func: Callable[[dict[str, Any]], AsyncGenerator[StreamChunk]],
    ) -> AsyncGenerator[StreamChunk]:
        """Handle MCP errors with user-friendly messaging and fallback to non-MCP tools."""

        async with self._stats_lock:
            self._mcp_tool_failures += 1
            call_index_snapshot = self._mcp_tool_calls_count

        if MCPErrorHandler:
            log_type, user_message, _ = MCPErrorHandler.get_error_details(error)  # type: ignore[assignment]
        else:
            log_type, user_message = "mcp_error", "[MCP] Error occurred"

        logger.warning(
            f"MCP tool call #{call_index_snapshot} failed - {log_type}: {error}",
        )

        yield StreamChunk(
            type="content",
            content=f"\n⚠️  {user_message} ({error}); continuing without MCP tools\n",
        )

        fallback_params = dict(api_params)

        if "tools" in fallback_params and self._mcp_functions:
            mcp_names = set(self._mcp_functions.keys())
            non_mcp_tools = []
            for tool in fallback_params["tools"]:
                name = tool.get("name")
                if name in mcp_names:
                    continue
                non_mcp_tools.append(tool)
            fallback_params["tools"] = non_mcp_tools

        # Add back provider tools if they were present
        if provider_tools:
            if "tools" not in fallback_params:
                fallback_params["tools"] = []
            fallback_params["tools"].extend(provider_tools)

        async for chunk in stream_func(fallback_params):
            yield chunk

    async def _execute_mcp_function_with_retry(
        self,
        function_name: str,
        arguments_json: str,
        max_retries: int = 3,
    ) -> tuple[str, Any]:
        """Execute MCP function with Claude-specific formatting."""
        # Use parent class method which returns tuple
        result_str, result_obj = await super()._execute_mcp_function_with_retry(
            function_name,
            arguments_json,
            max_retries,
        )

        if result_str.startswith("Error:"):
            return (result_str, {"error": result_str})
        return (result_str, result_obj)

    def create_tool_result_message(
        self,
        tool_call: dict[str, Any],
        result_content: str,
    ) -> dict[str, Any]:
        """Create tool result message in Claude's expected format."""
        tool_call_id = self.extract_tool_call_id(tool_call)
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": result_content,
                },
            ],
        }

    def extract_tool_result_content(self, tool_result_message: dict[str, Any]) -> str:
        """Extract content from Claude tool result message."""
        content = tool_result_message.get("content", [])
        if isinstance(content, list) and content:
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    return item.get("content", "")
        return ""

    def reset_tool_usage(self):
        """Reset tool usage tracking."""
        self.search_count = 0
        self.code_session_hours = 0.0
        super().reset_token_usage()

    def _create_client(self, **kwargs):
        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        # Instrument client for Logfire observability if enabled
        try:
            from massgen.structured_logging import get_tracer, is_observability_enabled

            if is_observability_enabled():
                get_tracer().instrument_anthropic(client)
        except ImportError:
            pass  # structured_logging module not available
        except Exception as e:
            logger.warning(
                f"Failed to instrument Anthropic client for observability: {e}",
            )
        return client

    def get_provider_name(self) -> str:
        """Get the provider name."""
        return "Claude"

    def get_supported_builtin_tools(self) -> list[str]:
        """Get list of builtin tools supported by Claude."""
        return ["web_search", "code_execution"]

    def get_filesystem_support(self) -> FilesystemSupport:
        """Claude supports filesystem through MCP servers."""
        return FilesystemSupport.MCP

    def _validate_advanced_features(self, all_params: dict[str, Any]) -> None:
        model = all_params.get("model", "")
        compatible_patterns = [
            "claude-opus-4-5",
            "claude-sonnet-4-5",
        ]
        is_compatible = any(pattern in model for pattern in compatible_patterns)

        # Validate programmatic flow
        if all_params.get("enable_programmatic_flow"):
            if is_compatible:
                logger.info(
                    f"[Claude] Programmatic tool calling enabled for model '{model}'. " "Tools can be called from within code execution sandbox.",
                )
            else:
                logger.warning(
                    f"[Claude] Auto-disabling programmatic flow - model '{model}' not supported. "
                    f"Compatible models: Claude Opus 4.5, Claude Sonnet 4.5. "
                    f"Workflow will continue with standard tool calling.",
                )
                all_params["enable_programmatic_flow"] = False

        # Validate tool search
        if all_params.get("enable_tool_search"):
            if is_compatible:
                variant = all_params.get("tool_search_variant", "regex")
                logger.info(
                    f"[Claude] Tool search enabled for model '{model}' (variant: {variant}). " "Deferred tools will be discovered on-demand.",
                )
            else:
                logger.warning(
                    f"[Claude] Auto-disabling tool search - model '{model}' not supported. " f"Compatible models: Claude Opus 4.5, Claude Sonnet 4.5. " f"All tools will be visible without search.",
                )
                all_params["enable_tool_search"] = False
