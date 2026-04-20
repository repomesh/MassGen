"""
Read media files and analyze them using understand_* tools.

This is the primary tool for multimodal input in MassGen. It delegates to
understand_image, understand_audio, or understand_video based on file type.
These tools make external API calls to analyze the media content.

Supports batch mode for parallel analysis of multiple media files, including
multi-image prompts where multiple images are sent to the model together.
"""

import asyncio
import json
import re
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from massgen.logger_config import logger
from massgen.tool._decorators import context_params
from massgen.tool._result import ExecutionResult, TextContent

# Maximum time (seconds) for a single understand_image/video/audio call
MEDIA_ANALYSIS_TIMEOUT = 600  # 10 minutes


def _normalize_stringified_inputs(
    inputs: list[dict[str, Any]] | str | None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Normalize `inputs` when models pass JSON as a string.

    Returns:
        Tuple of (normalized_inputs, error_message). When normalization fails,
        error_message contains a user-facing explanation and normalized_inputs
        is None.
    """
    if not isinstance(inputs, str):
        return inputs, None

    raw = inputs.strip()
    if not raw:
        return (
            None,
            "inputs string is empty; expected a JSON array, " 'e.g. inputs=\'[{"files":{"image_0":"image.png"}}]\'',
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return (
            None,
            f"inputs must be a valid JSON array string: {exc.msg}. " 'Example: inputs=\'[{"files":{"image_0":"image.png"}}]\'',
        )

    if not isinstance(parsed, list):
        return (
            None,
            "inputs JSON string must decode to an array, " 'e.g. inputs=\'[{"files":{"image_0":"image.png"}}]\'',
        )

    return parsed, None


def _normalize_inputs_aliases(inputs: list[dict]) -> list[dict]:
    """Normalize common aliases in each input dict before validation.

    Handles ``file_paths`` (list) as an alias for ``files`` (dict), since
    models sometimes pluralize the top-level ``file_path`` parameter and
    produce an array instead of a named mapping.

    Rules:
    - If ``files`` is already present, leave it unchanged (``file_paths`` ignored).
    - If ``file_paths`` is a list, convert to ``files`` dict with keys
      ``image_0``, ``image_1``, ... and remove ``file_paths``.
    - If ``file_paths`` is not a list, leave it unchanged (validation will fail
      with a clear error downstream).
    """
    result = []
    for inp in inputs:
        if not isinstance(inp, dict):
            result.append(inp)
            continue
        if "files" in inp or "file_paths" not in inp:
            result.append(inp)
            continue
        file_paths = inp["file_paths"]
        if not isinstance(file_paths, list):
            result.append(inp)
            continue
        normalized = {k: v for k, v in inp.items() if k != "file_paths"}
        normalized["files"] = {f"image_{i}": p for i, p in enumerate(file_paths)}
        result.append(normalized)
    return result


def _inputs_only_example(media_type: str | None) -> str:
    """Return a concise inputs-only call shape example for a modality."""
    if media_type == "video":
        return 'inputs=[{"files":{"video_0":"clip.mp4"},"prompt":"Analyze this video"}]'
    if media_type == "audio":
        return 'inputs=[{"files":{"audio_0":"voice.mp3"},"prompt":"Analyze this audio"}]'
    return 'inputs=[{"files":{"image_0":"image.png"},"prompt":"Analyze this image"}]'


def _infer_media_type_from_input_item(inp: dict[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort infer modality + suspicious key from malformed batch item."""
    alias_map = {
        "screenshot_path": "image",
        "image_path": "image",
        "video_path": "video",
        "audio_path": "audio",
        "sound_path": "audio",
        "file_path": None,
    }

    for key, media_type in alias_map.items():
        if key not in inp:
            continue
        value = inp.get(key)
        if media_type is not None:
            return media_type, key
        if isinstance(value, str):
            return _detect_media_type(value), key
        return None, key

    for key, value in inp.items():
        if isinstance(value, str):
            media_type = _detect_media_type(value)
            if media_type:
                return media_type, key

    return None, None


def _build_missing_files_error(index: int, inp: dict[str, Any]) -> str:
    """Build actionable missing-files validation error with modality hints."""
    media_type, detected_key = _infer_media_type_from_input_item(inp)
    hint = _inputs_only_example(media_type)
    if detected_key:
        return f"inputs[{index}] missing required 'files' key. " f"Detected '{detected_key}'. " f"Use {hint}"
    return f"inputs[{index}] missing required 'files' key. Use {hint}"


def _error_result(error: str) -> ExecutionResult:
    """Create an error ExecutionResult."""
    return ExecutionResult(
        output_blocks=[
            TextContent(
                data=json.dumps({"success": False, "operation": "read_media", "error": error}, indent=2),
            ),
        ],
    )


def _parse_severity_summary(response_text: str) -> dict[str, Any] | None:
    """Best-effort parse a JSON severity summary from the vision model response.

    Looks for JSON containing ``foundation_sound`` key, either in a code fence
    or as a standalone JSON object. Returns None if not found or malformed.
    """
    # Try code-fenced JSON first
    fenced = re.findall(r"```json\s*\n(.*?)\n```", response_text, re.DOTALL)
    for block in fenced:
        try:
            data = json.loads(block)
            if "foundation_sound" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            continue

    # Try standalone JSON objects containing foundation_sound
    for match in re.finditer(r"\{[^{}]*\"foundation_sound\"[^{}]*\}", response_text):
        try:
            data = json.loads(match.group())
            return data
        except (json.JSONDecodeError, TypeError):
            continue

    return None


def _maybe_add_severity_fields(
    result: dict[str, Any],
    severity: dict[str, Any] | None,
) -> None:
    """Add severity_summary and foundation_warning to result dict if applicable."""
    if severity is None:
        return

    result["severity_summary"] = severity
    result["foundation_sound"] = severity.get("foundation_sound", True)

    if not severity.get("foundation_sound", True):
        result["foundation_warning"] = (
            "Vision analysis found fundamental issues with the current approach. "
            "Consider whether the direction needs rethinking rather than "
            "incremental patching. Include these findings in your diagnostic report."
        )


class _ConversationStore:
    """Stores conversation state for read_media follow-ups.

    Maps conversation_id -> state dict containing backend_type, response_id
    (for OpenAI), message history (for other backends), images, model, etc.
    """

    def __init__(self, max_conversations: int = 50):
        self._store: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max = max_conversations

    def save(self, conv_id: str, state: dict[str, Any]) -> None:
        """Save or update conversation state. Evicts oldest if over max."""
        if conv_id in self._store:
            del self._store[conv_id]
        elif len(self._store) >= self._max:
            self._store.popitem(last=False)
        self._store[conv_id] = state

    def get(self, conv_id: str) -> dict[str, Any] | None:
        """Retrieve conversation state by ID, or None if not found."""
        return self._store.get(conv_id)


_conversation_store = _ConversationStore()


# Supported media types and their extensions
MEDIA_TYPE_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif"},
}


def _detect_media_type(file_path: str) -> str | None:
    """Detect media type from file extension.

    Args:
        file_path: Path to the media file

    Returns:
        Media type string ("image", "audio", "video") or None if unsupported
    """
    ext = Path(file_path).suffix.lower()
    for media_type, extensions in MEDIA_TYPE_EXTENSIONS.items():
        if ext in extensions:
            return media_type
    return None


def _validate_path_access(path: Path, allowed_paths: list[Path] | None = None) -> None:
    """Validate that a path is within allowed directories.

    Args:
        path: Path to validate
        allowed_paths: List of allowed base paths (optional)

    Raises:
        ValueError: If path is not within allowed directories
    """
    if not allowed_paths:
        return  # No restrictions

    for allowed_path in allowed_paths:
        try:
            path.relative_to(allowed_path)
            return  # Path is within this allowed directory
        except ValueError:
            continue

    raise ValueError(f"Path not in allowed directories: {path}")


@context_params(
    "backend_type",
    "model",
    "agent_cwd",
    "allowed_paths",
    "multimodal_config",
    "task_context",
)
async def read_media(
    prompt: str | None = None,
    inputs: list[dict[str, Any]] | None = None,
    max_concurrent: int = 4,
    continue_from: str | None = None,
    agent_cwd: str | None = None,
    allowed_paths: list[str] | None = None,
    backend_type: str | None = None,
    model: str | None = None,
    multimodal_config: dict[str, Any] | None = None,
    task_context: str | None = None,
) -> ExecutionResult:
    """
    Read and analyze media file(s) using external API calls.

    This tool delegates to understand_image, understand_audio, or understand_video
    based on the file type. These tools make external API calls to analyze the
    media content and return text descriptions.

    Supports batch mode: provide `inputs` (list of dicts) to analyze multiple
    media items in parallel, including multi-image prompts where multiple images
    are sent to the model together for comparison/analysis.

    Supports:
    - Images: png, jpg, jpeg, gif, webp, bmp
    - Audio: mp3, wav, m4a, ogg, flac, aac
    - Video: mp4, mov, avi, mkv, webm

    Analysis Quality:
        The vision model is instructed to be a critical reviewer by default.
        It will identify problems, classify their severity (fundamental vs
        surface-level), and assess whether the overall approach is sound.

        You can still customize analysis with your prompt. Good prompts for
        different domains:
        - Website: "What flaws, layout issues, or broken elements do you see?"
        - Generated image: "Does this match what was requested? What's off?"
        - Chart/diagram: "Is the data clearly communicated? What's misleading?"
        - Code output: "Are there obvious bugs or unclear patterns visible?"

        The system prompt can be disabled via multimodal_config:
            multimodal_config:
              image:
                system_prompt_enabled: false

    Args:
        prompt: Optional prompt/question about the media content.
                For evaluation: include critical/skeptical framing in your prompt.
        inputs: List of input specs for batch/multi-image analysis.
                Each input is a dict with:
                - "files": Dict mapping names to paths, e.g. {"before": "a.png", "after": "b.png"}
                - "prompt": Optional prompt for this input (reference images by name)
                Multiple inputs are processed in parallel.
        max_concurrent: Maximum concurrent analyses for batch mode (default: 4).
        agent_cwd: Agent's current working directory (automatically injected).
        allowed_paths: List of allowed base paths for validation (optional).
        backend_type: Backend type (automatically injected from ExecutionContext).
        model: Model name (automatically injected from ExecutionContext).
        multimodal_config: Optional config overrides per modality.

    Returns:
        ExecutionResult containing text description/analysis of the media.
        For batch mode, returns results array with per-input status.

    Examples:
        # Batch with multi-image comparison (parallel processing)
        read_media(
            inputs=[
                {"files": {"before": "v1.png", "after": "v2.png"}, "prompt": "Compare before and after"},
                {"files": {"error": "error.png"}, "prompt": "What error is shown?"}
            ],
            max_concurrent=2
        )
        → Returns batch results with each input processed in parallel

        # Critical evaluation of video
        read_media(inputs=[{"files": {"video_0": "game_recording.mp4"}}],
                   prompt="Does gameplay look correct? Are controls responsive? Be critical.")
        → Returns critique-focused analysis
    """
    # Normalize stringified JSON inputs before validation.
    inputs, inputs_error = _normalize_stringified_inputs(inputs)
    if inputs_error:
        return _error_result(inputs_error)

    # Inputs-only contract (continue_from remains available for follow-up calls).
    if not inputs and not continue_from:
        return _error_result("Must provide either 'inputs' or 'continue_from'")

    # Validate continue_from early
    if continue_from:
        conv_state = _conversation_store.get(continue_from)
        if conv_state is None:
            return _error_result(
                f"Conversation '{continue_from}' not found. " "The conversation_id may have expired or belongs to a previous session.",
            )

    # Normalize common aliases before validation
    if inputs:
        inputs = _normalize_inputs_aliases(inputs)

    # Validate inputs structure if provided
    if inputs:
        for i, inp in enumerate(inputs):
            if not isinstance(inp, dict):
                return _error_result(f"inputs[{i}] must be a dict, got {type(inp).__name__}")
            if "files" not in inp:
                return _error_result(_build_missing_files_error(i, inp))
            if not isinstance(inp["files"], dict) or not inp["files"]:
                return _error_result(f"inputs[{i}]['files'] must be a non-empty dict mapping names to paths")

    if max_concurrent is None:
        max_concurrent = 4
    elif not isinstance(max_concurrent, int) or max_concurrent <= 0:
        return _error_result("max_concurrent must be a positive integer")

    try:
        # Load task_context dynamically from CONTEXT.md (it may be created during execution)
        from massgen.context.task_context import load_task_context_with_warning

        task_context, context_warning = load_task_context_with_warning(agent_cwd, task_context)

        # Require CONTEXT.md for external API calls
        if not task_context:
            context_search_path = agent_cwd or "None (no agent_cwd provided)"
            return _error_result(
                f"CONTEXT.md not found in workspace: {context_search_path}. "
                "Before using read_media, create a CONTEXT.md file with task context. "
                "This helps external APIs understand what you're working on. "
                "See system prompt for instructions and examples.",
            )

        # Helper to add context warning to result dict if present
        def _add_warning(result_dict: dict[str, Any]) -> dict[str, Any]:
            if context_warning:
                result_dict["warning"] = context_warning
            return result_dict

        # Convert allowed_paths from strings to Path objects
        allowed_paths_list = [Path(p) for p in allowed_paths] if allowed_paths else None
        base_dir = Path(agent_cwd) if agent_cwd else Path.cwd()

        # Extract config overrides
        image_config = (multimodal_config or {}).get("image", {})
        audio_config = (multimodal_config or {}).get("audio", {})
        video_config = (multimodal_config or {}).get("video", {})

        # Vision system prompt — on by default, disable via multimodal_config
        from massgen.tool._multimodal_tools.analysis_prompts import (
            DEFAULT_MEDIA_PROMPT_TEMPLATE,
            VISION_SYSTEM_PROMPT,
        )

        vision_system_prompt: str | None = VISION_SYSTEM_PROMPT
        if image_config.get("system_prompt_enabled") is False:
            vision_system_prompt = None

        # Generate conversation_id for this call (reuse existing for follow-ups)
        conversation_id = continue_from or f"conv_{uuid.uuid4().hex[:12]}"

        # Resolve follow-up state
        prev_response_id: str | None = None
        conv_messages: list[dict] | None = None
        if continue_from and conv_state:
            prev_response_id = conv_state.get("response_id")
            conv_messages = conv_state.get("messages")
            # Inherit backend/model from prior conversation if not provided
            if not backend_type:
                backend_type = conv_state.get("backend_type")
            if not model:
                model = conv_state.get("model")

        # Inputs-only contract still supports single-file behavior by using
        # a single-item inputs payload with a one-file files dict.
        single_input_file_path: str | None = None
        single_input_prompt: str | None = prompt
        if inputs and len(inputs) == 1 and isinstance(inputs[0], dict):
            files_dict = inputs[0].get("files")
            if isinstance(files_dict, dict) and len(files_dict) == 1:
                candidate_path = next(iter(files_dict.values()))
                if isinstance(candidate_path, str):
                    single_input_file_path = candidate_path
                    single_input_prompt = inputs[0].get("prompt") or prompt

        # ------------------------------------------------------------------
        # FOLLOW-UP MODE (continue_from without new inputs)
        # ------------------------------------------------------------------
        if single_input_file_path or (continue_from and not inputs):
            if single_input_file_path:
                if Path(single_input_file_path).is_absolute():
                    media_path = Path(single_input_file_path).resolve()
                else:
                    media_path = (base_dir / single_input_file_path).resolve()

                _validate_path_access(media_path, allowed_paths_list)

                if not media_path.exists():
                    return _error_result(f"File does not exist: {media_path}")

                media_type = _detect_media_type(single_input_file_path)
                if not media_type:
                    return _error_result(
                        f"Unsupported file type: {media_path.suffix}. " "Supported: images (png, jpg, webp), audio (mp3, wav, m4a, ogg), " "video (mp4, mov, avi, mkv, webm, gif)",
                    )
            else:
                # Follow-up without new file — use stored conversation's media type
                media_type = conv_state.get("media_type", "image") if conv_state else "image"
                media_path = None

            logger.info(f"Using understand_{media_type} for {media_type} analysis")

            selected_prompt = single_input_prompt if single_input_file_path else prompt
            default_prompt = selected_prompt or DEFAULT_MEDIA_PROMPT_TEMPLATE.format(
                media_type=media_type,
            )

            if media_type == "image":
                from massgen.tool._multimodal_tools.understand_image import (
                    understand_image,
                )

                image_kwargs: dict[str, Any] = {
                    "prompt": default_prompt,
                    "agent_cwd": agent_cwd,
                    "allowed_paths": allowed_paths,
                    "task_context": task_context,
                    "backend_type": backend_type,
                    "model": image_config.get("model") or model or "gpt-5.4",
                    "system_prompt": vision_system_prompt,
                    "previous_response_id": prev_response_id,
                    "conversation_messages": conv_messages,
                    # None = API default (legacy). `--fast` injects "low" via
                    # `multimodal_config.image.reasoning_effort`.
                    "reasoning_effort": image_config.get("reasoning_effort"),
                }
                if media_path:
                    image_kwargs["image_path"] = str(media_path)

                result = await asyncio.wait_for(understand_image(**image_kwargs), timeout=MEDIA_ANALYSIS_TIMEOUT)

                # Add conversation_id and warning to result
                for block in result.output_blocks:
                    if isinstance(block, TextContent):
                        try:
                            data = json.loads(block.data)
                            data["conversation_id"] = conversation_id
                            if context_warning:
                                data["warning"] = context_warning

                            # Save conversation state for future follow-ups
                            new_state: dict[str, Any] = {
                                "media_type": "image",
                                "backend_type": backend_type,
                                "response_id": data.get("response_id"),
                                "model": image_kwargs["model"],
                                "system_prompt": vision_system_prompt,
                                "prompt": default_prompt,
                                "messages": [],
                                "images": [],
                            }
                            # For non-OpenAI backends, build message history
                            if not data.get("response_id") and conv_messages:
                                new_state["messages"] = conv_messages + [
                                    {"role": "user", "content": default_prompt},
                                    {"role": "assistant", "content": data.get("response", "")},
                                ]
                            elif not data.get("response_id"):
                                new_state["messages"] = [
                                    {"role": "user", "content": default_prompt},
                                    {"role": "assistant", "content": data.get("response", "")},
                                ]
                            _conversation_store.save(conversation_id, new_state)

                            block.data = json.dumps(data, indent=2)
                        except (json.JSONDecodeError, AttributeError) as e:
                            logger.warning(
                                f"[read_media] Could not inject conversation_id into image result " f"block (parse failed: {e}). Follow-up calls with continue_from " f"will not work.",
                            )
                return result

            elif media_type == "audio":
                from massgen.tool._multimodal_tools.understand_audio import (
                    understand_audio,
                )

                result = await asyncio.wait_for(
                    understand_audio(
                        audio_paths=[str(media_path)],
                        prompt=default_prompt,
                        backend_type=audio_config.get("backend") or backend_type,
                        model=audio_config.get("model"),
                        agent_cwd=agent_cwd,
                        allowed_paths=allowed_paths,
                        task_context=task_context,
                    ),
                    timeout=MEDIA_ANALYSIS_TIMEOUT,
                )
                if context_warning:
                    for block in result.output_blocks:
                        if isinstance(block, TextContent):
                            try:
                                data = json.loads(block.data)
                                data["warning"] = context_warning
                                block.data = json.dumps(data, indent=2)
                            except (json.JSONDecodeError, AttributeError) as e:
                                logger.warning(
                                    f"[read_media] Could not inject context warning into audio " f"result block (parse failed: {e}).",
                                )
                return result

            elif media_type == "video":
                from massgen.tool._multimodal_tools.understand_video import (
                    understand_video,
                )

                result = await asyncio.wait_for(
                    understand_video(
                        video_path=str(media_path),
                        prompt=default_prompt,
                        backend_type=video_config.get("backend") or backend_type,
                        model=video_config.get("model"),
                        agent_cwd=agent_cwd,
                        allowed_paths=allowed_paths,
                        task_context=task_context,
                        video_extraction_config=video_config,
                        system_prompt=vision_system_prompt,
                    ),
                    timeout=MEDIA_ANALYSIS_TIMEOUT,
                )
                if context_warning:
                    for block in result.output_blocks:
                        if isinstance(block, TextContent):
                            try:
                                data = json.loads(block.data)
                                data["warning"] = context_warning
                                block.data = json.dumps(data, indent=2)
                            except (json.JSONDecodeError, AttributeError) as e:
                                logger.warning(
                                    f"[read_media] Could not inject context warning into video " f"result block (parse failed: {e}).",
                                )
                return result

        # ------------------------------------------------------------------
        # BATCH MODE with multi-image support
        # ------------------------------------------------------------------
        async def _process_one_input(idx: int, inp: dict[str, Any], semaphore: asyncio.Semaphore) -> dict[str, Any]:
            """Process a single input spec with concurrency control."""
            async with semaphore:
                try:
                    files_dict: dict[str, str] = inp["files"]
                    input_prompt = inp.get("prompt") or prompt

                    # Determine media type from first file
                    first_path = next(iter(files_dict.values()))
                    media_type = _detect_media_type(first_path)

                    if not media_type:
                        return {
                            "input_index": idx,
                            "success": False,
                            "error": f"Unsupported file type for '{first_path}'",
                        }

                    default_prompt = input_prompt or DEFAULT_MEDIA_PROMPT_TEMPLATE.format(
                        media_type=media_type,
                    )

                    # For now, only images support multi-file in single call
                    # Audio/video process first file only
                    if media_type == "image":
                        from massgen.tool._multimodal_tools.understand_image import (
                            understand_image,
                        )

                        image_kwargs: dict[str, Any] = {
                            "images": files_dict,
                            "prompt": default_prompt,
                            "agent_cwd": agent_cwd,
                            "allowed_paths": allowed_paths,
                            "task_context": task_context,
                            "backend_type": backend_type,
                            "model": image_config.get("model") or model or "gpt-5.4",
                            "system_prompt": vision_system_prompt,
                            "reasoning_effort": image_config.get("reasoning_effort"),
                        }

                        result = await asyncio.wait_for(understand_image(**image_kwargs), timeout=MEDIA_ANALYSIS_TIMEOUT)

                        # Parse result
                        for block in result.output_blocks:
                            if isinstance(block, TextContent):
                                try:
                                    data = json.loads(block.data)
                                    data["input_index"] = idx
                                    return data
                                except json.JSONDecodeError as e:
                                    logger.error(
                                        f"[read_media] Failed to parse image result JSON at index {idx}: {e}. " f"Block data: {block.data[:200]}",
                                    )
                                    continue

                    elif media_type == "audio":
                        from massgen.tool._multimodal_tools.understand_audio import (
                            understand_audio,
                        )

                        # Audio: use all files
                        audio_paths = list(files_dict.values())
                        result = await asyncio.wait_for(
                            understand_audio(
                                audio_paths=audio_paths,
                                prompt=default_prompt,
                                backend_type=audio_config.get("backend") or backend_type,
                                model=audio_config.get("model"),
                                agent_cwd=agent_cwd,
                                allowed_paths=allowed_paths,
                                task_context=task_context,
                            ),
                            timeout=MEDIA_ANALYSIS_TIMEOUT,
                        )
                        for block in result.output_blocks:
                            if isinstance(block, TextContent):
                                try:
                                    data = json.loads(block.data)
                                    data["input_index"] = idx
                                    return data
                                except json.JSONDecodeError as e:
                                    logger.error(
                                        f"[read_media] Failed to parse audio result JSON at index {idx}: {e}. " f"Block data: {block.data[:200]}",
                                    )
                                    continue

                    elif media_type == "video":
                        from massgen.tool._multimodal_tools.understand_video import (
                            understand_video,
                        )

                        # Video: use first file only
                        result = await asyncio.wait_for(
                            understand_video(
                                video_path=first_path,
                                prompt=default_prompt,
                                backend_type=video_config.get("backend") or backend_type,
                                model=video_config.get("model"),
                                agent_cwd=agent_cwd,
                                allowed_paths=allowed_paths,
                                task_context=task_context,
                                video_extraction_config=video_config,
                                system_prompt=vision_system_prompt,
                            ),
                            timeout=MEDIA_ANALYSIS_TIMEOUT,
                        )
                        for block in result.output_blocks:
                            if isinstance(block, TextContent):
                                try:
                                    data = json.loads(block.data)
                                    data["input_index"] = idx
                                    return data
                                except json.JSONDecodeError as e:
                                    logger.error(
                                        f"[read_media] Failed to parse video result JSON at index {idx}: {e}. " f"Block data: {block.data[:200]}",
                                    )
                                    continue

                    return {"input_index": idx, "success": False, "error": "No result returned"}

                except Exception as e:
                    logger.exception(f"Error processing input {idx}")
                    return {"input_index": idx, "success": False, "error": str(e)}

        # Execute all inputs in parallel with concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [_process_one_input(i, inp, semaphore) for i, inp in enumerate(inputs)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert any exceptions to error results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append({"input_index": i, "success": False, "error": str(result)})
            else:
                final_results.append(result)

        # Calculate success/failure counts
        succeeded = sum(1 for r in final_results if r.get("success"))
        failed = len(final_results) - succeeded

        response_data = _add_warning(
            {
                "success": succeeded > 0,
                "operation": "read_media",
                "batch": True,
                "total": len(final_results),
                "succeeded": succeeded,
                "failed": failed,
                "results": final_results,
            },
        )

        return ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(response_data, indent=2))],
        )

    except ValueError as ve:
        return _error_result(str(ve))

    except Exception as e:
        return _error_result(f"Failed to read media: {str(e)}")
