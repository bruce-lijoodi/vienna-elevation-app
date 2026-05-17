"""
main.py

This file is the web server for our application.
It uses FastAPI to create a REST API that the frontend (map interface) will talk to.

It exposes two endpoints:
  GET  /health  — a simple check to confirm the server is running
  POST /routes  — accepts origin + destination coordinates, returns 3 route options

To run the server:
  uvicorn backend.main:app --reload
"""

from fastapi import FastAPI, HTTPException   # FastAPI is our web framework
from fastapi.middleware.cors import CORSMiddleware  # Allows the frontend to talk to the backend
from fastapi.responses import FileResponse   # Used to serve the frontend HTML file
from pydantic import BaseModel               # Used to define and validate request/response data
import pickle                                # Used to load our saved graph from disk
import os                                    # Used for file path operations

# Import our own modules
from backend.graph_builder import build_graph

# Switch routers via environment variable — no code change needed to revert
USE_GRAPHHOPPER = os.getenv("USE_GRAPHHOPPER", "")
if USE_GRAPHHOPPER:
    from backend.router_gh import compute_routes
    print("Router: GraphHopper API")
else:
    from backend.router import compute_routes
    print("Router: local OSMnx/NetworkX")

# ---------------------------------------------------------------------------
# Create the FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Vienna Elevation Router",
    description="Returns 3 elevation-aware walking routes between two points in Vienna",
    version="1.0",
)

# Allow requests from any origin (needed so our frontend HTML can call the API)
# In a production app you would restrict this to your frontend's domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Load the graph when the server starts
# ---------------------------------------------------------------------------

# Path to the enriched graph file we built with graph_builder.py
DATA_DIR = os.path.join(os.path.dirname(__file__), "../data")
ENRICHED_GRAPH_PATH = os.path.join(DATA_DIR, "vienna_walk_graph_enriched.pkl")

# This variable will hold our graph in memory while the server is running
G = None


@app.on_event("startup")
def load_graph():
    """
    This function runs automatically when the server starts.
    It loads the pre-built graph from disk into memory so we can use it for routing.
    If no graph exists yet, it builds one from scratch (takes a few minutes).
    Skipped entirely when running in GraphHopper mode.
    """
    global G

    if USE_GRAPHHOPPER:
        print("GraphHopper mode — skipping local graph load.")
        return

    if os.path.exists(ENRICHED_GRAPH_PATH):
        print("Loading enriched graph from disk...")
        with open(ENRICHED_GRAPH_PATH, "rb") as f:
            G = pickle.load(f)
        print(f"Graph loaded: {len(G.nodes):,} nodes, {len(G.edges):,} edges")
    else:
        print("No cached graph found — building from scratch...")
        print("This will take a few minutes on first run.")
        G = build_graph()


# ---------------------------------------------------------------------------
# Request and Response data models
# ---------------------------------------------------------------------------
# Pydantic models define the shape of data coming in and going out.
# FastAPI uses these to automatically validate requests and document the API.
# ---------------------------------------------------------------------------

class RouteRequest(BaseModel):
    """The data we expect to receive when someone requests routes."""
    origin_lat: float   # Latitude of the starting point
    origin_lon: float   # Longitude of the starting point
    dest_lat: float     # Latitude of the destination
    dest_lon: float     # Longitude of the destination


class ElevationPoint(BaseModel):
    """A single point on the elevation profile chart."""
    distance: float    # How far along the route we are (metres)
    elevation: float   # Elevation at this point (metres above sea level)


class RouteResult(BaseModel):
    """A single route with all its details."""
    profile: str                          # "flattest", "balanced", or "steepest"
    distance_m: float                     # Total route distance in metres
    elevation_gain_m: float               # Total uphill climb in metres
    elevation_loss_m: float               # Total downhill in metres
    coordinates: list[list[float]]        # [[lon, lat], ...] for drawing on the map
    elevation_profile: list[ElevationPoint]  # [{distance, elevation}, ...] for the chart


class RouteResponse(BaseModel):
    """The full response containing all 3 routes."""
    routes: list[RouteResult]


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "../frontend/index.html")

@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_PATH)


@app.get("/health")
def health():
    """
    Simple health check endpoint.
    Visit http://localhost:8000/health to confirm the server is running.
    """
    return {
        "status": "ok",
        "graph_loaded": G is not None,
        "node_count": len(G.nodes) if G else 0,
    }


@app.post("/routes", response_model=RouteResponse)
def get_routes(req: RouteRequest):
    """
    Main endpoint — calculates and returns 3 routes between two points.

    Expects a JSON body with origin and destination coordinates.
    Returns 3 routes sorted flattest → balanced → steepest.
    """
    # In local mode, make sure the graph is loaded before we try to use it
    if G is None and not USE_GRAPHHOPPER:
        raise HTTPException(status_code=503, detail="Graph not loaded yet — please wait")

    # Make sure the coordinates are actually within Vienna's bounds
    if not (48.10 <= req.origin_lat <= 48.33 and 16.18 <= req.origin_lon <= 16.58):
        raise HTTPException(status_code=400, detail="Origin coordinates are outside Vienna")
    if not (48.10 <= req.dest_lat <= 48.33 and 16.18 <= req.dest_lon <= 16.58):
        raise HTTPException(status_code=400, detail="Destination coordinates are outside Vienna")

    # Calculate the 3 routes using our router module
    routes = compute_routes(
        G,
        req.origin_lat, req.origin_lon,
        req.dest_lat, req.dest_lon,
    )

    if not routes:
        raise HTTPException(status_code=404, detail="No routes found between these points")

    return RouteResponse(routes=routes)