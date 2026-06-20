# Vienna Elevation Router

An elevation-aware walking route planner for Vienna. Instead of just finding the shortest path, the app offers three route profiles so users can choose based on their preference.

| Profile | Description |
|---|---|
| 🟢 Flattest | Avoids uphill as much as possible — good for accessibility |
| 🟡 Balanced | Pure shortest path — no elevation consideration |
| 🔴 Steepest | Seeks out uphill segments — good for fitness training |

## Features

- **3 route profiles** computed simultaneously using Dijkstra's algorithm with custom cost functions
- **Elevation profile chart** for each route
- **Real-time navigation** — GPS tracking, remaining distance, ETA, speed, off-route detection
- **Loop/circular routes** — "Take a Lap" button with 2/5/10/20/30 km options
- **Two routing engines** — local OSMnx/SRTM or GraphHopper API (higher resolution)
- **Address search** via Nominatim geocoding
- **Mobile responsive** — works in any browser, no install required
- **Weight experiment panel** — test custom elevation weights interactively

## Running Locally

```bash
py -3.14 -m uvicorn backend.main:app --reload
```

Then open [http://localhost:8000](http://localhost:8000).

The enriched graph (`data/vienna_walk_graph_enriched.pkl`) is included in the repo and loads automatically on startup (~5 seconds).

## Using GraphHopper

Set your API key before starting the server:

```powershell
$env:GH_API_KEY="your-key-here"
py -3.14 -m uvicorn backend.main:app --reload
```

Then select **GraphHopper** in the routing engine toggle in the app. Without the key, the local OSMnx engine is used.

## Tech Stack

- **Backend** — FastAPI (Python), NetworkX (Dijkstra routing), OSMnx (street network)
- **Elevation data** — SRTM CGIAR-CSI v4.1, ~90m resolution (`srtm_40_03.tif`)
- **Frontend** — Vanilla JS, Leaflet.js (map), Chart.js (elevation chart), Nominatim (geocoding)
- **Deployment** — Railway (auto-deploys on push to `main`)

## Project Structure

```
backend/
  main.py           FastAPI server and API endpoints
  router.py         Local Dijkstra routing with elevation cost functions
  router_gh.py      GraphHopper API routing
  graph_builder.py  Downloads OSM street network and attaches SRTM elevation data

frontend/
  index.html        Single-file frontend (map, chart, navigation, UI)

experiments/
  weight_experiment.py   Weight sensitivity analysis script
  *.png / *.csv          Experiment results and charts

data/
  vienna_walk_graph_enriched.pkl   Pre-built street graph with elevation (64 MB)
  srtm/srtm_40_03.tif              SRTM elevation raster (Git LFS)
```

## Weight Experiment

The `experiments/` folder contains a script for exploring how changing the elevation weight affects routing:

```bash
# Full sweep (-20000 to +20000)
py -3.14 experiments/weight_experiment.py

# Only the 3 weights the live app uses today
py -3.14 experiments/weight_experiment.py --production

# Overlay both results on one comparison chart
py -3.14 experiments/weight_experiment.py --compare
```

## TU Wien — Location Based Services
