"""Accessibility-tree flattening and diffing.

The tree diff is the part an agent actually reasons over. A screenshot says
"something changed"; this says `Button[editor.tool.pen] appeared` and
`StaticText[library.title] "Library" -> "Untitled Notebook"`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

MOVE_THRESHOLD = 4  # points; below this a frame change is layout noise


@dataclass
class Node:
    key: str
    type: str
    id: str = ""
    label: str = ""
    value: str = ""
    frame: tuple[int, int, int, int] = (0, 0, 0, 0)
    enabled: bool = True
    selected: bool = False
    depth: int = 0
    path: str = ""

    @property
    def named(self) -> bool:
        return bool(self.id or self.label)

    def describe(self) -> str:
        parts = [self.type]
        if self.id:
            parts.append(self.id)
        if self.label:
            parts.append(f'"{_ellipsis(self.label)}"')
        x, y, w, h = self.frame
        parts.append(f"@ ({x},{y} {w}x{h})")
        return " ".join(parts)


@dataclass
class TreeDiff:
    added: list[Node] = field(default_factory=list)
    removed: list[Node] = field(default_factory=list)
    changed: list[tuple[Node, Node, list[str]]] = field(default_factory=list)
    # Unnamed structural containers, counted but not listed: a popover can add
    # forty anonymous `Other` nodes and none of them tell an agent anything.
    added_anonymous: int = 0
    removed_anonymous: int = 0
    modal: str = ""

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed
                    or self.added_anonymous or self.removed_anonymous)


def _ellipsis(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load(path: str | Path) -> list[Node]:
    return flatten(json.loads(Path(path).read_text()))


def flatten(root: dict) -> list[Node]:
    nodes: list[Node] = []
    seen: dict[str, int] = {}

    def visit(raw: dict, depth: int, path: str) -> None:
        kind = raw.get("type", "?")
        identifier = raw.get("id", "")
        label = raw.get("label", "")
        # Identity, most stable first: an explicit identifier, then a label, then
        # position in the tree. Identifiers survive relayout; paths do not.
        if identifier:
            base = f"{kind}#{identifier}"
        elif label:
            base = f"{kind}|{_ellipsis(label, 32)}"
        else:
            base = f"{path}/{kind}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        key = base if count == 0 else f"{base}[{count}]"

        frame = raw.get("frame") or [0, 0, 0, 0]
        nodes.append(Node(
            key=key, type=kind, id=identifier, label=label,
            value=str(raw.get("value", "")),
            frame=(int(frame[0]), int(frame[1]), int(frame[2]), int(frame[3])),
            enabled=raw.get("enabled", True), selected=raw.get("selected", False),
            depth=depth, path=path,
        ))
        for index, child in enumerate(raw.get("children", [])):
            visit(child, depth + 1, f"{path}/{kind}{index}")

    visit(root, 0, "")
    return nodes


def diff(before: list[Node], after: list[Node]) -> TreeDiff:
    old = {n.key: n for n in before}
    new = {n.key: n for n in after}
    result = TreeDiff()

    for key, node in new.items():
        if key not in old:
            if node.named:
                result.added.append(node)
            else:
                result.added_anonymous += 1
    for key, node in old.items():
        if key not in new:
            if node.named:
                result.removed.append(node)
            else:
                result.removed_anonymous += 1

    # A modal covering the screen makes everything behind it inaccessible, so the
    # raw diff reads as "ninety elements vanished". Say what actually happened.
    covering = next((n for n in after
                     if n.type in ("Sheet", "Alert", "Popover")
                     or "dismiss" in n.label.lower()), None)
    if covering is not None and len(result.removed) > 8:
        result.modal = (f"a modal appeared ({covering.type}"
                        + (f' "{_ellipsis(covering.label, 32)}"' if covering.label else "")
                        + f"); {len(result.removed)} background element(s) became "
                          f"inaccessible rather than being destroyed")

    for key, node in new.items():
        previous = old.get(key)
        if previous is None:
            continue
        reasons: list[str] = []
        if previous.label != node.label:
            reasons.append(f'label "{_ellipsis(previous.label)}" -> "{_ellipsis(node.label)}"')
        if previous.value != node.value:
            reasons.append(f'value "{_ellipsis(previous.value)}" -> "{_ellipsis(node.value)}"')
        if previous.enabled != node.enabled:
            reasons.append("enabled" if node.enabled else "disabled")
        if previous.selected != node.selected:
            reasons.append("selected" if node.selected else "deselected")
        moved = max(abs(a - b) for a, b in zip(previous.frame, node.frame))
        if moved >= MOVE_THRESHOLD:
            reasons.append(f"frame {previous.frame} -> {node.frame}")
        if reasons:
            result.changed.append((previous, node, reasons))

    # identified elements first: they are the ones an agent can address
    result.added.sort(key=lambda n: (not n.id, n.depth, n.key))
    result.removed.sort(key=lambda n: (not n.id, n.depth, n.key))
    return result


def render(result: TreeDiff, limit: int = 12) -> list[str]:
    lines: list[str] = []
    if result.modal:
        lines.append(f"  ! {result.modal}")
    for node in result.added[:limit]:
        lines.append(f"  + {node.describe()}")
    if len(result.added) > limit:
        lines.append(f"  + … and {len(result.added) - limit} more added")
    for node in result.removed[:limit]:
        lines.append(f"  - {node.describe()}")
    if len(result.removed) > limit:
        lines.append(f"  - … and {len(result.removed) - limit} more removed")
    for previous, _, reasons in result.changed[:limit]:
        head = previous.id or previous.type
        lines.append(f"  ~ {previous.type} {head}: " + "; ".join(reasons))
    if len(result.changed) > limit:
        lines.append(f"  ~ … and {len(result.changed) - limit} more changed")
    anon = result.added_anonymous + result.removed_anonymous
    if anon:
        lines.append(f"    ({result.added_anonymous} added / "
                     f"{result.removed_anonymous} removed unnamed containers, not listed)")
    return lines


def interactive(nodes: list[Node]) -> list[Node]:
    """Elements worth naming to an agent choosing what to tap next."""
    tappable = {"Button", "Cell", "Link", "MenuItem", "Switch", "TextField",
                "SecureTextField", "TextView", "Slider", "TabBar"}
    return [n for n in nodes if n.type in tappable and (n.id or n.label)]
