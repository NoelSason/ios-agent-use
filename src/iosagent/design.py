"""Design-to-screen support.

The workflow this exists for: someone hands the agent a design file, the agent
implements it in SwiftUI, and then has to answer "does the built screen actually
look like the design?" -- on a device, not in its imagination.

Pixel-diffing a mockup against a real screenshot is the wrong tool: fonts,
insets and safe areas differ legitimately. What helps instead is a side-by-side
at matched scale, plus a few things that can be checked objectively -- the
colour palette, and whether the text in the design shows up in the accessibility
tree of the built screen.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import png
from .png import Image

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)


class DesignError(Exception):
    pass


def find_browser() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("chromium") or shutil.which("google-chrome")
    if found:
        return found
    raise DesignError(
        "no Chrome-family browser found, so design files cannot be rendered. "
        "Install Google Chrome, or render the design yourself and pass the PNG "
        "to `iosagent compare`."
    )


def render(source: Path, out: Path, *, width: int = 1600, height: int = 1200,
           wait_ms: int = 2500) -> Path:
    """Screenshot a local HTML file (a .dc.html canvas, or any page)."""
    browser = find_browser()
    out.parent.mkdir(parents=True, exist_ok=True)
    url = source if str(source).startswith(("http://", "https://")) \
        else Path(source).resolve().as_uri()
    proc = subprocess.run(
        [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--window-size={width},{height}",
         f"--virtual-time-budget={wait_ms}",
         f"--screenshot={out}", str(url)],
        capture_output=True, text=True, timeout=180,
    )
    if not out.exists():
        raise DesignError(f"the browser produced no screenshot:\n{proc.stderr[-1500:]}")
    return out


# ---------------------------------------------------------------------------
# palette
# ---------------------------------------------------------------------------

@dataclass
class Swatch:
    rgb: tuple[int, int, int]
    coverage: float

    @property
    def hex(self) -> str:
        return "#%02x%02x%02x" % self.rgb


def palette(image: Image, top: int = 8, step: int = 3) -> list[Swatch]:
    """Dominant colours, quantised so near-identical shades collapse together."""
    counts: dict[tuple[int, int, int], int] = {}
    total = 0
    for y in range(0, image.height, step):
        for x in range(0, image.width, step):
            r, g, b = image.pixel(x, y)
            key = (r >> 4, g >> 4, b >> 4)
            counts[key] = counts.get(key, 0) + 1
            total += 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return [Swatch(rgb=((k[0] << 4) + 8, (k[1] << 4) + 8, (k[2] << 4) + 8),
                   coverage=count / total if total else 0.0)
            for k, count in ranked]


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def match_palettes(reference: list[Swatch], actual: list[Swatch],
                   tolerance: float = 40.0) -> tuple[list[Swatch], list[Swatch]]:
    """Reference swatches with no near neighbour in the build, and vice versa."""
    missing = [s for s in reference
               if min((_distance(s.rgb, a.rgb) for a in actual), default=999) > tolerance]
    extra = [s for s in actual
             if min((_distance(s.rgb, r.rgb) for r in reference), default=999) > tolerance]
    return missing, extra


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_ELEMENT_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z' ]{2,}")


def visible_text(source: Path, limit: int = 200) -> list[str]:
    """Rough text extraction from a design file: enough to check that the words
    in the mockup made it into the build."""
    raw = _TAG_RE.sub(" ", Path(source).read_text(errors="ignore"))
    text = html.unescape(_ELEMENT_RE.sub("\n", raw))
    seen: list[str] = []
    for line in text.splitlines():
        candidate = " ".join(line.split())
        if 2 < len(candidate) <= 60 and _WORD_RE.fullmatch(candidate):
            if candidate not in seen:
                seen.append(candidate)
        if len(seen) >= limit:
            break
    return seen


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

@dataclass
class Comparison:
    composite: Path
    reference_palette: list[Swatch] = field(default_factory=list)
    actual_palette: list[Swatch] = field(default_factory=list)
    missing_colors: list[Swatch] = field(default_factory=list)
    extra_colors: list[Swatch] = field(default_factory=list)
    missing_text: list[str] = field(default_factory=list)
    found_text: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = ["# design vs build", "", f"![side by side]({self.composite.name})", ""]
        lines.append("## palette")
        lines.append("")
        lines.append("| design | build |")
        lines.append("|---|---|")
        for index in range(max(len(self.reference_palette), len(self.actual_palette))):
            left = self.reference_palette[index] if index < len(self.reference_palette) else None
            right = self.actual_palette[index] if index < len(self.actual_palette) else None
            left_cell = f"{left.hex} {left.coverage * 100:.0f}%" if left else "—"
            right_cell = f"{right.hex} {right.coverage * 100:.0f}%" if right else "—"
            lines.append(f"| {left_cell} | {right_cell} |")
        lines.append("")
        if self.missing_colors:
            lines.append("colours in the design with no close match on screen: "
                         + ", ".join(s.hex for s in self.missing_colors))
        if self.extra_colors:
            lines.append("colours on screen that are not in the design: "
                         + ", ".join(s.hex for s in self.extra_colors))
        if not self.missing_colors and not self.extra_colors:
            lines.append("every dominant colour has a close match in both directions")
        lines.append("")
        if self.found_text or self.missing_text:
            lines.append("## text")
            lines.append("")
            lines.append(f"found on screen: {len(self.found_text)} of "
                         f"{len(self.found_text) + len(self.missing_text)} design strings")
            if self.missing_text:
                lines.append("")
                lines.append("missing:")
                lines += [f"- {t}" for t in self.missing_text[:30]]
                if len(self.missing_text) > 30:
                    lines.append(f"- … {len(self.missing_text) - 30} more")
        lines.append("")
        lines.append("Colour and text are the objective half. Whether the layout, "
                     "spacing and hierarchy match is a judgement call — look at "
                     "the composite above.")
        return "\n".join(lines)


def compare(reference: Path, actual: Path, out_dir: Path, *,
            design_source: Path | None = None,
            labels: list[str] | None = None,
            height: int = 900) -> Comparison:
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / ".work"
    work.mkdir(exist_ok=True)

    # match heights so the two sit sensibly beside each other
    ref_small = png.downscale(reference, work / "ref.png", height)
    act_small = png.downscale(actual, work / "act.png", height)
    ref_image = png.read_png(ref_small)
    act_image = png.read_png(act_small)

    composite = out_dir / "compare.png"
    png.write_png(composite, png.side_by_side(ref_image, act_image, gap=16))

    result = Comparison(composite=composite,
                        reference_palette=palette(ref_image),
                        actual_palette=palette(act_image))
    result.missing_colors, result.extra_colors = match_palettes(
        result.reference_palette, result.actual_palette)

    if design_source is not None and labels is not None:
        haystack = " \n ".join(labels).lower()
        for phrase in visible_text(design_source):
            (result.found_text if phrase.lower() in haystack
             else result.missing_text).append(phrase)

    shutil.rmtree(work, ignore_errors=True)
    (out_dir / "compare.md").write_text(result.render())
    return result
