"""What changed between two observations: pixels, elements, and a report."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from . import png, tree
from .png import Image

TILE = 16               # pixels per comparison cell, on the downscaled image
# Both screenshots come from the same renderer as lossless PNGs, so matching
# regions are near bit-identical and only resampling introduces drift. The
# threshold is therefore low on purpose: a dark-themed UI changes by very few
# levels per channel, and a mean-based test misses a whole popover.
PIXEL_DELTA = 6         # per-pixel max-channel delta that counts as different
DIRTY_FRACTION = 0.02   # share of sampled pixels that must differ for a dirty tile
COMPARE_MAX_DIM = 800


@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int

    def scaled(self, factor: float) -> "Region":
        return Region(int(self.x * factor), int(self.y * factor),
                      int(self.w * factor), int(self.h * factor))


@dataclass
class PixelDiff:
    changed_ratio: float = 0.0
    regions: list[Region] = field(default_factory=list)
    width: int = 0
    height: int = 0
    identical: bool = True
    note: str = ""
    units: str = "px"


def _tile_changed(a: Image, b: Image, tx: int, ty: int) -> bool:
    differing = 0
    sampled = 0
    for y in range(ty, min(ty + TILE, a.height)):
        for x in range(tx, min(tx + TILE, a.width), 2):  # every other column is plenty
            ar, ag, ab = a.pixel(x, y)
            br, bg, bb = b.pixel(x, y)
            if max(abs(ar - br), abs(ag - bg), abs(ab - bb)) > PIXEL_DELTA:
                differing += 1
            sampled += 1
    return sampled > 0 and (differing / sampled) > DIRTY_FRACTION


def _components(grid: list[list[bool]]) -> list[Region]:
    """Group changed tiles into rectangles so the report names areas, not confetti."""
    rows, cols = len(grid), len(grid[0]) if grid else 0
    seen = [[False] * cols for _ in range(rows)]
    regions: list[Region] = []
    for r in range(rows):
        for c in range(cols):
            if not grid[r][c] or seen[r][c]:
                continue
            queue = deque([(r, c)])
            seen[r][c] = True
            min_r = max_r = r
            min_c = max_c = c
            while queue:
                cr, cc = queue.popleft()
                min_r, max_r = min(min_r, cr), max(max_r, cr)
                min_c, max_c = min(min_c, cc), max(max_c, cc)
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = cr + dr, cc + dc
                    if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] and not seen[nr][nc]:
                        seen[nr][nc] = True
                        queue.append((nr, nc))
            regions.append(Region(min_c * TILE, min_r * TILE,
                                  (max_c - min_c + 1) * TILE, (max_r - min_r + 1) * TILE))
    regions.sort(key=lambda r: r.w * r.h, reverse=True)
    return regions


def pixels(before: Path, after: Path, *, work_dir: Path | None = None,
           annotated: Path | None = None,
           frame_points: tuple[float, float] = (0.0, 0.0)) -> PixelDiff:
    work = work_dir or (after.parent / ".diff")
    work.mkdir(parents=True, exist_ok=True)
    small_a = png.downscale(before, work / "a.png", COMPARE_MAX_DIM)
    small_b = png.downscale(after, work / "b.png", COMPARE_MAX_DIM)

    image_a = png.read_png(small_a)
    image_b = png.read_png(small_b)
    if (image_a.width, image_a.height) != (image_b.width, image_b.height):
        return PixelDiff(identical=False, note="screenshot dimensions differ "
                         f"({image_a.width}x{image_a.height} vs "
                         f"{image_b.width}x{image_b.height}); "
                         "the device probably rotated")

    rows = (image_a.height + TILE - 1) // TILE
    cols = (image_a.width + TILE - 1) // TILE
    grid = [[False] * cols for _ in range(rows)]
    changed = 0
    for r in range(rows):
        for c in range(cols):
            if _tile_changed(image_a, image_b, c * TILE, r * TILE):
                grid[r][c] = True
                changed += 1

    total = rows * cols
    regions = _components(grid)
    result = PixelDiff(
        changed_ratio=changed / total if total else 0.0,
        regions=regions,
        width=image_a.width, height=image_a.height,
        identical=(changed == 0),
    )
    # Regions are found on the downscaled copy; report them in a space the
    # caller can act on. With a frame size that is points -- the same space as
    # the accessibility frames, so a changed area and the element that changed
    # can be lined up by eye. Without one, the source image's own pixels.
    if image_a.width:
        if frame_points[0]:
            result.regions = [r.scaled(frame_points[0] / image_a.width) for r in regions]
            result.units = "pt"
        else:
            source_width = png.dimensions(before)[0]
            result.regions = [r.scaled(source_width / image_a.width) for r in regions]


    if annotated is not None:
        marked = png.read_png(small_b)
        for region in result.regions[:12]:
            png.draw_rect(marked, region.x, region.y, region.w, region.h)
        png.write_png(annotated, png.side_by_side(image_a, marked))

    for temp in (small_a, small_b):
        temp.unlink(missing_ok=True)
    return result


def report_step(index: int, action: str, *, ok: bool, ms: int,
                pixel: PixelDiff | None, elements: tree.TreeDiff | None,
                error: str | None = None, note: str | None = None) -> str:
    status = "" if ok else "  **FAILED**"
    lines = [f"## step {index} · {action}{status}", ""]
    if error:
        lines += [f"error: `{error}`", ""]
    if note:
        lines += [f"note: {note}", ""]
    lines.append(f"took {ms} ms")

    if pixel is not None:
        if pixel.note:
            lines.append(f"pixels   {pixel.note}")
        elif pixel.identical:
            lines.append("pixels   no visible change")
        else:
            unit = pixel.units
            boxes = ", ".join(f"({r.x},{r.y} {r.w}×{r.h}{unit})" for r in pixel.regions[:3])
            more = f" +{len(pixel.regions) - 3} more" if len(pixel.regions) > 3 else ""
            lines.append(f"pixels   {pixel.changed_ratio * 100:.1f}% changed in "
                         f"{len(pixel.regions)} region(s) — {boxes}{more}")

    if elements is not None:
        if elements.empty:
            lines.append("tree     unchanged")
        else:
            lines.append(f"tree     +{len(elements.added)} −{len(elements.removed)} "
                         f"~{len(elements.changed)}")
            lines += tree.render(elements)
    lines.append("")
    return "\n".join(lines)
