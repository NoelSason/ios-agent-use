"""Turn a run into the one file an agent should read."""

from __future__ import annotations

from pathlib import Path

from . import diff, tree
from .driver import RunOutcome


def write(outcome: RunOutcome, *, title: str = "") -> Path:
    lines = [f"# {title or outcome.run_dir.name}", ""]
    lines.append(f"{'PASSED' if outcome.ok else 'FAILED'} · "
                 f"{len(outcome.steps)} observation(s) · {outcome.seconds:.1f}s wall clock")
    if outcome.screen_size != (0.0, 0.0):
        lines.append(f"screen {outcome.screen_size[0]:.0f}×{outcome.screen_size[1]:.0f} pt")
    if outcome.message:
        lines.append("")
        lines.append(outcome.message)
    lines.append("")

    previous = None
    for step in outcome.steps:
        pixel = None
        elements = None
        if previous is not None:
            if previous.screenshot and step.screenshot:
                annotated = step.screenshot.parent / "diff.png"
                try:
                    pixel = diff.pixels(previous.screenshot, step.screenshot,
                                        annotated=annotated,
                                        frame_points=outcome.screen_size)
                except Exception as exc:                      # noqa: BLE001
                    pixel = diff.PixelDiff(note=f"could not compare images: {exc}")
            if previous.tree and step.tree:
                try:
                    elements = tree.diff(tree.load(previous.tree), tree.load(step.tree))
                except Exception:                             # noqa: BLE001
                    elements = None

        lines.append(diff.report_step(
            step.index, step.action, ok=step.ok, ms=step.ms,
            pixel=pixel, elements=elements, error=step.error, note=step.note,
        ))
        if step.view:
            lines.append(f"![step {step.index}]({step.view.relative_to(outcome.run_dir)})")
            lines.append("")
        previous = step

    final = outcome.steps[-1] if outcome.steps else None
    if final and final.tree:
        try:
            actionable = tree.interactive(tree.load(final.tree))
            if actionable:
                lines += ["## what is tappable now", ""]
                lines += [f"- `{n.id or n.label}` — {n.type} \"{n.label[:60]}\""
                          for n in actionable[:40]]
                if len(actionable) > 40:
                    lines.append(f"- … {len(actionable) - 40} more")
                lines.append("")
        except Exception:                                     # noqa: BLE001
            pass

    path = outcome.run_dir / "report.md"
    path.write_text("\n".join(lines))
    return path
