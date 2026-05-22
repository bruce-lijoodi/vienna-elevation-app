"""
router.py

This file is the brain of our routing system.
Given a start point and end point, it calculates 3 different routes:

  1. Flattest  — avoids uphill as much as possible (good for accessibility)
  2. Balanced  — a mix of short distance and moderate elevation
  3. Steepest  — seeks out the most uphill paths (good for fitness)

How it works:
  - The street network is treated as a "graph" (a web of connected nodes and edges)
  - We use Dijkstra's algorithm to find the best path between two nodes
  - The trick is that we change what "best" means by using different cost functions
  - A cost function tells the algorithm how "expensive" each street segment is
  - For flattest routes, uphill segments are made very expensive so the algorithm avoids them
  - For steepest routes, uphill segments are made cheap so the algorithm seeks them out
"""

import math          # Used for distance calculations
import networkx as nx  # The graph library that runs Dijkstra's algorithm


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# This multiplier controls how much we penalise (or reward) elevation gain.
# A value of 20 means: 1 metre of uphill climb = 20 metres of extra "cost"
# The higher this number, the more aggressively the algorithm avoids hills.
ELEVATION_GAIN_WEIGHT = 5000.0

def _get_cost_fn(profile: str):
    """
    Returns a weight function compatible with NetworkX MultiDiGraph.
    - flattest: avoids uphill heavily
    - balanced: pure shortest distance
    - steepest: seeks uphill aggressively
    """
    def cost(u, v, data):
        # Extract edge attributes correctly for MultiDiGraph
        if isinstance(data, dict) and 0 in data:
            d = min(data.values(), key=lambda x: x.get("length", 1))
        else:
            d = data

        length = d.get("length", 1)
        grade = d.get("grade", 0)
        uphill_gain = max(0, grade * length)

        if profile == "flattest":
            # Heavily penalise uphill
            return length + ELEVATION_GAIN_WEIGHT * uphill_gain
        elif profile == "balanced":
            # Pure shortest distance — no elevation consideration
            return length
        else:  # steepest
            # Reward uphill segments
            return max(1.0, length - ELEVATION_GAIN_WEIGHT * uphill_gain)

    return cost


# Map profile names to their cost functions for easy lookup
PROFILES = {
    "flattest": _get_cost_fn("flattest"),
    "balanced": _get_cost_fn("balanced"),
    "steepest": _get_cost_fn("steepest"),
}

# ---------------------------------------------------------------------------
# Helper: find the nearest graph node to a lat/lon coordinate
# ---------------------------------------------------------------------------

def nearest_node(G, lat: float, lon: float) -> int:
    """
    Given a latitude and longitude, finds the closest node (intersection)
    in our street graph.
    
    This is needed because the user picks a point on the map, but our
    routing algorithm works with graph nodes — so we need to snap the
    user's point to the nearest node.
    """
    best_node = None
    best_dist = float("inf")  # Start with an infinitely large distance

    for node_id, data in G.nodes(data=True):
        # Calculate straight-line distance between the target point and this node
        # We use simple Pythagorean distance on lat/lon (good enough for short distances)
        dlat = data["y"] - lat
        dlon = data["x"] - lon
        dist = math.sqrt(dlat**2 + dlon**2)

        if dist < best_dist:
            best_dist = dist
            best_node = node_id

    return best_node


# ---------------------------------------------------------------------------
# Helper: calculate stats for a given path through the graph
# ---------------------------------------------------------------------------

def _path_stats(G, path: list[int]) -> dict:
    """
    Given a list of node IDs representing a route, calculates:
      - Total distance in metres
      - Total elevation gain (uphill metres)
      - Total elevation loss (downhill metres)
      - List of [longitude, latitude] coordinates (for drawing on the map)
      - Elevation profile (distance vs elevation, for the chart)
    """
    total_distance = 0.0
    total_gain = 0.0
    total_loss = 0.0
    coordinates = []       # Will hold [lon, lat] pairs for each node
    elevation_profile = [] # Will hold {distance, elevation} for each node

    for i, node in enumerate(path):
        node_data = G.nodes[node]
        lat = node_data["y"]
        lon = node_data["x"]
        elev = node_data.get("elevation", 0)

        # GeoJSON format uses [longitude, latitude] order (opposite of what you might expect)
        coordinates.append([lon, lat])

        # Record where we are on the elevation profile chart
        elevation_profile.append({
            "distance": round(total_distance, 1),
            "elevation": round(elev, 1),
        })

        # If this isn't the last node, look ahead to the next segment
        if i < len(path) - 1:
            next_node = path[i + 1]

            # Get the edge data between this node and the next
            # (There may be multiple edges between two nodes, so we pick the shortest)
            edges = G.get_edge_data(node, next_node)
            edge = min(edges.values(), key=lambda e: e.get("length", 0)) if edges else {}
            length = edge.get("length", 0)

            total_distance += length

            # Calculate elevation change to this next node
            elev_next = G.nodes[next_node].get("elevation", 0)
            diff = elev_next - elev

            # Only count meaningful elevation changes (filter out SRTM noise)
            if diff > 0.5:  # More than 0.5m uphill counts as gain/uphill
                total_gain += diff   # Going uphill
            elif diff < -0.5:  # More than 0.5m downhill counts as loss/downhill
                total_loss += abs(diff)  # Going downhill

    return {
        "distance_m": round(total_distance, 1),
        "elevation_gain_m": round(total_gain, 1),
        "elevation_loss_m": round(total_loss, 1),
        "coordinates": coordinates,
        "elevation_profile": elevation_profile,
    }


# ---------------------------------------------------------------------------
# Circular route: loop from origin back to origin
# ---------------------------------------------------------------------------

def _compute_circular_routes(G, origin_lat: float, origin_lon: float, distance_m: float) -> list[dict]:
    """
    Generates 3 loop routes starting and ending at origin, each approximately
    distance_m long. Uses 3 compass directions (0°, 120°, 240°) to find
    different midpoints so the loops go through different terrain.
    """
    origin_node = nearest_node(G, origin_lat, origin_lon)
    half = distance_m / 2

    # Degree offsets for half the target distance at Vienna's latitude
    dlat_per_m = 1 / 111000
    dlon_per_m = 1 / (111000 * math.cos(math.radians(origin_lat)))

    routes = []

    for angle_deg in [0, 120, 240]:
        angle_rad = math.radians(angle_deg)
        mid_lat = origin_lat + half * dlat_per_m * math.cos(angle_rad)
        mid_lon = origin_lon + half * dlon_per_m * math.sin(angle_rad)
        mid_node = nearest_node(G, mid_lat, mid_lon)

        if mid_node == origin_node:
            continue

        try:
            path_out  = nx.shortest_path(G, source=origin_node, target=mid_node,  weight=PROFILES["balanced"])
            path_back = nx.shortest_path(G, source=mid_node,    target=origin_node, weight=PROFILES["balanced"])
            full_path = path_out + path_back[1:]  # avoid duplicate node at junction
            stats = _path_stats(G, full_path)
            routes.append(stats)
        except nx.NetworkXNoPath:
            print(f"  No circular path found for angle {angle_deg}°")

    routes.sort(key=lambda r: r["elevation_gain_m"])
    labels = ["flattest", "balanced", "steepest"]
    for i, route in enumerate(routes[:3]):
        route["profile"] = labels[i]

    return routes[:3]


# ---------------------------------------------------------------------------
# Main function: compute all 3 routes (point-to-point or loop)
# ---------------------------------------------------------------------------

def compute_routes(
    G,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float = None,
    dest_lon: float = None,
    mode: str = "point_to_point",
    loop_distance_km: float = 5.0,
) -> list[dict]:
    """
    Calculates 3 routes sorted flattest → balanced → steepest.
    mode="point_to_point": routes between origin and destination.
    mode="loop": circular routes starting and ending at origin.
    """
    if mode == "loop":
        return _compute_circular_routes(G, origin_lat, origin_lon, loop_distance_km * 1000)

    # Snap the user's coordinates to the nearest nodes in our graph
    origin_node = nearest_node(G, origin_lat, origin_lon)
    dest_node = nearest_node(G, dest_lat, dest_lon)

    routes = []

    # Run Dijkstra's algorithm once for each profile
    for profile_name, cost_fn in PROFILES.items():
        try:
            path = nx.shortest_path(
                G,
                source=origin_node,
                target=dest_node,
                weight=cost_fn,
            )
            stats = _path_stats(G, path)
            routes.append({
                "profile": profile_name,
                "node_path": path,
                **stats,
            })
        except nx.NetworkXNoPath:
            print(f"  No path found for profile: {profile_name}")

    routes.sort(key=lambda r: r["elevation_gain_m"])
    labels = ["flattest", "balanced", "steepest"]
    for i, route in enumerate(routes):
        route["profile"] = labels[i]

    return routes