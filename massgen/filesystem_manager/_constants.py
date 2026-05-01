"""Centralized constants for filesystem operations.

This module defines common patterns for directories and files that should be
excluded from various operations like logging, sharing, and path permissions.
"""

# =============================================================================
# DIRECTORY PATTERNS TO SKIP/EXCLUDE
# =============================================================================

# Large dependency/cache directories that should be skipped in logging and listing
# These directories can contain thousands of files and slow down operations
SKIP_DIRS_FOR_LOGGING = frozenset(
    {
        # Backend config directories
        ".gemini",
        # Package managers / dependencies
        "node_modules",
        ".pnpm",
        ".pnpm-store",  # pnpm content-addressable store
        "vendor",  # PHP, Go
        "pkg",  # Go
        "target",  # Rust
        # Python
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "*.egg-info",
        # Build outputs
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".parcel-cache",
        # Caches
        ".cache",
        ".coverage",
    },
)

# Directories that are critical/sensitive and should be protected from agent access
# Agents should not read/write to these directories
CRITICAL_DIRS = frozenset(
    {
        ".git",
        ".gemini",
        ".env",
        ".massgen",
        "massgen_logs",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    },
)

# Directories excluded from path permissions by default
# Subset of critical dirs that permission manager should block
DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".massgen",
        ".gemini",
        ".env",
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".DS_Store",
        "massgen_logs",
    },
)

# Directories to exclude when uploading to gist/sharing
# These are often huge and not useful for sharing session data
SHARE_EXCLUDE_DIRS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".venv",
        ".git",
        "workspace",  # Agent workspace directories (often huge)
    },
)

# =============================================================================
# FILE PATTERNS TO IGNORE
# =============================================================================

# File patterns to ignore in file operation tracking
PATTERNS_TO_IGNORE_FOR_TRACKING = [
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "*.egg-info",
    ".tox",
    ".nox",
    "node_modules",
    ".next",
    ".nuxt",
    "dist",
    "build",
    ".DS_Store",
    "Thumbs.db",
    "*.log",
    "*.swp",
    "*.swo",
    "*~",
    "*.pyc",  # Python compiled bytecode files
    "*.pyo",  # Python optimized bytecode files
]

# File extensions to exclude when sharing (binary/large files)
SHARE_EXCLUDE_EXTENSIONS = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".bin",
        ".safetensors",
        ".log.zip",
        ".db",
        ".sqlite",
        ".sqlite3",
    },
)

# =============================================================================
# BINARY FILE EXTENSIONS
# =============================================================================

# Binary file extensions that should not be read by text-based tools
BINARY_FILE_EXTENSIONS = frozenset(
    {
        # Images
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".ico",
        ".svg",
        ".webp",
        ".tiff",
        ".tif",
        # Audio
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".aac",
        ".m4a",
        ".wma",
        # Video
        ".mp4",
        ".avi",
        ".mkv",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".mpg",
        ".mpeg",
        # Archives
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        # Executables and object files
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".o",
        ".a",
        ".class",
        ".jar",
        # Documents (binary formats)
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        # Data
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
        ".sqlite3",
        # Python compiled
        ".pyc",
        ".pyo",
        ".pyd",
        # Other
        ".wasm",
        ".safetensors",
        ".onnx",
        ".pb",
        ".h5",
        ".hdf5",
    },
)

# =============================================================================
# WORKSPACE FILE EXTENSIONS (for sharing)
# =============================================================================

# File extensions to include from workspace when sharing (text and previewable files)
WORKSPACE_INCLUDE_EXTENSIONS = frozenset(
    {
        # Text files
        ".txt",
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".py",
        ".js",
        ".ts",
        ".html",
        ".css",
        ".sh",
        ".toml",
        ".cfg",
        ".ini",
        ".xml",
        # Office documents (binary - handled specially for preview conversion)
        ".docx",
        ".pptx",
        ".xlsx",
        # PDF (already previewable)
        ".pdf",
    },
)

# Office document extensions that need PDF conversion for preview
OFFICE_DOCUMENT_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})

# =============================================================================
# SIZE LIMITS
# =============================================================================

# Maximum file size for sharing (50MB for text files)
# Using git push allows much larger files than API
MAX_FILE_SIZE_FOR_SHARING = 50_000_000

# Maximum file size for previewable binary files (75MB for pptx, pdf, images)
# These are prioritized for sharing since they're often the main deliverable
MAX_PREVIEWABLE_FILE_SIZE_FOR_SHARING = 75_000_000

# Maximum total size for sharing (500MB - git push supports large uploads)
# GitHub Gist via git push supports up to 100MB per file, generous total
MAX_TOTAL_SIZE_FOR_SHARING = 500_000_000

# Maximum number of files for sharing (290, leaving buffer from 300 gist limit)
MAX_FILES_FOR_SHARING = 290

# Extensions for previewable binary files (prioritized in sharing)
PREVIEWABLE_EXTENSIONS = {".pptx", ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Maximum items to log in workspace listings
MAX_LOG_ITEMS = 50

# Maximum directory depth for workspace logging
MAX_LOG_DEPTH = 3

# =============================================================================
# FRAMEWORK MCP SERVERS
# =============================================================================

# MCP servers that are part of MassGen's framework and should NOT be converted
# to code-based tools (discoverable in servers/ directory). These are either:
# - Automatically available built-in tools
# - Handled specially by the framework
# - Injected conditionally based on config flags
#
# Note: Server names may have agent-specific suffixes (e.g., "planning_agent_a"),
# so matching should check for prefix matches like server_name.startswith(f"{mcp}_")
FRAMEWORK_MCPS = frozenset(
    {
        "command_line",  # Command execution (execute_command tool)
        "workspace_tools",  # Workspace operations (file ops, media generation)
        "filesystem",  # Filesystem operations (read/write/edit files)
        "planning",  # Task planning MCP
        "memory",  # Memory management MCP
        "subagent",  # Subagent spawning (built-in when enabled)
        "skills",  # Skill discovery and reading MCP
        "massgen_checklist",  # Checklist-gated voting tool (must be a direct model tool)
        "massgen_quality_tools",  # Standalone quality tools MCP (massgen-refinery plugin)
        "massgen_workflow_tools",  # Standalone workflow tools MCP (massgen-refinery plugin)
        "massgen_media_tools",  # Standalone media tools MCP (massgen-refinery plugin)
        "massgen_checkpoint",  # Checkpoint coordination tool (main agent delegates to team)
        "massgen_checkpoint_standalone",  # Standalone checkpoint MCP exposed in-session (init+checkpoint)
    },
)

# =============================================================================
# TOOL RESULT EVICTION
# =============================================================================

# Token threshold for evicting large tool results to files
# Results exceeding this limit are saved to disk and replaced with a reference
TOOL_RESULT_EVICTION_THRESHOLD_TOKENS = 20_000

# Tokens to include as preview in the reference message
TOOL_RESULT_EVICTION_PREVIEW_TOKENS = 2_000

# Directory name for evicted results (within agent workspace)
EVICTED_RESULTS_DIR = ".tool_results"

# =============================================================================
# FILE EXTENSION TO LANGUAGE MAPPING
# =============================================================================

# Map file extensions to syntax highlighting/language identifiers
# Used by web UI for code highlighting and CLI for file type display
EXTENSION_TO_LANGUAGE = {
    # Python
    ".py": "python",
    ".pyi": "python",
    ".pyw": "python",
    # JavaScript/TypeScript
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    # Web
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    # Data formats
    ".json": "json",
    ".jsonc": "json",
    ".json5": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    # Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".fish": "fish",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    # Systems programming
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".zig": "zig",
    # JVM
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".groovy": "groovy",
    ".gradle": "groovy",
    # .NET
    ".cs": "csharp",
    ".fs": "fsharp",
    ".vb": "vb",
    # Mobile
    ".swift": "swift",
    ".m": "objective-c",
    ".mm": "objective-cpp",
    # Scripting
    ".rb": "ruby",
    ".php": "php",
    ".pl": "perl",
    ".pm": "perl",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
    ".jl": "julia",
    # Functional
    ".hs": "haskell",
    ".lhs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".lisp": "lisp",
    ".el": "lisp",
    ".scm": "scheme",
    ".rkt": "racket",
    # Database
    ".sql": "sql",
    ".psql": "sql",
    ".mysql": "sql",
    # Documentation
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".tex": "latex",
    ".adoc": "asciidoc",
    # Config files
    ".dockerfile": "dockerfile",
    ".gitignore": "gitignore",
    ".env": "dotenv",
    ".editorconfig": "ini",
    # Plain text
    ".txt": "plaintext",
    ".log": "plaintext",
    ".text": "plaintext",
}


def get_language_for_extension(extension: str) -> str:
    """Get the language identifier for a file extension.

    Args:
        extension: File extension including dot (e.g., '.py', '.js').

    Returns:
        Language identifier string, or 'plaintext' if unknown.
    """
    return EXTENSION_TO_LANGUAGE.get(extension.lower(), "plaintext")
