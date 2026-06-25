"""
main.py

FastAPI web server for the Vienna Elevation Router.
Routing and elevation data are provided entirely by the GraphHopper API.

Exposes:
  GET  /                   — serves the frontend HTML
  GET  /health             — liveness check
  POST /routes             — returns 3 elevation-aware route options
  POST /routes/constrained — adjusts a route to a target distance/time
"""

import logging
import os

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from backend.router_gh import (
    compute_routes,
    compute_constrained_route,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "../frontend/index.html")
FRONTEND_DIR  = os.path.join(os.path.dirname(__file__), "../frontend")

VIENNA_BOUNDS = {"lat": (48.10, 48.33), "lon": (16.18, 16.58)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Vienna Elevation Router started — routing via GraphHopper API.")
    yield


app = FastAPI(
    title="Vienna Elevation Router",
    description="Elevation-aware walking routes in Vienna powered by GraphHopper",
    version="2.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _in_vienna(lat: float, lon: float) -> bool:
    return (VIENNA_BOUNDS["lat"][0] <= lat <= VIENNA_BOUNDS["lat"][1] and
            VIENNA_BOUNDS["lon"][0] <= lon <= VIENNA_BOUNDS["lon"][1])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RouteRequest(BaseModel):
    origin_lat: float
    origin_lon: float
    dest_lat: float | None = None
    dest_lon: float | None = None
    mode: str = "point_to_point"  # "point_to_point" | "loop"
    loop_distance_km: float = 5.0

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v):
        if v not in ("point_to_point", "loop"):
            raise ValueError("mode must be 'point_to_point' or 'loop'")
        return v

    @field_validator("loop_distance_km")
    @classmethod
    def validate_loop_distance(cls, v):
        if not (0.5 <= v <= 50.0):
            raise ValueError("loop_distance_km must be between 0.5 and 50")
        return v


class ElevationPoint(BaseModel):
    distance: float
    elevation: float


class RouteResult(BaseModel):
    profile: str
    distance_m: float
    elevation_gain_m: float
    elevation_loss_m: float
    coordinates: list[list[float]]
    elevation_profile: list[ElevationPoint]


class RouteResponse(BaseModel):
    routes: list[RouteResult]


class ConstrainedRouteRequest(BaseModel):
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    profile: str = "balanced"
    target_km: float

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, v):
        if v not in ("flattest", "balanced", "steepest"):
            raise ValueError("profile must be flattest, balanced, or steepest")
        return v

    @field_validator("target_km")
    @classmethod
    def validate_target(cls, v):
        if not (0.1 <= v <= 50.0):
            raise ValueError("target_km must be between 0.1 and 50")
        return v


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def serve_frontend():
    if not os.path.exists(FRONTEND_PATH):
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(FRONTEND_PATH)


@app.get("/health")
def health():
    return {"status": "ok", "routing": "graphhopper"}


@app.post("/routes", response_model=RouteResponse)
def get_routes(req: RouteRequest):
    if not _in_vienna(req.origin_lat, req.origin_lon):
        raise HTTPException(status_code=400, detail="Origin coordinates are outside Vienna")

    if req.mode == "point_to_point":
        if req.dest_lat is None or req.dest_lon is None:
            raise HTTPException(status_code=400, detail="Destination required for point_to_point mode")
        if not _in_vienna(req.dest_lat, req.dest_lon):
            raise HTTPException(status_code=400, detail="Destination coordinates are outside Vienna")

    try:
        routes = compute_routes(
            None,
            req.origin_lat, req.origin_lon,
            req.dest_lat, req.dest_lon,
            mode=req.mode,
            loop_distance_km=req.loop_distance_km,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not routes:
        raise HTTPException(status_code=404, detail="No routes found between these points")

    return RouteResponse(routes=routes)


@app.post("/routes/constrained", response_model=RouteResult)
def get_constrained_route(req: ConstrainedRouteRequest):
    """Adjust a route to a target distance while keeping its elevation character."""
    if not _in_vienna(req.origin_lat, req.origin_lon):
        raise HTTPException(status_code=400, detail="Origin coordinates are outside Vienna")
    if not _in_vienna(req.dest_lat, req.dest_lon):
        raise HTTPException(status_code=400, detail="Destination coordinates are outside Vienna")
    try:
        result = compute_constrained_route(
            None,
            req.origin_lat, req.origin_lon,
            req.dest_lat,   req.dest_lon,
            req.profile,    req.target_km,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return RouteResult(**result)
