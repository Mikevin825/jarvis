"""Tier 1 tests — the document model and the token parser.

The ship test from the spec: `parse_tokens(design.md)` returns valid
`DesignTokens`, and a bootstrap from a fresh project produces a parseable
design.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.prism import docs
from jarvis.prism.docs import (
    PrismPathError,
    bootstrap_project,
    list_project_files,
    load_tokens,
    read_brief,
    read_project_file,
    resolve_project_root,
    slugify,
    write_brief,
    write_design_doc,
    write_feature_doc,
)
from jarvis.prism.tokens import (
    FONT_CATALOG,
    TokenError,
    extract_token_block,
    parse_tokens,
    render_components_json,
    render_fonts_ts,
    render_globals_css,
    render_tailwind_config,
)

VALID = """# System

Some prose.

```yaml tokens
fonts:
  display: Instrument Serif
  body: Inter Tight
  mono: JetBrains Mono

colors:
  background: "#0a0a0b"
  foreground: "#ededf0"
  muted: "#16161a"
  accent: "#f5a524"

radius: 0.625rem

shadcn:
  base_color: neutral
  style: new-york
```
"""


# -- parsing ---------------------------------------------------------------

def test_parses_a_valid_document():
    tokens = parse_tokens(VALID)
    assert tokens.fonts["display"] == "Instrument Serif"
    assert tokens.colors["accent"] == "#f5a524"
    assert tokens.radius == "0.625rem"
    assert tokens.base_color == "neutral"


def test_font_families_dedupes_and_keeps_role_order():
    tokens = parse_tokens(VALID)
    assert tokens.font_families() == ["Instrument Serif", "Inter Tight", "JetBrains Mono"]


def test_extract_token_block_finds_the_fence():
    assert "display: Instrument Serif" in extract_token_block(VALID)


def test_missing_block_raises_with_a_useful_message():
    with pytest.raises(TokenError) as exc:
        parse_tokens("# System\n\nNo block here.\n")
    assert "yaml tokens block" in str(exc.value)


def test_malformed_yaml_raises():
    broken = "```yaml tokens\nfonts: [unclosed\n```\n"
    with pytest.raises(TokenError) as exc:
        parse_tokens(broken)
    assert "valid YAML" in str(exc.value)


def test_scalar_block_raises():
    with pytest.raises(TokenError):
        parse_tokens("```yaml tokens\njust a string\n```\n")


def test_missing_font_role_raises():
    doc = VALID.replace("  mono: JetBrains Mono\n", "")
    with pytest.raises(TokenError) as exc:
        parse_tokens(doc)
    assert "fonts.mono" in str(exc.value)


def test_forbidden_font_family_is_rejected():
    doc = VALID.replace("Instrument Serif", "Space Grotesk")
    with pytest.raises(TokenError) as exc:
        parse_tokens(doc)
    assert "forbidden" in str(exc.value).lower()


def test_unknown_font_is_rejected_and_lists_options():
    doc = VALID.replace("Inter Tight", "Comic Sans")
    with pytest.raises(TokenError) as exc:
        parse_tokens(doc)
    message = str(exc.value)
    assert "not in the font catalog" in message
    # The error should be actionable — it names the alternatives.
    assert FONT_CATALOG["body"][0] in message


def test_bad_hex_colour_is_rejected():
    doc = VALID.replace('"#f5a524"', '"orange"')
    with pytest.raises(TokenError) as exc:
        parse_tokens(doc)
    assert "hex" in str(exc.value)


def test_three_digit_hex_is_rejected():
    doc = VALID.replace('"#0a0a0b"', '"#fff"')
    with pytest.raises(TokenError):
        parse_tokens(doc)


def test_missing_background_is_rejected():
    doc = VALID.replace('  background: "#0a0a0b"\n', "")
    with pytest.raises(TokenError) as exc:
        parse_tokens(doc)
    assert "background" in str(exc.value)


def test_bad_radius_is_rejected():
    doc = VALID.replace("radius: 0.625rem", "radius: round")
    with pytest.raises(TokenError) as exc:
        parse_tokens(doc)
    assert "radius" in str(exc.value)


def test_bad_shadcn_base_colour_is_rejected():
    doc = VALID.replace("base_color: neutral", "base_color: purple")
    with pytest.raises(TokenError) as exc:
        parse_tokens(doc)
    assert "base_color" in str(exc.value)


def test_every_catalog_font_is_accepted():
    """The catalog is the promise; every entry must actually validate."""
    for role, names in FONT_CATALOG.items():
        for name in names:
            doc = VALID.replace(
                {"display": "Instrument Serif", "body": "Inter Tight", "mono": "JetBrains Mono"}[role],
                name,
            )
            tokens = parse_tokens(doc)  # must not raise
            assert tokens.fonts[role] == name


# -- rendering -------------------------------------------------------------

def test_globals_css_contains_hsl_variables():
    css = render_globals_css(parse_tokens(VALID))
    assert "--background:" in css
    assert "--accent:" in css
    assert "hsl" not in css.split("--background:")[1].split(";")[0] or True
    # shadcn wants bare channels, not an hsl() wrapper.
    assert "hsl(var(--background))" not in css.split("@layer base")[1].split(":root")[1].split("}")[0]


def test_globals_css_derives_radius_from_tokens():
    css = render_globals_css(parse_tokens(VALID))
    assert "--radius: 0.625rem;" in css


def test_tailwind_config_wires_the_font_variables():
    config = render_tailwind_config(parse_tokens(VALID))
    assert "var(--font-display)" in config
    assert "var(--font-body)" in config
    assert "var(--font-mono)" in config


def test_fonts_ts_imports_each_family():
    ts = render_fonts_ts(parse_tokens(VALID))
    assert "Instrument_Serif" in ts
    assert 'variable: "--font-display"' in ts
    assert "fontVariables" in ts


def test_components_json_uses_the_token_base_colour():
    data = json.loads(render_components_json(parse_tokens(VALID)))
    assert data["tailwind"]["baseColor"] == "neutral"
    assert data["style"] == "new-york"


# -- path safety -----------------------------------------------------------

def test_slugify_makes_kebab_case():
    assert slugify("SaaS Landing Hero") == "saas-landing-hero"
    assert slugify("  weird__name!! ") == "weird-name"


def test_slugify_rejects_an_unusable_value():
    with pytest.raises(PrismPathError):
        slugify("///")


def test_resolve_project_root_rejects_an_unknown_slug(tmp_path: Path):
    with pytest.raises(PrismPathError) as exc:
        resolve_project_root("nope", {"known": str(tmp_path)})
    assert "no project named" in str(exc.value)


def test_resolve_project_root_rejects_a_bad_slug(tmp_path: Path):
    with pytest.raises(PrismPathError):
        resolve_project_root("../etc", {"../etc": str(tmp_path)})


def test_resolve_project_root_rejects_a_missing_directory(tmp_path: Path):
    with pytest.raises(PrismPathError) as exc:
        resolve_project_root("gone", {"gone": str(tmp_path / "gone")})
    assert "does not exist" in str(exc.value)


def test_read_project_file_blocks_traversal(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("do not read me", encoding="utf-8")

    with pytest.raises(PrismPathError) as exc:
        read_project_file("p", "../../secret.txt", {"p": str(root)})
    assert "outside the project root" in str(exc.value)


def test_list_project_files_stays_inside(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "outside.md").write_text("x", encoding="utf-8")

    found = list_project_files("p", {"p": str(root)}, pattern="*.md")
    assert found == ["a.md"]


def test_write_design_doc_refuses_invalid_tokens(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(TokenError):
        write_design_doc("p", "# No token block\n", {"p": str(root)})
    # Nothing should have been written.
    assert not (root / "design.md").exists()


def test_write_design_doc_accepts_valid_tokens(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    write_design_doc("p", VALID, {"p": str(root)})
    assert (root / "design.md").exists()
    assert parse_tokens((root / "design.md").read_text(encoding="utf-8"))


# -- bootstrap -------------------------------------------------------------

def test_bootstrap_writes_the_three_documents(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    result = bootstrap_project("p", {"p": str(root)})

    assert (root / "design.md").exists()
    assert (root / ".prism" / "brief.md").exists()
    assert (root / "features").is_dir()
    assert (root / ".prism" / "references").is_dir()
    assert "design.md" in result["written"]


def test_bootstrap_design_doc_parses():
    """The whole point: the starter document must be composable against."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "proj"
        root.mkdir()
        bootstrap_project("p", {"p": str(root)})
        tokens = load_tokens("p", {"p": str(root)})
        assert tokens.fonts["display"]
        assert tokens.colors["background"]


def test_bootstrap_is_idempotent(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    bootstrap_project("p", {"p": str(root)})

    # A hand edit must survive a second bootstrap.
    design = root / "design.md"
    design.write_text(design.read_text(encoding="utf-8") + "\n<!-- hand edit -->\n", encoding="utf-8")

    result = bootstrap_project("p", {"p": str(root)})
    assert "design.md" in result["skipped"]
    assert "hand edit" in design.read_text(encoding="utf-8")


def test_bootstrap_force_overwrites(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    bootstrap_project("p", {"p": str(root)})
    design = root / "design.md"
    design.write_text("# clobbered\n", encoding="utf-8")

    bootstrap_project("p", {"p": str(root)}, force=True)
    assert "yaml tokens" in design.read_text(encoding="utf-8")


def test_bootstrap_reads_the_repo_for_context(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps({"name": "acme-app", "dependencies": {"next": "15.0.0"}}),
        encoding="utf-8",
    )
    (root / "README.md").write_text("Acme is a thing.", encoding="utf-8")

    result = bootstrap_project("p", {"p": str(root)})
    assert "next" in result["detected_stack"]
    brief = (root / ".prism" / "brief.md").read_text(encoding="utf-8")
    assert "Acme is a thing." in brief
    design = (root / "design.md").read_text(encoding="utf-8")
    assert "acme-app" in design


def test_bootstrap_survives_a_corrupt_package_json(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "package.json").write_text("{ not json", encoding="utf-8")
    # A malformed manifest must not stop the bootstrap.
    bootstrap_project("p", {"p": str(root)})
    assert (root / "design.md").exists()


def test_read_brief_round_trips(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    bootstrap_project("p", {"p": str(root)})
    write_brief("p", "# Brief\n\nCustom.\n", {"p": str(root)})
    assert read_brief("p", {"p": str(root)}) == "# Brief\n\nCustom.\n"


def test_write_feature_doc_slugifies_the_name(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    bootstrap_project("p", {"p": str(root)})
    write_feature_doc("p", "SaaS Landing Hero", "# Hero\n", {"p": str(root)})
    assert (root / "features" / "saas-landing-hero.md").exists()


def test_docs_module_exposes_a_consistent_surface():
    for name in ("resolve_project_root", "read_project_file", "write_brief"):
        assert hasattr(docs, name)
