"""SVG rendering for deployment architecture topology diagrams.

Generates SVG visualizations of local and cloud deployment topologies.
Uses fixed layouts with parametric sizing — not a generic graph layout.
"""

from typing import Any
from xml.sax.saxutils import escape

# Color palette (warm stone)
COLOR_PD = "#78716c"       # stone-500
COLOR_TIKV = "#57534e"     # stone-600
COLOR_OBS = "#a8a29e"      # stone-400
COLOR_OPERATOR = "#44403c" # stone-700
COLOR_EVAL = "#a8a29e"     # stone-400
COLOR_DATABASE = "#78716c" # stone-500
COLOR_APP = "#78716c"      # stone-500
COLOR_OTHER = "#d6d3d1"    # stone-300
COLOR_BORDER = "#d6d3d1"   # stone-300
COLOR_TEXT = "#1c1917"      # stone-900
COLOR_LABEL = "#78716c"    # stone-500
COLOR_VM_BG = "#f5f5f4"    # stone-100 tint for VM background

ROLE_COLORS = {
    "pd": COLOR_PD,
    "tikv": COLOR_TIKV,
    "observability": COLOR_OBS,
    "operator": COLOR_OPERATOR,
    "eval": COLOR_EVAL,
    "database": COLOR_DATABASE,
    "app": COLOR_APP,
    "other": COLOR_OTHER,
}

# Node dimensions
NODE_W = 80
NODE_H = 36
NODE_RX = 6
NODE_GAP_X = 16
NODE_GAP_Y = 12
GROUP_PAD = 20
LABEL_H = 24


def _short_container_label(container_name: str) -> str:
    """Extract a short display label from a Docker container name.

    Docker Compose names follow: {project}-{service}-{instance_num}
    e.g., "tikv-pd0-1" -> "pd0", "tikv-eval-0-tikv2-1" -> "tikv2"
    """
    if not container_name:
        return ""
    parts = container_name.split("-")
    # Strip trailing instance number (always last part, always a digit)
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    # Known project prefixes to strip
    for prefix_len in [3, 2, 1]:  # try "tikv-eval-0", "tikv-eval", "tikv"
        if len(parts) > prefix_len:
            candidate = "-".join(parts[prefix_len:])
            if candidate:
                return candidate
    return parts[-1] if parts else container_name


def _role_color(role: str) -> str:
    return ROLE_COLORS.get(role, COLOR_OTHER)


def _node_svg(x: int, y: int, label: str, role: str, w: int = NODE_W) -> str:
    """Render a single node box."""
    color = _role_color(role)
    # Truncate label to fit (scale with node width)
    max_chars = max(12, w // 7)
    display = label[:max_chars]
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{NODE_H}" rx="{NODE_RX}" '
        f'fill="white" stroke="{color}" stroke-width="1.5"/>\n'
        f'<text x="{x + w // 2}" y="{y + NODE_H // 2 + 4}" '
        f'text-anchor="middle" font-size="11" fill="{COLOR_TEXT}" font-weight="500">'
        f'{escape(display)}</text>\n'
    )


def _group_box(
    x: int, y: int, w: int, h: int, label: str,
    dashed: bool = True, bg: str | None = None,
) -> str:
    """Render a group boundary box with label."""
    dash = ' stroke-dasharray="6 3"' if dashed else ""
    bg_fill = f'fill="{bg}"' if bg else 'fill="none"'
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
        f'{bg_fill} stroke="{COLOR_BORDER}" stroke-width="1.5"{dash}/>\n'
        f'<text x="{x + 10}" y="{y + 16}" font-size="12" fill="{COLOR_LABEL}" '
        f'font-weight="600">{escape(label)}</text>\n'
    )


def _arrow_marker() -> str:
    """SVG marker definition for arrowheads."""
    return (
        '<defs>\n'
        '  <marker id="arrowhead" markerWidth="8" markerHeight="6" '
        'refX="8" refY="3" orient="auto">\n'
        f'    <polygon points="0 0, 8 3, 0 6" fill="{COLOR_LABEL}"/>\n'
        '  </marker>\n'
        '</defs>\n'
    )


def _connection_line(
    x1: int, y1: int, x2: int, y2: int, label: str = "",
) -> str:
    """Render a connection line with optional label."""
    mid_x = (x1 + x2) // 2
    mid_y = (y1 + y2) // 2
    line = (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{COLOR_LABEL}" stroke-width="1" '
        f'marker-end="url(#arrowhead)"/>\n'
    )
    if label:
        line += (
            f'<text x="{mid_x}" y="{mid_y - 4}" text-anchor="middle" '
            f'font-size="9" fill="{COLOR_LABEL}">{escape(label)}</text>\n'
        )
    return line


def _render_local_topology(topology: dict[str, Any]) -> str:
    """Render SVG for local deployment topology."""
    hosts = topology.get("hosts", [])
    connections = topology.get("connections", [])

    # Find host and docker groups
    host_entry = next((h for h in hosts if h.get("type") == "host"), None)
    docker_entry = next((h for h in hosts if h.get("type") == "docker"), None)

    if not docker_entry:
        return ""

    processes = host_entry.get("processes", []) if host_entry else []
    containers = docker_entry.get("containers", [])

    # Group containers by role, preserving order of first appearance
    container_groups: list[tuple[str, list[dict]]] = []
    seen_roles: dict[str, int] = {}
    for c in containers:
        role = c.get("role", "other")
        if role not in seen_roles:
            seen_roles[role] = len(container_groups)
            container_groups.append((role, []))
        container_groups[seen_roles[role]][1].append(c)

    # Layout calculations
    # Left side: host processes
    host_x = GROUP_PAD
    host_y = GROUP_PAD
    proc_w = 120
    proc_h = NODE_H
    host_inner_h = len(processes) * (proc_h + NODE_GAP_Y) + GROUP_PAD
    host_box_w = proc_w + GROUP_PAD * 2
    host_box_h = host_inner_h + LABEL_H

    # Right side: docker containers
    docker_x = host_box_w + GROUP_PAD * 3
    docker_y = GROUP_PAD

    # Rows: one per role group
    row_counts = [len(g) for _, g in container_groups]
    max_cols = max(row_counts) if row_counts else 3
    docker_inner_w = max_cols * (NODE_W + NODE_GAP_X) - NODE_GAP_X + GROUP_PAD * 2
    docker_inner_w = max(docker_inner_w, 240)  # minimum width

    num_rows = len(container_groups)
    docker_inner_h = num_rows * (NODE_H + NODE_GAP_Y) + GROUP_PAD
    docker_box_h = docker_inner_h + LABEL_H

    # Ensure both boxes have same height
    max_h = max(host_box_h, docker_box_h, 180)
    host_box_h = max_h
    docker_box_h = max_h

    total_w = docker_x + docker_inner_w + GROUP_PAD * 2
    total_h = max_h + GROUP_PAD * 2

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" '
        f'style="max-width:100%;height:auto;" font-family="system-ui,-apple-system,sans-serif">\n',
        _arrow_marker(),
    ]

    # Host box
    if host_entry:
        svg_parts.append(_group_box(
            host_x, host_y, host_box_w, host_box_h,
            host_entry.get("label", "Local Machine"),
        ))

        # Process nodes
        proc_y = host_y + LABEL_H + NODE_GAP_Y
        proc_x = host_x + GROUP_PAD
        process_positions: dict[str, tuple[int, int]] = {}
        for proc in processes:
            svg_parts.append(_node_svg(proc_x, proc_y, proc.get("label", ""), proc.get("role", ""), w=proc_w))
            process_positions[proc["id"]] = (proc_x + proc_w, proc_y + NODE_H // 2)
            proc_y += proc_h + NODE_GAP_Y

    # Docker box
    svg_parts.append(_group_box(
        docker_x, docker_y, docker_inner_w + GROUP_PAD, docker_box_h,
        docker_entry.get("label", "Docker"),
    ))

    # Render container rows
    container_y = docker_y + LABEL_H + NODE_GAP_Y
    container_positions: dict[str, tuple[int, int]] = {}
    docker_mid_x = docker_x + (docker_inner_w + GROUP_PAD) // 2

    for _role, group_nodes in container_groups:
        if not group_nodes:
            continue
        row_w = len(group_nodes) * (NODE_W + NODE_GAP_X) - NODE_GAP_X
        start_x = docker_x + GROUP_PAD + (docker_inner_w - row_w) // 2
        cx = start_x
        for node in group_nodes:
            node_id = node.get("id", "")
            label = _short_container_label(node_id)
            svg_parts.append(_node_svg(cx, container_y, label, node.get("role", ""), w=NODE_W))
            container_positions[node_id] = (cx, container_y + NODE_H // 2)
            cx += NODE_W + NODE_GAP_X
        container_y += NODE_H + NODE_GAP_Y

    # Draw connections
    docker_left = docker_x
    for conn in connections:
        from_id = conn.get("from", "")
        to_id = conn.get("to", "")
        label = conn.get("label", "")

        if from_id in process_positions and to_id == "docker":
            x1, y1 = process_positions[from_id]
            x2 = docker_left
            y2 = y1
            svg_parts.append(_connection_line(x1, y1, x2, y2, label))

    svg_parts.append("</svg>")
    return "".join(svg_parts)


def _render_cloud_topology(topology: dict[str, Any]) -> str:
    """Render SVG for cloud (GCP) deployment topology."""
    hosts = topology.get("hosts", [])
    connections = topology.get("connections", [])

    eval_host = next((h for h in hosts if h.get("type") == "host"), None)
    vm_host = next((h for h in hosts if h.get("type") == "vm"), None)

    if not vm_host:
        return ""

    compose_containers = vm_host.get("compose_containers", [])
    operator_containers = vm_host.get("operator_containers", [])

    # Group compose containers by role, preserving order of first appearance
    compose_groups: list[tuple[str, list[dict]]] = []
    seen_roles: dict[str, int] = {}
    for c in compose_containers:
        role = c.get("role", "other")
        if role not in seen_roles:
            seen_roles[role] = len(compose_groups)
            compose_groups.append((role, []))
        compose_groups[seen_roles[role]][1].append(c)

    # Layout: eval worker box on left, VM box on right
    eval_box_x = GROUP_PAD
    eval_box_y = GROUP_PAD
    eval_box_w = 140
    eval_box_h = 100

    vm_box_x = eval_box_w + GROUP_PAD * 4
    vm_box_y = GROUP_PAD

    # VM box sizing — use wider nodes for readability
    node_w = 100
    max_row = max((len(g) for _, g in compose_groups), default=1)
    # Operator row: monitor + agent + DB = 3 nodes
    if operator_containers:
        op_row_count = len(operator_containers) + 1  # +1 for data volume
        max_row = max(max_row, op_row_count)
    vm_inner_w = max_row * (node_w + NODE_GAP_X) - NODE_GAP_X + GROUP_PAD * 2
    vm_inner_w = max(vm_inner_w, 300)  # minimum

    # Sections: compose label + compose rows + operator section
    compose_rows = len(compose_groups)
    vm_inner_h = (
        LABEL_H  # VM label
        + LABEL_H  # "Docker Compose" sublabel
        + compose_rows * (NODE_H + NODE_GAP_Y)
        + (LABEL_H + NODE_H + NODE_GAP_Y if operator_containers else 0)
        + GROUP_PAD * 2
    )
    vm_box_h = max(vm_inner_h, eval_box_h)
    eval_box_h = vm_box_h  # Match heights

    total_w = vm_box_x + vm_inner_w + GROUP_PAD * 2
    total_h = vm_box_h + GROUP_PAD * 2

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" '
        f'style="max-width:100%;height:auto;" font-family="system-ui,-apple-system,sans-serif">\n',
        _arrow_marker(),
    ]

    # Eval worker box
    if eval_host:
        svg_parts.append(_group_box(
            eval_box_x, eval_box_y, eval_box_w, eval_box_h,
            eval_host.get("label", "Eval Worker"),
        ))
        # Eval runner node
        proc_x = eval_box_x + GROUP_PAD
        proc_y = eval_box_y + LABEL_H + NODE_GAP_Y + (eval_box_h - LABEL_H - NODE_H) // 3
        svg_parts.append(_node_svg(proc_x, proc_y, "Eval Runner", "eval", w=100))
        eval_right = proc_x + 100
        eval_mid_y = proc_y + NODE_H // 2

    # VM box (with light blue background)
    svg_parts.append(_group_box(
        vm_box_x, vm_box_y, vm_inner_w + GROUP_PAD, vm_box_h,
        vm_host.get("label", "Cloud VM"),
        bg=COLOR_VM_BG,
    ))

    # Docker Compose sublabel
    cy = vm_box_y + LABEL_H + 4
    svg_parts.append(
        f'<text x="{vm_box_x + GROUP_PAD}" y="{cy + 12}" font-size="10" '
        f'fill="{COLOR_LABEL}" font-style="italic">Docker Compose ({vm_host.get("vm_name", "")})</text>\n'
    )
    cy += LABEL_H

    # Compose container rows (all roles)
    for _role, group_nodes in compose_groups:
        if not group_nodes:
            continue
        row_w = len(group_nodes) * (node_w + NODE_GAP_X) - NODE_GAP_X
        start_x = vm_box_x + GROUP_PAD + (vm_inner_w - row_w) // 2
        cx = start_x
        for node in group_nodes:
            node_id = node.get("id", "")
            label = _short_container_label(node_id)
            svg_parts.append(_node_svg(cx, cy, label, node.get("role", ""), w=node_w))
            cx += node_w + NODE_GAP_X
        cy += NODE_H + NODE_GAP_Y

    # Operator section
    if operator_containers:
        cy += 4
        svg_parts.append(
            f'<text x="{vm_box_x + GROUP_PAD}" y="{cy + 12}" font-size="10" '
            f'fill="{COLOR_LABEL}" font-style="italic">Operator (docker compose, --network=host)</text>\n'
        )
        cy += LABEL_H
        cx = vm_box_x + GROUP_PAD

        # Map container IDs to friendly labels
        _OP_LABELS = {"operator-monitor": "Monitor", "operator-agent": "Agent"}
        for oc in operator_containers:
            oc_id = oc.get("id", "")
            label = _OP_LABELS.get(oc_id, oc_id.replace("operator-", ""))
            svg_parts.append(_node_svg(cx, cy, label, "operator", w=node_w))
            cx += node_w + NODE_GAP_X

        # Data volume node
        svg_parts.append(_node_svg(cx, cy, "DB", "operator", w=node_w))

    # SSH connection arrow
    if eval_host:
        vm_left = vm_box_x
        svg_parts.append(_connection_line(
            eval_right, eval_mid_y,
            vm_left, eval_mid_y,
            "SSH",
        ))

    svg_parts.append("</svg>")
    return "".join(svg_parts)


def render_topology_svg(topology: dict[str, Any] | None) -> str:
    """Render topology dict as an SVG string.

    Args:
        topology: Parsed topology dict with 'mode', 'hosts', 'connections'

    Returns:
        SVG string, or empty string if topology cannot be rendered
    """
    if not topology or not isinstance(topology, dict):
        return ""

    mode = topology.get("mode", "local")
    if mode == "local":
        return _render_local_topology(topology)
    elif mode in ("cloud-gcp", "cloud"):
        return _render_cloud_topology(topology)

    return ""
