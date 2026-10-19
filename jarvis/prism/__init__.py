"""Prism — the head-of-design sub-agent.

Prism turns a design brief into a real Next.js screen. It is deliberately not
"ask the model to write HTML": modern design quality comes from composing
high-quality primitives, so Prism scaffolds a per-project Next.js + Tailwind +
shadcn app and composes screens into it.

The three-tier document model, per project:

    <project>/
      design.md                  PUBLIC, STABLE   — the design system
      .prism/
        brief.md                 PRIVATE, EVOLVING — strategic memory
        references/<feature>/    reference screenshots
        preview/                 the mockup app (the composition substrate)
      features/<slug>.md         PUBLIC, RAPIDLY EVOLVING — per-feature spec

Everything here is read-and-write through the helpers in `docs.py`, which keep
every path inside the project root.
"""

from .docs import (
    PrismPathError,
    assert_within_project,
    bootstrap_project,
    list_project_files,
    read_project_file,
    resolve_project_root,
    write_brief,
    write_design_doc,
    write_feature_doc,
)
from .tokens import DesignTokens, TokenError, parse_tokens, render_globals_css, render_tailwind_config

__all__ = [
    "DesignTokens",
    "PrismPathError",
    "TokenError",
    "assert_within_project",
    "bootstrap_project",
    "list_project_files",
    "parse_tokens",
    "read_project_file",
    "render_globals_css",
    "render_tailwind_config",
    "resolve_project_root",
    "write_brief",
    "write_design_doc",
    "write_feature_doc",
]
