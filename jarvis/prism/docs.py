"""The document layer.

Every read and write Prism performs on a project goes through here, so path
containment is enforced in one place rather than remembered at each call site.
A design agent that can write anywhere is a design agent that can clobber the
user's source tree.

The three documents and their volatility:

    design.md             PUBLIC, STABLE          the design system
    .prism/brief.md       PRIVATE, EVOLVING       strategic memory
    features/<slug>.md    PUBLIC, RAPIDLY EVOLVING per-feature spec
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .tokens import (
    DesignTokens,
    TokenError,
    parse_tokens,
    render_default_tokens_yaml,
)

PRISM_DIR = ".prism"
BRIEF_FILE = "brief.md"
DESIGN_FILE = "design.md"
FEATURES_DIR = "features"
REFERENCES_DIR = "references"
PREVIEW_DIR = "preview"

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PrismPathError(Exception):
    """A path escaped the project root, or a slug was malformed.

    Raised rather than corrected: silently rewriting a bad path hides the bug
    that produced it.
    """


def slugify(value: str) -> str:
    """A filesystem-safe kebab-case slug. Raises if nothing survives."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    if not slug or not _SLUG.match(slug):
        raise PrismPathError(f"cannot make a slug from {value!r}")
    return slug


def assert_within_project(path: Path, project_root: Path) -> Path:
    """Resolve `path` and confirm it sits inside `project_root`.

    The single containment gate. Every helper below routes through it, so a
    traversal bug can only be introduced in one place.
    """
    root = project_root.resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise PrismPathError(
            f"path {path} resolves outside the project root {root}."
        )
    return resolved


def resolve_project_root(slug: str, projects: dict[str, str]) -> Path:
    """Map a project slug to its filesystem root.

    `projects` comes from config.yaml (`prism.projects`), so pointing Prism at a
    new project is a config edit, never a code change.
    """
    if not _SLUG.match(slug or ""):
        raise PrismPathError(f"{slug!r} is not a valid project slug")
    raw = projects.get(slug)
    if not raw:
        known = ", ".join(sorted(projects)) or "(none configured)"
        raise PrismPathError(
            f"no project named '{slug}'. Configured projects: {known}. "
            f"Add it under prism.projects in config.yaml."
        )
    root = Path(raw).expanduser()
    if not root.exists():
        raise PrismPathError(f"project '{slug}' points at {root}, which does not exist.")
    return root.resolve()


# -- reading ---------------------------------------------------------------

def read_project_file(slug: str, relative: str, projects: dict[str, str]) -> str:
    """Read a file inside a project. Raises if it is missing or escapes."""
    root = resolve_project_root(slug, projects)
    path = assert_within_project(root / relative, root)
    if not path.exists():
        raise PrismPathError(f"{relative} does not exist in project '{slug}'.")
    return path.read_text(encoding="utf-8")


def list_project_files(
    slug: str,
    projects: dict[str, str],
    relative: str = ".",
    pattern: str = "*",
    limit: int = 200,
) -> list[str]:
    """List files under a project-relative directory."""
    root = resolve_project_root(slug, projects)
    base = assert_within_project(root / relative, root)
    if not base.exists():
        return []
    out: list[str] = []
    for path in sorted(base.glob(pattern)):
        if path.is_file():
            out.append(str(path.relative_to(root)))
        if len(out) >= limit:
            break
    return out


def read_design_doc(slug: str, projects: dict[str, str]) -> str:
    return read_project_file(slug, DESIGN_FILE, projects)


def read_brief(slug: str, projects: dict[str, str]) -> str:
    return read_project_file(slug, f"{PRISM_DIR}/{BRIEF_FILE}", projects)


def read_feature_doc(slug: str, feature: str, projects: dict[str, str]) -> str:
    return read_project_file(slug, f"{FEATURES_DIR}/{slugify(feature)}.md", projects)


def load_tokens(slug: str, projects: dict[str, str]) -> DesignTokens:
    """Read and parse a project's design tokens, or raise.

    Callers should let TokenError propagate with its message intact: it names
    the offending value, which is what the human fixing the document needs.
    """
    return parse_tokens(read_design_doc(slug, projects))


# -- writing ---------------------------------------------------------------

def _write(path: Path, content: str, root: Path) -> Path:
    safe = assert_within_project(path, root)
    safe.parent.mkdir(parents=True, exist_ok=True)
    safe.write_text(content, encoding="utf-8")
    return safe


def write_design_doc(slug: str, content: str, projects: dict[str, str]) -> Path:
    """Write design.md. Validates the token block before committing.

    A design.md whose tokens do not parse is worse than none at all, so the
    document is rejected rather than written and discovered later.
    """
    parse_tokens(content)  # raises TokenError; nothing is written if it does
    root = resolve_project_root(slug, projects)
    return _write(root / DESIGN_FILE, content, root)


def write_brief(slug: str, content: str, projects: dict[str, str]) -> Path:
    root = resolve_project_root(slug, projects)
    return _write(root / PRISM_DIR / BRIEF_FILE, content, root)


def write_feature_doc(
    slug: str, feature: str, content: str, projects: dict[str, str]
) -> Path:
    root = resolve_project_root(slug, projects)
    return _write(root / FEATURES_DIR / f"{slugify(feature)}.md", content, root)


# -- bootstrap -------------------------------------------------------------

def _scan_repo(root: Path) -> dict:
    """A short, cheap scan so the starter documents are not generic.

    Deliberately shallow: package.json, README, and any CSS. Enough to make the
    first design.md plausible, not a full analysis.
    """
    found: dict = {"name": root.name, "stack": [], "readme": "", "css": []}

    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            found["name"] = data.get("name") or found["name"]
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            found["stack"] = sorted(deps)[:20]
        except (json.JSONDecodeError, OSError):
            pass

    for candidate in ("README.md", "readme.md", "README"):
        path = root / candidate
        if path.exists():
            try:
                found["readme"] = path.read_text(encoding="utf-8")[:600]
            except OSError:
                pass
            break

    try:
        found["css"] = [str(p.relative_to(root)) for p in root.glob("*.css")][:5]
    except OSError:
        pass

    return found


def _design_doc_template(name: str, scan: dict) -> str:
    """A concrete starter design.md.

    Committed values, not placeholders — see the note in tokens.py.
    """
    stack = ", ".join(scan.get("stack") or []) or "not detected"
    return f"""# {name} — Design System

This is the stable design system for **{name}**. It changes rarely and
deliberately. The token block below is machine-read by the preview app; the
prose around it is for people.

Detected stack: {stack}

## Type

Three roles, each doing one job. The display face carries the wordmark and
headlines; the body face is for reading; the mono face is for data, labels and
marginalia.

## Colour

A near-black ground with a single warm accent. One accent, used precisely —
never as a fill, never decoratively. Everything else is a neutral.

## Motion

Motion is continuous, not one-shot: something on the page is always moving
slowly. Entrances are brief and never block reading.

## Rules

- One accent colour. If everything is accented, nothing is.
- Mono for data and marginalia, never for body copy.
- Texture is visible (opacity 0.4+) or it is not there at all.

{render_default_tokens_yaml()}
"""


def _brief_template(name: str, scan: dict) -> str:
    readme = (scan.get("readme") or "").strip()
    readme_block = f"\n## Repo notes\n\n{readme}\n" if readme else ""
    return f"""# {name} — Design Brief

Private working memory. This evolves as the work does, and it is what stops
each dispatch re-litigating decisions already made.

## Positioning

What this product is, and who it is for. One paragraph.

## Persona

Who is looking at the screen, and in what frame of mind.

## Business goals

What the design is in service of. A beautiful page that does not move a number
is a failed page.

## Brand language

The vocabulary, the tone, the metaphors that are on-brand — and the ones that
are not.

## Standing design decisions

Decisions already made, with the reasoning, so they are not reopened.

- **Forbidden moves:** list them explicitly. A brief that only says what to do
  gets what it does not want.

## Ongoing themes

Threads currently running through the work.

## Bootstrap notes

Generated from a short repo scan. Replace the guesses with the truth.
{readme_block}"""


def _feature_template(feature: str, name: str) -> str:
    return f"""# {feature.replace("-", " ").title()}

Per-feature spec for **{name}**. This changes fast — it is the working document
for one piece of the product.

## Purpose

What this screen or flow is for, in one or two sentences.

## Audience

Who uses it, and what they already know when they arrive.

## Required elements

What must appear. Be specific: the composition step reads this literally.

## Open questions

Unresolved decisions. Anything here is a candidate for the brief once settled.

## Mockups

Composed screens live in `.prism/preview/app/{feature}/`. This section records
which exist and what each one is for.
"""


def bootstrap_project(slug: str, projects: dict[str, str], force: bool = False) -> dict:
    """Create the three starter documents for a project.

    Idempotent: existing documents are left alone unless `force` is set, so a
    re-dispatch never discards work the user has done by hand.

    Returns a dict describing what was written and what was skipped.
    """
    root = resolve_project_root(slug, projects)
    scan = _scan_repo(root)
    name = scan.get("name") or slug

    written: list[str] = []
    skipped: list[str] = []

    design_path = root / DESIGN_FILE
    if force or not design_path.exists():
        _write(design_path, _design_doc_template(name, scan), root)
        written.append(DESIGN_FILE)
    else:
        skipped.append(DESIGN_FILE)

    brief_path = root / PRISM_DIR / BRIEF_FILE
    if force or not brief_path.exists():
        _write(brief_path, _brief_template(name, scan), root)
        written.append(f"{PRISM_DIR}/{BRIEF_FILE}")
    else:
        skipped.append(f"{PRISM_DIR}/{BRIEF_FILE}")

    features_dir = root / FEATURES_DIR
    features_dir.mkdir(parents=True, exist_ok=True)
    (root / PRISM_DIR / REFERENCES_DIR).mkdir(parents=True, exist_ok=True)

    # The design.md we just wrote must actually parse. If it does not, the
    # bootstrap is broken and the user should hear it now, not at dispatch time.
    parse_tokens(design_path.read_text(encoding="utf-8"))

    return {
        "project": slug,
        "root": str(root),
        "written": written,
        "skipped": skipped,
        "detected_stack": scan.get("stack") or [],
    }


__all__ = [
    "BRIEF_FILE",
    "DESIGN_FILE",
    "FEATURES_DIR",
    "PREVIEW_DIR",
    "PRISM_DIR",
    "REFERENCES_DIR",
    "PrismPathError",
    "TokenError",
    "assert_within_project",
    "bootstrap_project",
    "list_project_files",
    "load_tokens",
    "read_brief",
    "read_design_doc",
    "read_feature_doc",
    "read_project_file",
    "resolve_project_root",
    "slugify",
    "write_brief",
    "write_design_doc",
    "write_feature_doc",
]
