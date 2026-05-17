"""
router_gh.py

GraphHopper Directions API router — drop-in replacement for router.py.
Makes three requests to the GH API (one per elevation profile) and maps
the responses to the same format the frontend and main.py already expect.

Activate with environment variables:
  $env:USE_GRAPHHOPPER="1"
  $env:GH_API_KEY="your_key_here"

Revert to local routing by omitting USE_GRAPHHOPPER.
"""

import os
import math
import urllib.request
import urllib.parse
import json

GH_URL = "https://graphhopper.com/api/1/route"
GH_KEY = os.getenv("GH_API_KEY", "")


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_path(gh_path: dict) -> dict:
    """Convert a single GraphHopper path into the RouteResult dict format."""
    raw = gh_path["points"]["coordinates"]  # [[lon, lat, elev], ...]

    coordinates = [[c[0], c[1]] for c in raw]
    elevations = [c[2] if len(c) > 2 else 0.0 for c in raw]

    total_gain = 0.0
    total_loss = 0.0
    cumulative_dist = 0.0
    elevation_profile = []

    for i, (coord, elev) in enumerate(zip(coordinates, elevations)):
        elevation_profile.append({
            "distance": round(cumulative_dist, 1),
            "elevation": round(elev, 1),
        })

        if i < len(coordinates) - 1:
            nxt = coordinates[i + 1]
            cumulative_dist += _haversine(coord[1], coord[0], nxt[1], nxt[0])

            diff = elevations[i + 1] - elev
            if diff > 0.5:
                total_gain += diff
            elif diff < -0.5:
                total_loss += abs(diff)

    return {
        "distance_m": round(gh_path.get("distance", cumulative_dist), 1),
        "elevation_gain_m": round(total_gain, 1),
        "elevation_loss_m": round(total_loss, 1),
        "coordinates": coordinates,
        "elevation_profile": elevation_profile,
    }


def _gh_request(payload: dict) -> dict:
    """Send a POST request to the GraphHopper API and return parsed JSON."""
    url = f"{GH_URL}?key={GH_KEY}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def compute_routes(G, origin_lat, origin_lon, dest_lat, dest_lon):
    """
    GraphHopper implementation of compute_routes.
    G is accepted but not used — routing is handled by the GH API.
    Returns the same list-of-dicts format as router.py.

    Uses GH's alternative_route algorithm to get up to 3 geographically
    different paths in a single request, then sorts them by elevation gain
    so the labelling (flattest / balanced / steepest) reflects actual terrain.
    """
    if not GH_KEY:
        raise RuntimeError("GH_API_KEY environment variable is not set.")

    payload = {
        "points": [[origin_lon, origin_lat], [dest_lon, dest_lat]],
        "profile": "foot",
        "elevation": True,
        "points_encoded": False,
        "algorithm": "alternative_route",
        "alternative_route.max_paths": 3,
        # Allow alternatives up to twice the cost of the shortest path
        "alternative_route.max_weight_factor": 2.0,
        # Allow alternatives that share up to 80% of the shortest path
        "alternative_route.max_share_factor": 0.8,
    }

    try:
        data = _gh_request(payload)
    except Exception as e:
        print(f"  GH error: {e}")
        return []

    paths = data.get("paths", [])
    if not paths:
        print("  GH: no paths returned")
        return []

    routes = [_parse_path(p) for p in paths]

    # Sort by elevation gain and label flattest → balanced → steepest
    routes.sort(key=lambda r: r["elevation_gain_m"])
    labels = ["flattest", "balanced", "steepest"]
    for i, route in enumerate(routes[:3]):
        route["profile"] = labels[i]
        print(f"  GH {labels[i]}: {route['distance_m']}m, +{route['elevation_gain_m']}m gain")

    return routes[:3]
