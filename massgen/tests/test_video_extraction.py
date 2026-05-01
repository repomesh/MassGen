"""
Tests for configurable video frame extraction strategies.

Tests VideoExtractionConfig parsing, uniform extraction (FPS-based and fixed count),
scene-based extraction with PySceneDetect, and config passthrough from read_media.
"""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_video(tmp_path: Path, num_frames: int = 100, fps: float = 25.0) -> Path:
    """Create a minimal .mp4 file via OpenCV with synthetic frames.

    Returns the path to the created video file.
    """
    import cv2
    import numpy as np

    video_path = tmp_path / "test_video.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (64, 64))

    for i in range(num_frames):
        # Create a frame with varying color so scene detection can find changes
        color = int((i / num_frames) * 255)
        frame = np.full((64, 64, 3), color, dtype=np.uint8)
        writer.write(frame)

    writer.release()
    return video_path


def _make_scene_change_video(tmp_path: Path, fps: float = 25.0) -> Path:
    """Create a video with distinct scene changes (sharp color transitions).

    Creates 3 scenes: red, green, blue — each 25 frames (1 second each at 25fps).
    """
    import cv2
    import numpy as np

    video_path = tmp_path / "scene_change_video.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (64, 64))

    colors = [
        (0, 0, 255),  # Red (BGR)
        (0, 255, 0),  # Green
        (255, 0, 0),  # Blue
    ]

    for color in colors:
        for _ in range(25):  # 25 frames per scene
            frame = np.full((64, 64, 3), color, dtype=np.uint8)
            writer.write(frame)

    writer.release()
    return video_path


# ---------------------------------------------------------------------------
# TestVideoExtractionConfig — parsing, defaults, capping
# ---------------------------------------------------------------------------


class TestVideoExtractionConfig:
    """Test VideoExtractionConfig parsing from dict, defaults, and capping."""

    def test_defaults_when_no_config(self):
        from massgen.tool._multimodal_tools.video_extraction import (
            DEFAULT_FPS,
            DEFAULT_FRAMES_PER_SCENE,
            DEFAULT_MAX_FRAMES,
            DEFAULT_SCENE_THRESHOLD,
            ExtractionMode,
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config(None)

        assert config.extraction_mode == ExtractionMode.SCENE
        assert config.max_frames == DEFAULT_MAX_FRAMES
        assert config.fps == DEFAULT_FPS
        assert config.threshold == DEFAULT_SCENE_THRESHOLD
        assert config.frames_per_scene == DEFAULT_FRAMES_PER_SCENE
        assert config.num_frames is None

    def test_uniform_mode_from_dict(self):
        from massgen.tool._multimodal_tools.video_extraction import (
            ExtractionMode,
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "uniform", "fps": 2.0},
        )

        assert config.extraction_mode == ExtractionMode.UNIFORM
        assert config.fps == 2.0

    def test_scene_mode_from_dict(self):
        from massgen.tool._multimodal_tools.video_extraction import (
            ExtractionMode,
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "scene", "threshold": 0.5, "frames_per_scene": 5},
        )

        assert config.extraction_mode == ExtractionMode.SCENE
        assert config.threshold == 0.5
        assert config.frames_per_scene == 5

    def test_max_frames_capped_at_absolute_max(self):
        from massgen.tool._multimodal_tools.video_extraction import (
            ABSOLUTE_MAX_FRAMES,
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config({"max_frames": 999})

        assert config.max_frames == ABSOLUTE_MAX_FRAMES

    def test_max_frames_within_limit(self):
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config({"max_frames": 20})
        assert config.max_frames == 20

    def test_num_frames_from_config(self):
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config({"num_frames": 12})
        assert config.num_frames == 12

    def test_num_frames_from_legacy_param(self):
        """Legacy num_frames parameter (from understand_video signature) is used."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config(None, legacy_num_frames=16)
        assert config.num_frames == 16

    def test_config_num_frames_overrides_legacy(self):
        """Config num_frames takes priority over legacy parameter."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config(
            {"num_frames": 10},
            legacy_num_frames=8,
        )
        assert config.num_frames == 10

    def test_unknown_mode_falls_back_to_scene(self):
        from massgen.tool._multimodal_tools.video_extraction import (
            ExtractionMode,
            VideoExtractionConfig,
        )

        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "nonexistent"},
        )
        assert config.extraction_mode == ExtractionMode.SCENE


# ---------------------------------------------------------------------------
# TestUniformExtraction — correct frame count, max_frames cap, short video
# ---------------------------------------------------------------------------


class TestUniformExtraction:
    """Test uniform frame extraction strategy."""

    def test_fps_based_extraction_10s_video(self, tmp_path):
        """10s video at 1 FPS → 10 frames."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        # 250 frames at 25fps = 10 seconds
        video_path = _make_fake_video(tmp_path, num_frames=250, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "uniform", "fps": 1.0},
        )

        frames = extract_frames(video_path, config)
        assert len(frames) == 10

    def test_fps_based_extraction_capped_at_max_frames(self, tmp_path):
        """2min video at 1 FPS would be 120 frames, capped at max_frames=30."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        # 3000 frames at 25fps = 120 seconds
        video_path = _make_fake_video(tmp_path, num_frames=3000, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "uniform", "fps": 1.0, "max_frames": 30},
        )

        frames = extract_frames(video_path, config)
        assert len(frames) == 30

    def test_num_frames_overrides_fps(self, tmp_path):
        """When num_frames is set explicitly, use that instead of FPS-based calc."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        video_path = _make_fake_video(tmp_path, num_frames=250, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "uniform", "fps": 1.0, "num_frames": 8},
        )

        frames = extract_frames(video_path, config)
        assert len(frames) == 8

    def test_short_video_fewer_frames_than_requested(self, tmp_path):
        """Video with only 3 frames → returns all 3."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        video_path = _make_fake_video(tmp_path, num_frames=3, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "uniform", "num_frames": 10},
        )

        frames = extract_frames(video_path, config)
        assert len(frames) == 3

    def test_frames_are_valid_base64_jpeg(self, tmp_path):
        """Extracted frames should be valid base64-encoded JPEG data."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        video_path = _make_fake_video(tmp_path, num_frames=50, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "uniform", "num_frames": 2},
        )

        frames = extract_frames(video_path, config)
        assert len(frames) == 2

        for frame_b64 in frames:
            # Should be valid base64
            decoded = base64.b64decode(frame_b64)
            # JPEG magic bytes
            assert decoded[:2] == b"\xff\xd8"


# ---------------------------------------------------------------------------
# TestSceneExtraction — fallback, mock detection, max_frames cap
# ---------------------------------------------------------------------------


class TestSceneExtraction:
    """Test scene-based extraction strategy."""

    def test_fallback_to_uniform_when_scenedetect_missing(self, tmp_path):
        """When scenedetect is not installed, fall back to uniform extraction."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        video_path = _make_fake_video(tmp_path, num_frames=250, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "scene", "max_frames": 10},
        )

        # Mock scenedetect as unavailable

        with patch.dict("sys.modules", {"scenedetect": None}):
            frames = extract_frames(video_path, config)

        # Should still return frames (via uniform fallback)
        assert len(frames) > 0
        assert len(frames) <= 10

    def test_scene_detection_with_mock(self, tmp_path):
        """Scene detection with mocked PySceneDetect returns correct frame count."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        video_path = _make_fake_video(tmp_path, num_frames=250, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {
                "extraction_mode": "scene",
                "threshold": 0.3,
                "frames_per_scene": 3,
                "max_frames": 30,
            },
        )

        # Mock scenedetect to return 3 scenes
        mock_scene_list = [
            (Mock(get_frames=lambda: 0), Mock(get_frames=lambda: 83)),
            (Mock(get_frames=lambda: 83), Mock(get_frames=lambda: 166)),
            (Mock(get_frames=lambda: 166), Mock(get_frames=lambda: 250)),
        ]

        with patch(
            "massgen.tool._multimodal_tools.video_extraction._detect_scenes",
            return_value=mock_scene_list,
        ):
            frames = extract_frames(video_path, config)

        # 3 scenes × 3 frames_per_scene = 9 frames
        assert len(frames) == 9

    def test_scene_detection_capped_at_max_frames(self, tmp_path):
        """When scene detection would produce too many frames, cap at max_frames."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        video_path = _make_fake_video(tmp_path, num_frames=250, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {
                "extraction_mode": "scene",
                "frames_per_scene": 5,
                "max_frames": 8,
            },
        )

        # Mock 10 scenes — 10 × 5 = 50 frames, should cap at 8
        mock_scenes = []
        for i in range(10):
            start = i * 25
            end = (i + 1) * 25
            mock_scenes.append(
                (Mock(get_frames=lambda s=start: s), Mock(get_frames=lambda e=end: e)),
            )

        with patch(
            "massgen.tool._multimodal_tools.video_extraction._detect_scenes",
            return_value=mock_scenes,
        ):
            frames = extract_frames(video_path, config)

        assert len(frames) <= 8

    def test_no_scenes_detected_falls_back_to_uniform(self, tmp_path):
        """When scene detection finds 0 scenes, fall back to uniform."""
        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        video_path = _make_fake_video(tmp_path, num_frames=250, fps=25.0)
        config = VideoExtractionConfig.from_video_config(
            {"extraction_mode": "scene", "max_frames": 10},
        )

        with patch(
            "massgen.tool._multimodal_tools.video_extraction._detect_scenes",
            return_value=[],
        ):
            frames = extract_frames(video_path, config)

        # Should fall back to uniform and return frames
        assert len(frames) > 0
        assert len(frames) <= 10


# ---------------------------------------------------------------------------
# TestConfigPassthrough — read_media passes video config through
# ---------------------------------------------------------------------------


class TestConfigPassthrough:
    """Test that read_media passes video extraction config to understand_video."""

    @pytest.mark.asyncio
    async def test_read_media_passes_video_config(self, tmp_path):
        """read_media should pass video_extraction_config to understand_video."""
        # Create a dummy video file
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)

        video_config = {
            "backend": "openai",
            "extraction_mode": "uniform",
            "num_frames": 12,
            "max_frames": 20,
        }

        with (
            patch("massgen.context.task_context.load_task_context_with_warning") as mock_ctx,
            patch(
                "massgen.tool._multimodal_tools.understand_video.understand_video",
                new_callable=AsyncMock,
            ) as mock_uv,
        ):
            import json

            from massgen.tool._result import ExecutionResult, TextContent

            mock_ctx.return_value = ("some context", None)
            mock_uv.return_value = ExecutionResult(
                output_blocks=[
                    TextContent(
                        data=json.dumps({"success": True, "operation": "understand_video", "response": "ok"}),
                    ),
                ],
            )

            from massgen.tool._multimodal_tools.read_media import read_media

            await read_media(
                inputs=[{"files": {"video_0": str(video_file)}, "prompt": "describe"}],
                backend_type="openai",
                model="gpt-5.2",
                multimodal_config={"video": video_config},
                agent_cwd=str(tmp_path),
            )

            mock_uv.assert_called_once()
            call_kwargs = mock_uv.call_args[1] if mock_uv.call_args[1] else {}
            # The video_extraction_config should be passed through
            assert "video_extraction_config" in call_kwargs
            assert call_kwargs["video_extraction_config"] == video_config

    @pytest.mark.asyncio
    async def test_understand_video_creates_config_from_dict(self, tmp_path):
        """understand_video should parse video_extraction_config into VideoExtractionConfig."""
        import json

        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)

        with (
            patch(
                "massgen.tool._multimodal_tools.understand_video._process_with_openai",
                new_callable=AsyncMock,
            ) as mock_openai,
            patch(
                "massgen.tool._multimodal_tools.understand_video.extract_frames",
            ) as mock_extract,
            patch(
                "massgen.tool._multimodal_tools.understand_video.get_backend",
            ) as mock_backend,
        ):
            from massgen.tool._multimodal_tools.backend_selector import BackendConfig

            mock_backend.return_value = BackendConfig(name="openai", model="gpt-5.2", api_key_env_vars=["OPENAI_API_KEY"])
            mock_extract.return_value = ["base64frame1", "base64frame2"]
            mock_openai.return_value = "analysis result"

            from massgen.tool._multimodal_tools.understand_video import understand_video

            result = await understand_video(
                video_path=str(video_file),
                prompt="describe",
                video_extraction_config={
                    "extraction_mode": "uniform",
                    "num_frames": 5,
                },
            )

            data = json.loads(result.output_blocks[0].data)
            assert data["frame_extraction_performed"] is True
            assert data["frame_extraction_reason"] == "frame_sampling"
            assert data["frames_extracted"] == 2

            # extract_frames should have been called with a VideoExtractionConfig
            mock_extract.assert_called_once()
            call_args = mock_extract.call_args
            config_arg = call_args[0][1]  # second positional arg

            from massgen.tool._multimodal_tools.video_extraction import (
                ExtractionMode,
                VideoExtractionConfig,
            )

            assert isinstance(config_arg, VideoExtractionConfig)
            assert config_arg.extraction_mode == ExtractionMode.UNIFORM
            assert config_arg.num_frames == 5

    @pytest.mark.asyncio
    async def test_understand_video_marks_native_backend_no_frame_extraction(self, tmp_path):
        """Gemini native video path should report that frame extraction was not performed."""
        import json

        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)

        with (
            patch(
                "massgen.tool._multimodal_tools.understand_video._process_with_gemini",
                new_callable=AsyncMock,
            ) as mock_gemini,
            patch(
                "massgen.tool._multimodal_tools.understand_video.extract_frames",
            ) as mock_extract,
            patch(
                "massgen.tool._multimodal_tools.understand_video.get_backend",
            ) as mock_backend,
        ):
            from massgen.tool._multimodal_tools.backend_selector import BackendConfig
            from massgen.tool._multimodal_tools.understand_video import understand_video

            mock_backend.return_value = BackendConfig(
                name="gemini",
                model="gemini-3-flash-preview",
                api_key_env_vars=["GOOGLE_API_KEY", "GEMINI_API_KEY"],
            )
            mock_gemini.return_value = "native analysis"

            result = await understand_video(
                video_path=str(video_file),
                prompt="describe",
            )

            data = json.loads(result.output_blocks[0].data)
            assert data["success"] is True
            assert data["backend"] == "gemini"
            assert data["frames_extracted"] == 0
            assert data["frame_extraction_performed"] is False
            assert data["frame_extraction_reason"] == "native_backend"
            mock_extract.assert_not_called()


# ---------------------------------------------------------------------------
# Live tests (opt-in, require real video + scenedetect)
# ---------------------------------------------------------------------------


@pytest.mark.live_api
@pytest.mark.expensive
class TestSceneDetectionLive:
    """Live tests with actual PySceneDetect. Run with --run-live-api."""

    def test_scene_detection_on_real_video(self, tmp_path):
        """Test scene detection on a video with actual scene changes."""
        try:
            import scenedetect  # noqa: F401
        except ImportError:
            pytest.skip("scenedetect not installed")

        from massgen.tool._multimodal_tools.video_extraction import (
            VideoExtractionConfig,
            extract_frames,
        )

        video_path = _make_scene_change_video(tmp_path)
        config = VideoExtractionConfig.from_video_config(
            {
                "extraction_mode": "scene",
                "threshold": 0.3,
                "frames_per_scene": 2,
                "max_frames": 20,
            },
        )

        frames = extract_frames(video_path, config)

        # Should detect the scene changes and extract frames
        assert len(frames) > 0
        assert len(frames) <= 20
        print(f"Detected scenes produced {len(frames)} frames")
