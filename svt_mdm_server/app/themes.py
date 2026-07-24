"""Interface theme catalog — the single source of truth for dashboard and agent.

A *theme* is a small set of colour tokens plus a font family. The operator picks
one on the dashboard (persisted via ``app.prefs``); the dashboard renders it as
CSS custom properties, and device agents fetch the same tokens (see
``GET /api/theme``) so the phone app matches the server.

Keep this catalogue in sync with the Android agent's ``ui/theme/Themes.kt`` and
with ``shared/protocol.md``.

Token contract (every theme defines all of these):

    bg          page background
    panel       card / surface background
    panel2      secondary surface (inputs, tracks)
    text        primary foreground
    muted       secondary / dimmed foreground
    accent      primary action / brand colour
    accent_text foreground drawn *on* the accent (buttons)
    ok          success
    warn        warning
    danger      destructive / error
    border      hairline borders

``font`` is one of ``system``, ``mono`` or ``condensed`` (LCARS).
"""

from __future__ import annotations

from dataclasses import dataclass, field

FONT_STACKS: dict[str, str] = {
    "system": "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    "mono": (
        "ui-monospace, 'SF Mono', 'JetBrains Mono', 'Fira Code', Menlo, "
        "Consolas, monospace"
    ),
    "condensed": (
        "'Antonio', 'Oswald', 'Roboto Condensed', 'Arial Narrow', "
        "sans-serif"
    ),
}


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    description: str
    dark: bool
    font: str  # key into FONT_STACKS
    tokens: dict[str, str] = field(default_factory=dict)

    @property
    def font_stack(self) -> str:
        return FONT_STACKS.get(self.font, FONT_STACKS["system"])

    def css_vars(self) -> str:
        """The theme as a block of CSS custom-property declarations."""
        pairs = {
            "--bg": self.tokens["bg"],
            "--panel": self.tokens["panel"],
            "--panel-2": self.tokens["panel2"],
            "--text": self.tokens["text"],
            "--muted": self.tokens["muted"],
            "--accent": self.tokens["accent"],
            "--accent-text": self.tokens["accent_text"],
            "--ok": self.tokens["ok"],
            "--warn": self.tokens["warn"],
            "--danger": self.tokens["danger"],
            "--border": self.tokens["border"],
            "--font": self.font_stack,
        }
        return " ".join(f"{k}: {v};" for k, v in pairs.items())

    def as_api(self) -> dict:
        """Shape returned to agents from ``GET /api/theme``."""
        return {
            "id": self.id,
            "name": self.name,
            "dark": self.dark,
            "font": self.font,
            "colors": dict(self.tokens),
        }


def _t(id, name, description, dark, font, **tokens) -> Theme:
    return Theme(id=id, name=name, description=description, dark=dark, font=font, tokens=tokens)


# Ordered catalogue. The first entry is the default.
_CATALOG: tuple[Theme, ...] = (
    _t(
        "midnight", "Midnight", "Deep slate-blue dark theme (default).",
        dark=True, font="system",
        bg="#0f1419", panel="#1a2027", panel2="#222a33", text="#e6edf3",
        muted="#8b949e", accent="#2f81f7", accent_text="#ffffff",
        ok="#2ea043", warn="#d29922", danger="#f85149", border="#30363d",
    ),
    _t(
        "graphite", "Graphite", "Neutral monochrome dark theme.",
        dark=True, font="system",
        bg="#131417", panel="#1c1e22", panel2="#26292f", text="#e8e8ea",
        muted="#9096a0", accent="#b0b8c4", accent_text="#131417",
        ok="#57a05a", warn="#c99a3a", danger="#d9615a", border="#2e323a",
    ),
    _t(
        "nord", "Nord", "Cool, muted arctic palette.",
        dark=True, font="system",
        bg="#2e3440", panel="#3b4252", panel2="#434c5e", text="#eceff4",
        muted="#aab2c0", accent="#88c0d0", accent_text="#2e3440",
        ok="#a3be8c", warn="#ebcb8b", danger="#bf616a", border="#4c566a",
    ),
    _t(
        "nebula", "Nebula", "Modern indigo/violet dark theme.",
        dark=True, font="system",
        bg="#14121f", panel="#1e1b2e", panel2="#2a2640", text="#ece9f5",
        muted="#a49fc0", accent="#8b5cf6", accent_text="#ffffff",
        ok="#34d399", warn="#fbbf24", danger="#fb7185", border="#332d4d",
    ),
    _t(
        "terminal", "Terminal", "Console-green on near-black, monospace.",
        dark=True, font="mono",
        bg="#0a140e", panel="#10201a", panel2="#182b22", text="#d7f5e3",
        muted="#7fae93", accent="#4ade80", accent_text="#04120b",
        ok="#22c55e", warn="#eab308", danger="#ef4444", border="#24483a",
    ),
    _t(
        "aurora", "Aurora", "Clean professional light theme.",
        dark=False, font="system",
        bg="#f6f8fa", panel="#ffffff", panel2="#eef1f4", text="#1f2328",
        muted="#656d76", accent="#0969da", accent_text="#ffffff",
        ok="#1a7f37", warn="#9a6700", danger="#cf222e", border="#d0d7de",
    ),
    _t(
        "solar", "Solar", "Warm Solarized-light palette.",
        dark=False, font="system",
        bg="#fdf6e3", panel="#eee8d5", panel2="#e7e0cc", text="#073642",
        muted="#657b83", accent="#268bd2", accent_text="#fdf6e3",
        ok="#859900", warn="#b58900", danger="#dc322f", border="#ddd6c1",
    ),
    _t(
        "sandstone", "Sandstone", "Soft, warm paper-and-terracotta light theme.",
        dark=False, font="system",
        bg="#f4ecd8", panel="#fffaf0", panel2="#efe4cc", text="#433422",
        muted="#7c6a4d", accent="#b5651d", accent_text="#fffaf0",
        ok="#6a8a3f", warn="#b9822b", danger="#b23a2f", border="#ddcca6",
    ),
    _t(
        "lcars", "LCARS", "Starfleet library computer — amber pills on black.",
        dark=True, font="condensed",
        bg="#000000", panel="#0b0b0b", panel2="#161616", text="#ffcc99",
        muted="#cc99cc", accent="#ff9900", accent_text="#000000",
        ok="#99cc99", warn="#ffcc00", danger="#cc6666", border="#ff9900",
    ),
)

THEMES: dict[str, Theme] = {t.id: t for t in _CATALOG}
DEFAULT_THEME_ID: str = _CATALOG[0].id


def all_themes() -> list[Theme]:
    """Every theme, in catalogue (display) order."""
    return list(_CATALOG)


def get_theme(theme_id: str | None) -> Theme:
    """Resolve a theme id, falling back to the default for unknown/empty ids."""
    return THEMES.get(theme_id or "", THEMES[DEFAULT_THEME_ID])
