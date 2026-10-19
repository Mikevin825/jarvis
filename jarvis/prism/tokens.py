"""The design-token contract.

`design.md` carries a fenced ```yaml tokens block that this module parses,
validates, and renders into the Tailwind config and globals.css that the preview
app builds against. The block is the machine-readable half of the document; the
prose around it is for humans.

Validation is strict on purpose. A half-shaped token system produces half-shaped
mockups, and the failure is invisible until someone looks at the page — so a
missing or malformed block raises rather than falling back to defaults.

Fonts are validated against a curated catalog and a FORBIDDEN set. The forbidden
list exists because a handful of families have become visual shorthand for
"generic AI SaaS"; blocking them at parse time is cheaper than arguing with a
model about taste later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml


class TokenError(Exception):
    """The token block is missing, malformed, or invalid.

    Raising is the point: composing against a broken token system produces a
    broken page, and the error is far cheaper to read than the page.
    """


# -- the font catalog ------------------------------------------------------
#
# Curated for distinctiveness, ordered most distinctive first. A model picking
# from this list lands somewhere intentional; picking from "any Google Font"
# lands on Inter.

FONT_CATALOG: dict[str, list[str]] = {
    "display": [
        "Instrument Serif",
        "Fraunces",
        "Bricolage Grotesque",
        "Unbounded",
        "Syne",
        "Archivo Black",
        "Playfair Display",
        "DM Serif Display",
        "Cormorant Garamond",
        "Azeret Mono",
    ],
    "body": [
        "Inter Tight",
        "Geist",
        "Satoshi",
        "Manrope",
        "Outfit",
        "Work Sans",
        "IBM Plex Sans",
        "Public Sans",
        "Source Serif 4",
        "Newsreader",
    ],
    "mono": [
        "JetBrains Mono",
        "IBM Plex Mono",
        "Geist Mono",
        "Space Mono",
        "Fira Code",
        "Azeret Mono",
        "DM Mono",
        "Inconsolata",
    ],
}

ALL_FONTS = {name for names in FONT_CATALOG.values() for name in names}

# Families that signal "generic AI SaaS". Blocked at validation time rather than
# left to the model's judgement.
FORBIDDEN_FAMILIES = {
    "Space Grotesk",
    "Plus Jakarta Sans",
    "Poppins",
    "Montserrat",
    "Nunito",
    "Quicksand",
    "Raleway",
    "Rubik",
}

# shadcn's base-colour enum. The token block picks one; anything else is a typo.
SHADCN_BASE_COLORS = {"slate", "gray", "zinc", "neutral", "stone"}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class DesignTokens:
    """The parsed, validated design system."""

    fonts: dict[str, str]  # display / body / mono -> Google Font family name
    colors: dict[str, str]  # role -> #rrggbb
    radius: str  # e.g. "0.625rem"
    base_color: str  # shadcn base colour
    style: str = "new-york"  # shadcn style

    def font_families(self) -> list[str]:
        """Every distinct family, in display/body/mono order."""
        seen: list[str] = []
        for role in ("display", "body", "mono"):
            name = self.fonts.get(role)
            if name and name not in seen:
                seen.append(name)
        return seen


# -- parsing ---------------------------------------------------------------

_BLOCK = re.compile(
    r"```ya?ml\s+tokens\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def extract_token_block(text: str) -> str:
    """Pull the ```yaml tokens block out of a design.md, or raise."""
    match = _BLOCK.search(text or "")
    if not match:
        raise TokenError(
            "design.md has no ```yaml tokens block. The preview app is built "
            "from these tokens, so there is nothing to compose against. "
            "Re-run bootstrap or add the block by hand."
        )
    return match.group(1)


def parse_tokens(design_md: str) -> DesignTokens:
    """Parse and validate the token block from a design.md document.

    Raises TokenError on anything malformed. Every failure names the offending
    value, because this error is read by a human fixing a document.
    """
    raw = extract_token_block(design_md)
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise TokenError(f"the tokens block is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise TokenError("the tokens block must be a mapping, not a scalar or list.")

    # -- fonts
    fonts_raw = data.get("fonts")
    if not isinstance(fonts_raw, dict):
        raise TokenError("tokens.fonts must be a mapping with display/body/mono keys.")
    fonts: dict[str, str] = {}
    for role in ("display", "body", "mono"):
        name = fonts_raw.get(role)
        if not name:
            raise TokenError(f"tokens.fonts.{role} is missing.")
        name = str(name).strip()
        if name in FORBIDDEN_FAMILIES:
            raise TokenError(
                f"'{name}' is on the forbidden list — it reads as generic AI "
                f"SaaS. Pick a more distinctive family from the catalog."
            )
        if name not in ALL_FONTS:
            raise TokenError(
                f"'{name}' is not in the font catalog. Available for {role}: "
                f"{', '.join(FONT_CATALOG[role])}"
            )
        fonts[role] = name

    # -- colors
    colors_raw = data.get("colors")
    if not isinstance(colors_raw, dict) or not colors_raw:
        raise TokenError("tokens.colors must be a non-empty mapping of role -> hex.")
    colors: dict[str, str] = {}
    for role, value in colors_raw.items():
        value = str(value).strip()
        if not _HEX.match(value):
            raise TokenError(
                f"tokens.colors.{role} = '{value}' is not a #rrggbb hex string."
            )
        colors[str(role)] = value.lower()

    # A background and a foreground are the minimum for a coherent page.
    for required in ("background", "foreground"):
        if required not in colors:
            raise TokenError(
                f"tokens.colors.{required} is required — the preview app cannot "
                f"build a theme without it."
            )

    # -- radius
    radius = str(data.get("radius", "0.625rem")).strip()
    if not re.match(r"^[\d.]+(rem|px|em)$", radius):
        raise TokenError(f"tokens.radius = '{radius}' must be a length like 0.625rem.")

    # -- shadcn
    shadcn = data.get("shadcn") or {}
    if not isinstance(shadcn, dict):
        raise TokenError("tokens.shadcn must be a mapping.")
    base_color = str(shadcn.get("base_color", "neutral")).strip().lower()
    if base_color not in SHADCN_BASE_COLORS:
        raise TokenError(
            f"tokens.shadcn.base_color = '{base_color}' must be one of: "
            f"{', '.join(sorted(SHADCN_BASE_COLORS))}"
        )
    style = str(shadcn.get("style", "new-york")).strip().lower()

    return DesignTokens(
        fonts=fonts,
        colors=colors,
        radius=radius,
        base_color=base_color,
        style=style,
    )


# -- rendering -------------------------------------------------------------

def _hex_to_hsl_triplet(hex_color: str) -> str:
    """#rrggbb -> the bare 'H S% L%' shadcn CSS variables expect.

    shadcn's variables are HSL channels without the hsl() wrapper, because
    Tailwind composes them with opacity modifiers.
    """
    value = hex_color.lstrip("#")
    r = int(value[0:2], 16) / 255
    g = int(value[2:4], 16) / 255
    b = int(value[4:6], 16) / 255

    mx, mn = max(r, g, b), min(r, g, b)
    lightness = (mx + mn) / 2
    delta = mx - mn

    if delta == 0:
        hue = saturation = 0.0
    else:
        saturation = delta / (1 - abs(2 * lightness - 1))
        if mx == r:
            hue = 60 * (((g - b) / delta) % 6)
        elif mx == g:
            hue = 60 * (((b - r) / delta) + 2)
        else:
            hue = 60 * (((r - g) / delta) + 4)

    return f"{hue:.1f} {saturation * 100:.1f}% {lightness * 100:.1f}%"


def _role(tokens: DesignTokens, *names: str, default: str = "") -> str:
    """First matching colour role, so briefs can name roles loosely."""
    for name in names:
        if name in tokens.colors:
            return tokens.colors[name]
    return default


def render_globals_css(tokens: DesignTokens) -> str:
    """Render app/globals.css from the tokens.

    shadcn's CSS variables are derived from the brief's hex colours, so the
    mockups inherit the committed palette rather than the library default.
    """
    background = _role(tokens, "background", "bg")
    foreground = _role(tokens, "foreground", "fg", "text")
    accent = _role(tokens, "accent", "primary", default=foreground)
    muted = _role(tokens, "muted", default=background)
    border = _role(tokens, "border", default=muted)

    return f"""@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {{
  :root {{
    --background: {_hex_to_hsl_triplet(background)};
    --foreground: {_hex_to_hsl_triplet(foreground)};

    --card: {_hex_to_hsl_triplet(muted)};
    --card-foreground: {_hex_to_hsl_triplet(foreground)};

    --popover: {_hex_to_hsl_triplet(muted)};
    --popover-foreground: {_hex_to_hsl_triplet(foreground)};

    --primary: {_hex_to_hsl_triplet(accent)};
    --primary-foreground: {_hex_to_hsl_triplet(background)};

    --secondary: {_hex_to_hsl_triplet(muted)};
    --secondary-foreground: {_hex_to_hsl_triplet(foreground)};

    --muted: {_hex_to_hsl_triplet(muted)};
    --muted-foreground: {_hex_to_hsl_triplet(foreground)};

    --accent: {_hex_to_hsl_triplet(accent)};
    --accent-foreground: {_hex_to_hsl_triplet(background)};

    --destructive: 0 72% 51%;
    --destructive-foreground: {_hex_to_hsl_triplet(background)};

    --border: {_hex_to_hsl_triplet(border)};
    --input: {_hex_to_hsl_triplet(border)};
    --ring: {_hex_to_hsl_triplet(accent)};

    --radius: {tokens.radius};
  }}
}}

@layer base {{
  * {{
    @apply border-border;
  }}
  body {{
    @apply bg-background text-foreground;
  }}
}}
"""


def render_tailwind_config(tokens: DesignTokens) -> str:
    """Render tailwind.config.ts wired to the CSS variables."""
    return f"""import type {{ Config }} from "tailwindcss";

const config: Config = {{
  darkMode: ["class"],
  content: [
    "./app/**/*.{{ts,tsx}}",
    "./components/**/*.{{ts,tsx}}",
    "./lib/**/*.{{ts,tsx}}",
    "./prism/**/*.md",
  ],
  theme: {{
    container: {{
      center: true,
      padding: "2rem",
      screens: {{ "2xl": "1400px" }},
    }},
    extend: {{
      fontFamily: {{
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      }},
      colors: {{
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {{
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        }},
        secondary: {{
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        }},
        muted: {{
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        }},
        accent: {{
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        }},
        card: {{
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        }},
      }},
      borderRadius: {{
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      }},
    }},
  }},
  plugins: [require("tailwindcss-animate")],
}};

export default config;
"""


def render_components_json(tokens: DesignTokens) -> str:
    """Render components.json so shadcn add uses the brief's base colour."""
    import json

    return json.dumps(
        {
            "$schema": "https://ui.shadcn.com/schema.json",
            "style": tokens.style,
            "rsc": True,
            "tsx": True,
            "tailwind": {
                "config": "tailwind.config.ts",
                "css": "app/globals.css",
                "baseColor": tokens.base_color,
                "cssVariables": True,
                "prefix": "",
            },
            "aliases": {
                "components": "@/components",
                "utils": "@/lib/utils",
                "ui": "@/components/ui",
                "lib": "@/lib",
                "hooks": "@/hooks",
            },
            "iconLibrary": "lucide",
        },
        indent=2,
    ) + "\n"


def render_fonts_ts(tokens: DesignTokens) -> str:
    """Render lib/fonts.ts calling next/font/google with the chosen families."""
    lines = ['import { ' + ", ".join(
        _font_import_name(name) for name in tokens.font_families()
    ) + ' } from "next/font/google";', ""]

    for role in ("display", "body", "mono"):
        name = tokens.fonts[role]
        ident = _font_import_name(name)
        lines.append(f'export const {ident} = {ident}({{')
        lines.append('  subsets: ["latin"],')
        lines.append(f'  variable: "--font-{role}",')
        lines.append('  display: "swap",')
        lines.append("});")
        lines.append("")

    lines.append("export const fontVariables = [")
    for role in ("display", "body", "mono"):
        lines.append(f"  {_font_import_name(tokens.fonts[role])}.variable,")
    lines.append('].join(" ");')
    lines.append("")
    return "\n".join(lines)


def _font_import_name(family: str) -> str:
    """'Instrument Serif' -> 'Instrument_Serif' (next/font's import form)."""
    return family.replace(" ", "_")


def render_default_tokens_yaml() -> str:
    """The token block bootstrap writes when it cannot infer anything.

    Concrete values, not placeholders: a skeleton with TODO values produces
    skeleton mockups, so the first dispatch needs something real to compose
    against. The user iterates from here.
    """
    return """```yaml tokens
fonts:
  display: Instrument Serif
  body: Inter Tight
  mono: JetBrains Mono

colors:
  background: "#0a0a0b"
  foreground: "#ededf0"
  muted: "#16161a"
  border: "#26262c"
  accent: "#f5a524"

radius: 0.625rem

shadcn:
  base_color: neutral
  style: new-york
```"""
