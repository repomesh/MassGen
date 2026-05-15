# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
from datetime import datetime

import sphinx

# Add project root to Python path
sys.path.insert(0, os.path.abspath("../.."))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "MassGen"
copyright = f"{datetime.now().year}, MassGen Team"
author = "MassGen Team"
release = "0.1.0"
version = "0.1.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.githubpages",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
]

# Add optional extensions if available
try:
    extensions.append("myst_parser")
except ImportError:
    print("Warning: myst_parser not installed. Markdown support disabled.")

try:
    extensions.append("sphinx_copybutton")
except ImportError:
    print("Warning: sphinx_copybutton not installed.")

try:
    extensions.append("sphinx_design")
except ImportError:
    print("Warning: sphinx_design not installed. Grid support disabled.")

try:
    _sphinx_version = getattr(sphinx, "version_info", (0, 0, 0))
    _hoverxref_supported = tuple(_sphinx_version[:2]) < (9, 0)
except Exception:
    _hoverxref_supported = False

_hoverxref_enabled = False
if _hoverxref_supported:
    try:
        extensions.append("hoverxref.extension")
        _hoverxref_enabled = True
    except ImportError:
        print("Warning: sphinx-hoverxref not installed. Glossary tooltips disabled.")
else:
    print("Warning: sphinx-hoverxref currently disabled for Sphinx 9+ compatibility.")

try:
    extensions.append("sphinx_tabs.tabs")
except ImportError:
    print("Warning: sphinx-tabs not installed. Tabbed content disabled.")

# MyST parser configuration
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "html_admonition",
    "html_image",
    # "linkify",  # Requires linkify-it-py package
    "replacements",
    "smartquotes",
    "strikethrough",
    "substitution",
    "tasklist",
]

# Auto-generate heading anchors for deep linking
myst_heading_anchors = 3

# Configure heading slug generation to handle emojis better
myst_heading_slug_func = None  # Use default slugification

# Suppress duplicate label warnings for auto-generated TOC links
suppress_warnings = ["myst.header"]

# Configure MyST to parse markdown files
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
# Suppress MyST warnings for missing cross-references in markdown files
suppress_warnings = [
    "myst.xref_missing",  # Suppress missing cross-reference warnings in MyST
]

templates_path = ["_templates"]
exclude_patterns = ["case_studies"]  # Exclude standalone HTML from Sphinx processing

# Files in _extra/ are copied verbatim to the build output root (e.g. llms.txt).
# Use this for files that need to live at the site root, not under /_static/.
html_extra_path = ["_extra"]

# Autodoc settings
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# Try to use sphinx_book_theme, fall back to alabaster if not available
try:
    html_theme = "sphinx_book_theme"
except ImportError:
    html_theme = "alabaster"
    print("Warning: sphinx_book_theme not installed. Using alabaster theme.")
html_static_path = ["_static"]

# Custom CSS files
html_css_files = [
    "css/theme-images.css",
]

# Theme options
html_theme_options = {
    "logo": {
        "image_light": "_static/images/logo.png",
        "image_dark": "_static/images/logo-dark.png",
    },
    "logo_only": False,
    "display_version": True,
    "prev_next_buttons_location": "bottom",
    "style_external_links": False,
    "style_nav_header_background": "#2980B9",
    # TOC options
    "collapse_navigation": False,
    "sticky_navigation": True,
    "navigation_depth": 4,
    "includehidden": True,
    "titles_only": False,
    # Social and community links
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/Leezekun/MassGen",
            "icon": "fa-brands fa-github",
            "type": "fontawesome",
        },
        {
            "name": "Discord",
            "url": "https://discord.massgen.ai",
            "icon": "fa-brands fa-discord",
            "type": "fontawesome",
        },
        {
            "name": "X (Twitter)",
            "url": "https://x.massgen.ai",
            "icon": "fa-brands fa-x-twitter",
            "type": "fontawesome",
        },
        {
            "name": "LinkedIn",
            "url": "https://www.linkedin.com/company/massgen-ai",
            "icon": "fa-brands fa-linkedin",
            "type": "fontawesome",
        },
    ],
}

# Logo and favicon (fallback if theme doesn't support logo dict)
# html_logo = "../../assets/logo.png"
# html_favicon = "../../assets/logo.png"
html_favicon = "../../assets/favicon.png"

# Additional HTML context
html_context = {
    "display_github": True,
    "github_user": "Leezekun",
    "github_repo": "MassGen",
    "github_version": "main",
    "conf_py_path": "/docs/source/",
}

# Copy button configuration
copybutton_prompt_text = r">>> |\.\.\. |\$ |In \[\d*\]: | {2,5}\.\.\.: | {5,8}: "
copybutton_prompt_is_regexp = True

# Intersphinx mapping
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
}

# Show todo notes
todo_include_todos = True

# Hoverxref configuration for glossary tooltips
if _hoverxref_enabled:
    hoverxref_auto_ref = True
    hoverxref_domains = ["std"]
    hoverxref_role_types = {
        "term": "tooltip",  # Show glossary terms as tooltips on hover
    }
    hoverxref_tooltip_maxwidth = 600
    hoverxref_tooltip_theme = "tooltipster-shadow"


# -- llms-full.txt generation (https://llmstxt.org) --------------------------
# At build-finish, walk the curated documentation roots and concatenate their
# source files into a single llms-full.txt at the build output root. The
# hand-curated index lives at _extra/llms.txt and is copied via html_extra_path.

_LLMS_FULL_ROOTS = ("quickstart", "user_guide", "reference")
_LLMS_FULL_EXTS = (".rst", ".md")


def _generate_llms_full_txt(app, exception):
    if exception is not None:
        return
    if app.builder.name != "html":
        return

    source_root = os.path.abspath(app.srcdir)
    out_path = os.path.join(app.outdir, "llms-full.txt")

    header = (
        "# MassGen — full documentation dump\n\n"
        "> Concatenated source of MassGen's quickstart, user guide, and reference\n"
        "> documentation. For a curated index see /llms.txt. Generated at\n"
        "> Sphinx build time from docs/source/{quickstart,user_guide,reference}.\n\n"
    )

    sections = []
    for root in _LLMS_FULL_ROOTS:
        root_path = os.path.join(source_root, root)
        if not os.path.isdir(root_path):
            continue
        for dirpath, _dirnames, filenames in os.walk(root_path):
            for name in sorted(filenames):
                if not name.endswith(_LLMS_FULL_EXTS):
                    continue
                file_path = os.path.join(dirpath, name)
                rel_path = os.path.relpath(file_path, source_root)
                try:
                    with open(file_path, encoding="utf-8") as fh:
                        body = fh.read()
                except (OSError, UnicodeDecodeError):
                    continue
                sections.append((rel_path, body))

    sections.sort(key=lambda item: item[0])

    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(header)
            for rel_path, body in sections:
                fh.write(f"\n\n---\n\n## {rel_path}\n\n")
                fh.write(body)
                if not body.endswith("\n"):
                    fh.write("\n")
    except OSError as exc:
        print(f"Warning: failed to write llms-full.txt: {exc}")
        return

    print(f"Wrote llms-full.txt ({len(sections)} files) -> {out_path}")


def setup(app):
    app.connect("build-finished", _generate_llms_full_txt)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
