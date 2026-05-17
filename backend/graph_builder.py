"""
graph_builder.py

This file is responsible for building the "map" our app uses to calculate routes.
It does 3 things:
  1. Downloads Vienna's walking street network from OpenStreetMap (like a road map as data)
  2. Asks an elevation API how high above sea level each point on the map is
  3. Calculates the slope (steepness) of each street segment

The result is saved to disk so we don't have to re-download it every time.
"""

import osmnx as ox        # Library for downloading and working with street maps
ox.settings.max_query_area_size = 2500000000  # Allow larger query areas
import pickle             # Used to save and load Python objects to/from files
import os                 # Used to work with file paths and directories
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# __file__ is the path to this script. We go one level up to reach the project
# root, then into the "data" folder where we store downloaded files.
DATA_DIR = os.path.join(os.path.dirname(__file__), "../data")

# Full path to where we'll save the downloaded street graph
GRAPH_PATH = os.path.join(DATA_DIR, "vienna_walk_graph.pkl")

# The geographic bounding box that covers Vienna.
# Format: (south, west, north, east) — these are lat/lon coordinates.
VIENNA_BBOX = (48.10, 16.18, 48.33, 16.58)


# ---------------------------------------------------------------------------
# Step 1: Download the street network from OpenStreetMap
# ---------------------------------------------------------------------------

def fetch_vienna_graph(force_refresh: bool = False):
    """
    Downloads Vienna's walkable street network and saves it locally.
    
    If a saved version already exists, it loads that instead of downloading again.
    Set force_refresh=True to force a fresh download.
    """
    # Enable caching so we never re-download the same data twice
    ox.settings.use_cache = False
    # Make sure the data folder exists (create it if it doesn't)
    os.makedirs(DATA_DIR, exist_ok=True)

    # If we already downloaded the graph before, just load it from disk
    if os.path.exists(GRAPH_PATH) and not force_refresh:
        print("Found cached graph — loading from disk...")
        with open(GRAPH_PATH, "rb") as f:
            return pickle.load(f)

    # Otherwise, download it fresh from OpenStreetMap
    print("Downloading Vienna walk network from OpenStreetMap...")
    print("(This usually takes 1-2 minutes)")

    south, west, north, east = VIENNA_BBOX


    # Download walk network within 3km radius of Stephansdom
    # This covers enough hilly terrain without overwhelming the Overpass API
    G = ox.graph_from_point(
        center_point=(48.2082, 16.3738),  # Stephansdom coordinates
        dist=8000,                         # 8km radius
        network_type="walk",
        simplify=True,
    )

    print(f"  Downloaded {len(G.nodes):,} nodes and {len(G.edges):,} edges")

    # Save the graph to disk using pickle so we can reuse it later
    with open(GRAPH_PATH, "wb") as f:
        pickle.dump(G, f)
    print(f"  Saved to {GRAPH_PATH}")

    return G


# ---------------------------------------------------------------------------
# Step 2: Get elevation data for every node (street intersection)
# ---------------------------------------------------------------------------

def attach_elevations(G):
    """
    Reads elevation for every node directly from the local SRTM file.
    This is much faster and more reliable than using an API since
    everything happens offline on your computer.
    """
    import rasterio  # Library for reading geographic raster files like our SRTM .tif

    # Path to the SRTM elevation file we downloaded
    srtm_path = os.path.join(DATA_DIR, "srtm/srtm_40_03.tif")

    print(f"Reading elevations from local SRTM file...")

    # Open the SRTM file and read elevations for all nodes at once
    with rasterio.open(srtm_path) as src:
        # Read the entire elevation grid into memory once (faster than reading node by node)
        elevation_data = src.read(1)
        height, width = elevation_data.shape

        for node_id, data in G.nodes(data=True):
            lat = data["y"]  # Latitude
            lon = data["x"]  # Longitude

            # Convert lat/lon to the row/column position in the raster file
            row, col = src.index(lon, lat)

            # Make sure the position is within the bounds of the file
            if 0 <= row < height and 0 <= col < width:
                G.nodes[node_id]["elevation"] = float(elevation_data[row, col])
            else:
                # If outside bounds, default to 0m
                G.nodes[node_id]["elevation"] = 0.0
    print(f"  Elevations attached to all {len(G.nodes):,} nodes successfully.")
    return G


# ---------------------------------------------------------------------------
# Step 3: Calculate the slope (grade) of each street segment
# ---------------------------------------------------------------------------

def compute_edge_grades(G):
    """
    Calculates how steep each street segment (edge) is.
    
    Grade is calculated as: (elevation change) / (horizontal distance)
    A positive grade means going uphill, negative means downhill.
    
    We store both the signed grade and the absolute grade on each edge.
    """
    for u, v, data in G.edges(data=True):
        # Get the elevation at the start and end of this street segment
        elev_u = G.nodes[u].get("elevation", 0)  # elevation at start node
        elev_v = G.nodes[v].get("elevation", 0)  # elevation at end node

        # Get the length of this segment in metres
        length = data.get("length", 1)

        # Only calculate grade if there is a meaningful elevation difference
        # SRTM has ~90m resolution so differences on short edges are noise
        elev_diff = elev_v - elev_u

        if length > 0 and abs(elev_diff) > 0:
            data["grade"] = elev_diff / length
        else:
            data["grade"] = 0.0

        # Also store the absolute grade (ignoring direction) for filtering steep segments
        data["grade_abs"] = abs(data["grade"])

    return G

# ---------------------------------------------------------------------------
# Main pipeline: runs all 3 steps in order
# ---------------------------------------------------------------------------

def build_graph(force_refresh: bool = False):
    """
    Runs the full pipeline:
      1. Download street network
      2. Attach elevations
      3. Compute edge grades
    Then saves the final enriched graph to disk.
    """
    print("=== Starting graph build pipeline ===\n")

    G = fetch_vienna_graph(force_refresh=force_refresh)
    G = attach_elevations(G)
    G = compute_edge_grades(G)

    # Save the fully enriched graph under a new filename
    enriched_path = GRAPH_PATH.replace(".pkl", "_enriched.pkl")
    with open(enriched_path, "wb") as f:
        pickle.dump(G, f)

    print(f"\n=== Done! Enriched graph saved to {enriched_path} ===")
    return G


# ---------------------------------------------------------------------------
# Entry point: runs when you execute this file directly
# e.g. python graph_builder.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_graph()