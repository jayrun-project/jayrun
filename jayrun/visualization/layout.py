"""Deterministic orthogonal presentation of actual ports and occurrences.

Column/row hints affect positioning only. In particular a backward route is an
ordinary dependency unless the caller explicitly supplied a re-iteration.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
import unicodedata


def _units(char: str) -> float:
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 2.0
    if char in "MW@%mw":
        return 1.65
    if char in " ilI.,:;!|'":
        return 0.55
    return 1.25 if char.isupper() else 1.0


def lines(text: str, width: int, maximum: int) -> list[str]:
    """Conservative font-independent wrapping; full labels stay in inspection.

    Weight wide glyphs so long identifiers cannot overflow a fixed card merely
    because their character count happens to fit. Ellipsis is presentation only.
    """
    wrapped, current, used = [], "", 0.0
    for word in text.split():
        word_units = sum(_units(char) for char in word)
        if current and used + 0.55 + word_units > width:
            wrapped.append(current); current, used = "", 0.0
        if current:
            current += " "; used += 0.55
        for char in word:
            unit = _units(char)
            if current and used + unit > width:
                wrapped.append(current); current, used = "", 0.0
            current += char; used += unit
    if current:
        wrapped.append(current)
    wrapped = wrapped or [""]
    if len(wrapped) > maximum:
        wrapped = wrapped[:maximum]
        while sum(_units(char) for char in wrapped[-1]) > width - 2:
            wrapped[-1] = wrapped[-1][:-1]
        wrapped[-1] += "…"
    return wrapped


def _columns(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    if all("column" in node for node in nodes):
        values = sorted({node["column"] for node in nodes})
        indices = {value: i for i, value in enumerate(values)}
        return {node["id"]: indices[node["column"]] for node in nodes}
    outgoing, incoming = defaultdict(list), {node["id"]: 0 for node in nodes}
    for edge in edges:
        a, b = edge["source"]["node"], edge["target"]["node"]
        outgoing[a].append(b)
        incoming[b] += 1
    ready = deque(nid for nid, degree in incoming.items() if not degree)
    columns = {nid: 0 for nid in ready}
    while ready:
        nid = ready.popleft()
        for target in outgoing[nid]:
            columns[target] = max(columns.get(target, 0), columns[nid] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    # Cycles are not treated as iteration feedback. Lay remaining nodes out in
    # stable input order and route their ordinary dependencies around the cards.
    cursor = max(columns.values(), default=-1) + 1
    for node in nodes:
        if incoming[node["id"]]:
            columns[node["id"]] = cursor
            cursor += 1
    return columns


def _simplify(points: list[list[float]]) -> list[list[float]]:
    result: list[list[float]] = []
    for point in points:
        if result and point == result[-1]:
            continue
        while len(result) > 1 and (
            result[-2][0] == result[-1][0] == point[0]
            or result[-2][1] == result[-1][1] == point[1]
        ):
            # Only remove a point on the segment, not a reversal.
            a, b = result[-2], result[-1]
            if (b[0] - a[0]) * (point[0] - b[0]) < 0 or (b[1] - a[1]) * (point[1] - b[1]) < 0:
                break
            result.pop()
        result.append(point)
    return result


def _clear(points: list[list[float]], nodes: list[dict], padding: float = 0) -> bool:
    for a, b in zip(points, points[1:]):
        for node in nodes:
            left, right = node["x"] - padding, node["x"] + node["width"] + padding
            top, bottom = node["y"] - padding, node["y"] + node["height"] + padding
            if a[1] == b[1]:
                if top < a[1] < bottom and max(left, min(a[0], b[0])) < min(right, max(a[0], b[0])):
                    return False
            elif a[0] == b[0]:
                if left < a[0] < right and max(top, min(a[1], b[1])) < min(bottom, max(a[1], b[1])):
                    return False
            else:
                return False
    return True


def _measure(node: dict) -> None:
    operator = node["kind"] == "operator"
    node["width"] = 260 if operator else 142
    node["label_lines"] = lines(node["label"], 26 if operator else 15, 3 if operator else 2)
    node["description_lines"] = lines(node.get("description", ""), 34, 2) if operator and node.get("description") else []
    count = max(len(node["inputs"]), len(node["outputs"]), 1)
    if not operator:
        node["height"] = max(28 + 18 * len(node["label_lines"]), 24 + (count - 1) * 22)
        node["port_top"] = node["height"] / 2
        return
    node["port_top"] = 64 + 20 * len(node["label_lines"]) + 16 * len(node["description_lines"])
    cursor = node["port_top"] + (count - 1) * 28 + 22
    for marker in node.get("resources", []):
        marker["label_lines"] = lines(marker["label"], 31, 3)
        marker["height"] = 14 + 16 * len(marker["label_lines"])
        marker["y"] = cursor
        cursor += marker["height"] + 7
    # A fixed footer accommodates the existing progress display without moving
    # ports/cards when validation/dashboard mode or a snapshot changes.
    node["progress_y"] = cursor + 8
    node["height"] = cursor + 30


def _ports(node: dict) -> None:
    for side in ("inputs", "outputs"):
        for index, port in enumerate(node[side]):
            port["x"] = node["x"] + (node["width"] if side == "outputs" else 0)
            offset = node["port_top"] + index * 28 if node["kind"] == "operator" else node["height"] / 2 + (index - (len(node[side]) - 1) / 2) * 22
            port["y"] = node["y"] + offset


def _cost(points: list[list[float]], used: list[tuple[list[float], list[float]]]) -> float:
    cost = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(points, points[1:])) + 32 * (len(points) - 2)
    for a, b in zip(points[1:-1], points[2:-1]):
        # Candidate geometry is invariant across previously routed segments.
        # Preserve penalty accumulation order and strict endpoint comparisons.
        ax, ay = a
        bx, by = b
        horizontal, vertical = ay == by, ax == bx
        left, right = (ax, bx) if ax <= bx else (bx, ax)
        top, bottom = (ay, by) if ay <= by else (by, ay)
        for c, d in used:
            cx, cy = c
            dx, dy = d
            if horizontal and ay == cy == dy:
                cost += 2 * max(0, min(right, max(cx, dx)) - max(left, min(cx, dx)))
            elif vertical and ax == cx == dx:
                cost += 2 * max(0, min(bottom, max(cy, dy)) - max(top, min(cy, dy)))
            elif horizontal and cx == dx and left < cx < right and min(cy, dy) < ay < max(cy, dy):
                cost += 20
            elif vertical and cy == dy and top < cy < bottom and min(cx, dx) < ax < max(cx, dx):
                cost += 20
    return cost


def _label(edge: dict, nodes: list[dict]) -> list[float]:
    horizontal = [(a, b) for a, b in zip(edge["points"], edge["points"][1:]) if a[1] == b[1]]
    candidates = sorted(horizontal, key=lambda pair: -abs(pair[0][0] - pair[1][0]))
    for a, b in candidates:
        x, y = (a[0] + b[0]) / 2, a[1] - 10
        # Captions may be moved below a route, never into a card. Full labels
        # and exact fields are always available in the inspector.
        for offset in (0, 34):
            box = {"x": x - 52, "y": y + offset - 14, "width": 104, "height": 22}
            if all(box["x"] + box["width"] <= n["x"] or box["x"] >= n["x"] + n["width"] or box["y"] + box["height"] <= n["y"] or box["y"] >= n["y"] + n["height"] for n in nodes):
                return [x, y + offset]
    a, b = candidates[0]
    return [(a[0] + b[0]) / 2, a[1] - 10]


def arrange(graph: dict) -> dict:
    """Detach and place actual ports; prefer straight, card-clear routes.

    Row hints are shared across columns, as in the original viewer. They are
    presentation hints, not artifact lifetimes. Ordinary long edges use a clear
    straight/dogleg route or the nearest clear corridor, not a forced upper bus.
    Re-iteration lanes alone are reserved above the graph while hidden.
    """
    graph = deepcopy(graph)
    nodes = graph["nodes"]
    if not nodes:
        graph["bounds"] = {"x": 0, "y": 0, "width": 720, "height": 400}
        return graph
    columns = _columns(nodes, graph["edges"])
    groups: dict[int, list[dict]] = defaultdict(list)
    rows, row_top, row_bottom = {}, defaultdict(float), defaultdict(float)
    occupied: set[tuple[int, int]] = set()
    for node in nodes:
        _measure(node)
        col = columns[node["id"]]
        row = node.get("row", 0)
        while (col, row) in occupied:
            row += 1
        occupied.add((col, row))
        rows[node["id"]] = row
        groups[col].append(node)
        row_top[row] = max(row_top[row], node["port_top"])
        row_bottom[row] = max(row_bottom[row], node["height"] - node["port_top"])
    # Reserve only explicit feedback, so toggling it never changes geometry.
    top = 56 + 28 * len(graph["reiterations"])
    row_anchor, cursor = {}, top
    for row in sorted(row_top):
        row_anchor[row] = cursor + row_top[row]
        cursor += row_top[row] + row_bottom[row] + 78
    cursor = 48
    col_left, col_right = {}, {}
    for col in sorted(groups):
        width = max(n["width"] for n in groups[col])
        col_left[col], col_right[col] = cursor, cursor + width
        for node in groups[col]:
            # Compact boundary shapes sit against their connected side.
            node["x"] = cursor + (width - node["width"] if node["kind"] == "entry" else 0)
            node["y"] = row_anchor[rows[node["id"]]] - node["port_top"]
            _ports(node)
        cursor += width + 126
    by_id = {node["id"]: node for node in nodes}
    ports = {port["id"]: port for node in nodes for side in ("inputs", "outputs") for port in node[side]}
    # Align single-port boundaries to their actual endpoint where this does not
    # collide with another card. Rows remain hints; field order is never changed.
    for node in nodes:
        if node["kind"] == "operator" or len(node["inputs"] + node["outputs"]) != 1:
            continue
        outgoing = node["kind"] == "entry"
        connections = [e for e in graph["edges"] if e["source" if outgoing else "target"]["node"] == node["id"]]
        if not connections:
            continue
        endpoint = connections[0]["target" if outgoing else "source"]
        target = ports[endpoint["port"]]
        proposed_y = target["y"] - node["height"] / 2
        if proposed_y < top:
            continue
        others = [other for other in nodes if other is not node]
        if any(node["x"] < other["x"] + other["width"] + 16 and node["x"] + node["width"] + 16 > other["x"] and proposed_y < other["y"] + other["height"] + 20 and proposed_y + node["height"] + 20 > other["y"] for other in others):
            continue
        start = [node["x"] + (node["width"] if outgoing else 0), proposed_y + node["height"] / 2]
        end = [target["x"], target["y"]]
        if _clear([start, end], others):
            node["y"] = proposed_y
            _ports(node)
    all_edges = graph["edges"] + graph["reiterations"]
    feedback = {edge["id"]: index for index, edge in enumerate(graph["reiterations"])}
    peers: dict[tuple[str, str], int] = defaultdict(int)
    used: list[tuple[list[float], list[float]]] = []
    corridors = {top - 24, max(n["y"] + n["height"] for n in nodes) + 30}
    for node in nodes:
        corridors.update((node["y"] - 20, node["y"] + node["height"] + 20))
    for edge in all_edges:
        s, t = ports[edge["source"]["port"]], ports[edge["target"]["port"]]
        start, end = [s["x"], s["y"]], [t["x"], t["y"]]
        sc, tc = columns[edge["source"]["node"]], columns[edge["target"]["node"]]
        pair = (edge["source"]["port"], edge["target"]["port"])
        peer = peers[pair]
        peers[pair] += 1
        sx, tx = col_right[sc] + 24 + (peer % 4) * 7, col_left[tc] - 24 - (peer % 4) * 7
        if edge["id"] in feedback:
            y = 28 + feedback[edge["id"]] * 28
            points = _simplify([start, [sx, start[1]], [sx, y], [tx, y], [tx, end[1]], end])
        elif not peer and start[1] == end[1] and end[0] > start[0] and _clear([start, end], nodes):
            points = [start, end]
        else:
            candidates = []
            if tc > sc and not peer:
                for x in sorted({sx, tx, (sx + tx) / 2}):
                    if start[0] < x < end[0]:
                        candidates.append(_simplify([start, [x, start[1]], [x, end[1]], end]))
            ys = corridors | {start[1], end[1], start[1] - 24 - peer * 14, start[1] + 24 + peer * 14}
            for y in sorted(ys):
                if y < 16 or (peer and y in (start[1], end[1])):
                    continue
                candidates.append(_simplify([start, [sx, start[1]], [sx, y], [tx, y], [tx, end[1]], end]))
            valid = [p for p in candidates if len(p) >= 2 and p[1][0] > start[0] and p[-2][0] < end[0] and _clear(p, nodes)]
            if not valid:
                # Column gutters and an external corridor should always give a
                # route. Fail explicitly instead of drawing a path through a card.
                raise ValueError(f"No card-clear orthogonal route for {edge['id']!r}")
            points = min(valid, key=lambda p: (_cost(p, used), p))
        if not _clear(points, nodes):
            raise ValueError(f"Connection {edge['id']!r} intersects a card")
        edge["points"] = points
        edge["label_position"] = _label(edge, nodes)
        used.extend(zip(points, points[1:]))
    all_points = [p for edge in all_edges for p in edge["points"]]
    graph["bounds"] = {"x": 0, "y": 0,
        "width": max([n["x"] + n["width"] for n in nodes] + [p[0] for p in all_points]) + 48,
        "height": max([n["y"] + n["height"] for n in nodes] + [p[1] for p in all_points]) + 48}
    return graph
