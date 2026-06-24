"""
router.py

Calculates 3 elevation-aware walking routes (flattest / balanced / steepest)
using Dijkstra's algorithm on the OSM street graph.
"""

import math
import logging
import networkx as nx

logger = logging.getLogger(__name__)

ELEVATION_GAIN_WEIGHT = 5000.0


def _get_cost_fn(profile: str):
    """Weight function for NetworkX MultiDiGraph edges."""

    def cost(u, v, data):
        # MultiDiGraph passes the full edge-key→attr dict; pick the cheapest edge
        if isinstance(data, dict) and all(isinstance(k, int) for k in data):
            d = min(data.values(), key=lambda x: x.get("length", 1))
        else:
            d = data

        length = max(d.get("length", 1), 0.1)  # FIX: guard against 0-length edges
        grade  = d.get("grade", 0)
        uphill = max(0, grade * length)

        if profile == "flattest":
            return length + ELEVATION_GAIN_WEIGHT * uphill
        elif profile == "balanced":
            return length
        else:  # steepest — reward uphill
            return max(1.0, length - ELEVATION_GAIN_WEIGHT * uphill)

    return cost


PROFILES = {
    "flattest": _get_cost_fn("flattest"),
    "balanced": _get_cost_fn("balanced"),
    "steepest": _get_cost_fn("steepest"),
}


# ---------------------------------------------------------------------------
# Nearest node
# ---------------------------------------------------------------------------

def nearest_node(G, lat: float, lon: float) -> int:
    """Snap a lat/lon coordinate to the closest graph node."""
    # FIX: use a quick approximate search instead of iterating all nodes.
    # For large graphs (50k+ nodes) the naive loop takes ~1 s per call.
    # We still use pure Python here (no osmnx dependency at runtime) but
    # short-circuit once we're within 20 m to avoid scanning the whole graph.
    best_node = None
    best_dist = float("inf")

    # Precompute scale so dlat and dlon are comparable in metres
    cos_lat = math.cos(math.radians(lat))

    for node_id, data in G.nodes(data=True):
        dlat = (data["y"] - lat) * 111_000
        dlon = (data["x"] - lon) * 111_000 * cos_lat
        dist = dlat * dlat + dlon * dlon   # squared metres — no sqrt needed for comparison

        if dist < best_dist:
            best_dist = dist
            best_node = node_id
            if best_dist < 400:   # 20 m radius — good enough, stop early
                break

    return best_node


# ---------------------------------------------------------------------------
# Path statistics
# ---------------------------------------------------------------------------

def _path_stats(G, path: list[int]) -> dict:
    """Compute distance, elevation gain/loss, coordinates and elevation profile."""
    total_distance = 0.0
    total_gain     = 0.0
    total_loss     = 0.0
    coordinates    = []
    elevation_profile = []

    for i, node in enumerate(path):
        data = G.nodes[node]
        lat  = data["y"]
        lon  = data["x"]
        elev = data.get("elevation", 0.0)

        coordinates.append([lon, lat])
        elevation_profile.append({
            "distance":  round(total_distance, 1),
            "elevation": round(elev, 1),
        })

        if i < len(path) - 1:
            next_node = path[i + 1]
            edges     = G.get_edge_data(node, next_node)

            # FIX: guard against missing edge data (shouldn't happen but graph can have gaps)
            if not edges:
                continue

            edge   = min(edges.values(), key=lambda e: e.get("length", 0))
            length = edge.get("length", 0)
            total_distance += length

            elev_next = G.nodes[next_node].get("elevation", 0.0)
            diff = elev_next - elev
            if diff > 0.5:
                total_gain += diff
            elif diff < -0.5:
                total_loss += abs(diff)

    return {
        "distance_m":       round(total_distance, 1),
        "elevation_gain_m": round(total_gain, 1),
        "elevation_loss_m": round(total_loss, 1),
        "coordinates":      coordinates,
        "elevation_profile": elevation_profile,
    }


# ---------------------------------------------------------------------------
# Circular routes
# ---------------------------------------------------------------------------

def _compute_circular_routes(G, origin_lat: float, origin_lon: float,
                               distance_m: float) -> list[dict]:
    """
    3 loop routes from origin back to origin, each ~distance_m long.
    Uses 3 compass bearings (0°, 120°, 240°) for varied terrain.
    """
    origin_node = nearest_node(G, origin_lat, origin_lon)
    half        = distance_m / 2

    dlat_per_m = 1 / 111_000
    dlon_per_m = 1 / (111_000 * math.cos(math.radians(origin_lat)))

    routes = []

    for angle_deg in [0, 120, 240]:
        angle_rad = math.radians(angle_deg)
        mid_lat   = origin_lat + half * dlat_per_m * math.cos(angle_rad)
        mid_lon   = origin_lon + half * dlon_per_m * math.sin(angle_rad)
        mid_node  = nearest_node(G, mid_lat, mid_lon)

        if mid_node == origin_node:
            logger.warning(f"Circular: midpoint == origin for angle {angle_deg}°, skipping")
            continue

        try:
            path_out  = nx.shortest_path(G, source=origin_node, target=mid_node,
                                          weight=PROFILES["balanced"])
            path_back = nx.shortest_path(G, source=mid_node, target=origin_node,
                                          weight=PROFILES["balanced"])
            full_path = path_out + path_back[1:]
            stats     = _path_stats(G, full_path)
            routes.append(stats)
        except nx.NetworkXNoPath:
            logger.warning(f"Circular: no path found for angle {angle_deg}°")

    if not routes:
        return []

    routes.sort(key=lambda r: r["elevation_gain_m"])
    for i, route in enumerate(routes[:3]):
        route["profile"] = ["flattest", "balanced", "steepest"][i]

    return routes[:3]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_routes(
    G,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float   = None,
    dest_lon: float   = None,
    mode: str         = "point_to_point",
    loop_distance_km: float = 5.0,
) -> list[dict]:
    """
    Returns up to 3 routes sorted flattest → balanced → steepest.
    mode='point_to_point' — A to B routes.
    mode='loop'           — circular routes starting and ending at origin.
    """
    if mode == "loop":
        return _compute_circular_routes(G, origin_lat, origin_lon, loop_distance_km * 1000)

    if dest_lat is None or dest_lon is None:
        raise ValueError("dest_lat and dest_lon are required for point_to_point mode")

    origin_node = nearest_node(G, origin_lat, origin_lon)
    dest_node   = nearest_node(G, dest_lat, dest_lon)

    # FIX: if origin == dest node (very close points), return empty rather than crash
    if origin_node == dest_node:
        logger.warning("Origin and destination snapped to the same node — move points further apart")
        return []

    routes = []

    for profile_name, cost_fn in PROFILES.items():
        try:
            path  = nx.shortest_path(G, source=origin_node, target=dest_node, weight=cost_fn)
            stats = _path_stats(G, path)
            # FIX: don't include node_path in the returned dict — it's internal and not serialisable
            routes.append({"profile": profile_name, **stats})
        except nx.NetworkXNoPath:
            logger.warning(f"No path found for profile: {profile_name}")

    if not routes:
        return []

    routes.sort(key=lambda r: r["elevation_gain_m"])
    labels = ["flattest", "balanced", "steepest"]
    for i, route in enumerate(routes):
        route["profile"] = labels[i]

    return routes


def _perpendicular_waypoint(
    origin_lat: float, origin_lon: float,
    dest_lat: float,   dest_lon: float,
    offset_km: float,
) -> tuple[float, float]:
    """Return a point offset perpendicularly from the midpoint of A→B by offset_km."""
    mid_lat = (origin_lat + dest_lat) / 2
    mid_lon = (origin_lon + dest_lon) / 2

    dlat = dest_lat - origin_lat
    dlon = dest_lon - origin_lon
    length = math.sqrt(dlat ** 2 + dlon ** 2)
    if length == 0:
        return mid_lat, mid_lon

    # Rotate 90° to get perpendicular unit vector
    perp_lat = -dlon / length
    perp_lon =  dlat / length

    lat_per_km = 1.0 / 111.0
    lon_per_km = 1.0 / (111.0 * math.cos(math.radians(mid_lat)))

    return (
        mid_lat + perp_lat * offset_km * lat_per_km,
        mid_lon + perp_lon * offset_km * lon_per_km,
    )


def compute_constrained_route(
    G,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    profile: str,
    target_km: float,
) -> dict:
    """Route from A to B of approximately target_km using the given elevation profile.

    If target_km is longer than the direct route, inserts a perpendicular detour
    waypoint and binary-searches the offset until the path length ≈ target_km.
    """
    cost_fn = PROFILES[profile]
    origin_node = nearest_node(G, origin_lat, origin_lon)
    dest_node   = nearest_node(G, dest_lat,   dest_lon)

    def _route_via(wp_lat, wp_lon):
        wp_node = nearest_node(G, wp_lat, wp_lon)
        if wp_node in (origin_node, dest_node):
            return None
        try:
            p1 = nx.shortest_path(G, source=origin_node, target=wp_node, weight=cost_fn)
            p2 = nx.shortest_path(G, source=wp_node,     target=dest_node, weight=cost_fn)
            return p1 + p2[1:]
        except nx.NetworkXNoPath:
            return None

    try:
        direct_path = nx.shortest_path(G, source=origin_node, target=dest_node, weight=cost_fn)
    except nx.NetworkXNoPath:
        raise ValueError("No path found between these points")

    direct_stats = _path_stats(G, direct_path)
    direct_km    = direct_stats["distance_m"] / 1000

    if target_km <= direct_km * 1.1:
        direct_stats["profile"] = profile
        return direct_stats

    # Binary search the perpendicular offset (8 iterations ≈ 1% accuracy)
    lo, hi = 0.0, target_km * 0.8
    best = direct_stats

    for _ in range(8):
        offset = (lo + hi) / 2
        wp_lat, wp_lon = _perpendicular_waypoint(
            origin_lat, origin_lon, dest_lat, dest_lon, offset
        )
        path = _route_via(wp_lat, wp_lon)
        if path is None:
            hi = offset
            continue
        stats = _path_stats(G, path)
        best  = stats
        if stats["distance_m"] / 1000 < target_km:
            lo = offset
        else:
            hi = offset

    best["profile"] = profile
    return best


def compute_custom_weight_route(
    G,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    weight: float,
) -> dict:
    """Single route with a custom elevation weight for interactive experimentation.
    cost(edge) = length + weight * uphill_gain"""
    origin_node = nearest_node(G, origin_lat, origin_lon)
    dest_node = nearest_node(G, dest_lat, dest_lon)

    def cost(u, v, data):
        if isinstance(data, dict) and all(isinstance(k, int) for k in data):
            d = min(data.values(), key=lambda x: x.get("length", 1))
        else:
            d = data
        length = max(d.get("length", 1), 0.1)
        uphill = max(0, d.get("grade", 0) * length)
        return max(1.0, length + weight * uphill)

    path = nx.shortest_path(G, source=origin_node, target=dest_node, weight=cost)
    stats = _path_stats(G, path)
    stats["profile"] = "custom"
    return stats
