"""
weight_experiment.py

Course feedback experiment: how does varying the elevation-gain weight in the
routing cost function change the resulting route?

cost(edge) = length + WEIGHT * uphill_gain

  WEIGHT < 0  -> rewards climbing (seeks hills out)
  WEIGHT = 0  -> pure shortest path, no elevation consideration
  WEIGHT > 0  -> penalises climbing (avoids hills)

Runs the same origin -> destination request (Stephansdom -> Grinzing, the
same example pair shown in the app's own placeholder text) and records
distance vs. elevation gain for each weight tested — producing a CSV table
and two charts for the presentation.

Two modes:
  py -3.14 experiments/weight_experiment.py               -> full sweep
      (tests 9 weights from -20000 to +20000 to show where routes saturate)
  py -3.14 experiments/weight_experiment.py --production   -> app-only
      (tests only the 3 weights the live app actually uses today:
       -ELEVATION_GAIN_WEIGHT, 0, +ELEVATION_GAIN_WEIGHT, imported directly
       from backend/router.py so it always matches production)

Each mode writes its own CSV/PNG files (suffixed _production) so results
from both runs can be compared side by side.
"""

import os
import sys
import csv
import argparse
import pickle
import networkx as nx
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.router import nearest_node, _path_stats, ELEVATION_GAIN_WEIGHT

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GRAPH_PATH = os.path.join(DATA_DIR, "vienna_walk_graph_enriched.pkl")

# Stephansdom -> Grinzing — the same example pair shown in the app's UI
ORIGIN = (48.2082, 16.3738)
DEST = (48.2462, 16.3334)

FULL_SWEEP = [-20000, -5000, -1000, -200, 0, 200, 1000, 5000, 20000]
PRODUCTION_WEIGHTS = [-ELEVATION_GAIN_WEIGHT, 0, ELEVATION_GAIN_WEIGHT]


def make_cost_fn(weight):
    def cost(u, v, data):
        if isinstance(data, dict) and 0 in data:
            d = min(data.values(), key=lambda x: x.get("length", 1))
        else:
            d = data
        length = d.get("length", 1)
        grade = d.get("grade", 0)
        uphill_gain = max(0, grade * length)
        return max(1.0, length + weight * uphill_gain)
    return cost


def run_experiment(weights):
    print("Loading graph...")
    with open(GRAPH_PATH, "rb") as f:
        G = pickle.load(f)
    print(f"Graph loaded: {len(G.nodes):,} nodes, {len(G.edges):,} edges\n")

    origin_node = nearest_node(G, *ORIGIN)
    dest_node = nearest_node(G, *DEST)

    results = []
    for weight in weights:
        cost_fn = make_cost_fn(weight)
        path = nx.shortest_path(G, source=origin_node, target=dest_node, weight=cost_fn)
        stats = _path_stats(G, path)
        results.append({
            "weight": weight,
            "distance_m": stats["distance_m"],
            "elevation_gain_m": stats["elevation_gain_m"],
            "elevation_loss_m": stats["elevation_loss_m"],
            "node_count": len(path),
        })
        print(f"weight={weight:>9.1f}  distance={stats['distance_m']:>8.1f} m  "
              f"gain={stats['elevation_gain_m']:>6.1f} m  loss={stats['elevation_loss_m']:>6.1f} m")

    return results


def save_csv(results, path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"\nSaved table: {path}")


def save_charts(results, out_dir, suffix):
    weights = [r["weight"] for r in results]
    distances = [r["distance_m"] for r in results]
    gains = [r["elevation_gain_m"] for r in results]

    # Chart 1: elevation gain vs weight
    plt.figure(figsize=(7, 4.5))
    plt.plot(weights, gains, marker="o", color="#4a90d9")
    plt.xlabel("Elevation weight (cost per metre of uphill climb)")
    plt.ylabel("Total elevation gain (m)")
    plt.title("Elevation Gain vs. Weight\nStephansdom -> Grinzing")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    p1 = os.path.join(out_dir, f"gain_vs_weight{suffix}.png")
    plt.savefig(p1, dpi=150)
    plt.close()
    print(f"Saved chart: {p1}")

    # Chart 2: distance vs elevation gain (the trade-off curve)
    plt.figure(figsize=(7, 4.5))
    order = sorted(range(len(results)), key=lambda i: gains[i])
    plt.plot([gains[i] for i in order], [distances[i] for i in order],
              marker="o", color="#e91e63")
    for r in results:
        plt.annotate(str(r["weight"]), (r["elevation_gain_m"], r["distance_m"]),
                     textcoords="offset points", xytext=(5, 5), fontsize=8)
    plt.xlabel("Total elevation gain (m)")
    plt.ylabel("Total distance (m)")
    plt.title("Distance vs. Elevation Gain Trade-off\nStephansdom -> Grinzing")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    p2 = os.path.join(out_dir, f"tradeoff_curve{suffix}.png")
    plt.savefig(p2, dpi=150)
    plt.close()
    print(f"Saved chart: {p2}")


def save_comparison_chart(out_dir):
    """Overlays the full sweep and the production-only run on one chart,
    so it's obvious which points on the curve the live app actually uses."""
    def load(path):
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    full = load(os.path.join(out_dir, "weight_experiment_results.csv"))
    prod = load(os.path.join(out_dir, "weight_experiment_results_production.csv"))

    full_gains = [float(r["elevation_gain_m"]) for r in full]
    full_dist = [float(r["distance_m"]) for r in full]
    prod_gains = [float(r["elevation_gain_m"]) for r in prod]
    prod_dist = [float(r["distance_m"]) for r in prod]

    order = sorted(range(len(full)), key=lambda i: full_gains[i])

    plt.figure(figsize=(7, 4.5))
    plt.plot([full_gains[i] for i in order], [full_dist[i] for i in order],
              marker="o", color="#aaaaaa", label="Full sweep (-20000 to +20000)")
    plt.scatter(prod_gains, prod_dist, color="#e91e63", s=110, zorder=5,
                label="Live app today (±5000, 0)")
    for r in prod:
        plt.annotate(r["weight"], (float(r["elevation_gain_m"]), float(r["distance_m"])),
                     textcoords="offset points", xytext=(6, 6), fontsize=8, color="#e91e63")
    plt.xlabel("Total elevation gain (m)")
    plt.ylabel("Total distance (m)")
    plt.title("Production vs. Full Sweep\nStephansdom -> Grinzing")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    p = os.path.join(out_dir, "tradeoff_comparison.png")
    plt.savefig(p, dpi=150)
    plt.close()
    print(f"Saved comparison chart: {p}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--production", action="store_true",
        help="Only test the 3 weights the live app actually uses today "
             "(-ELEVATION_GAIN_WEIGHT, 0, +ELEVATION_GAIN_WEIGHT) instead of the full sweep."
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Skip routing entirely and just overlay the existing full-sweep and "
             "production CSVs into one comparison chart (run both modes first)."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    out_dir = os.path.dirname(__file__)

    if args.compare:
        save_comparison_chart(out_dir)
        sys.exit(0)

    if args.production:
        print(f"Mode: production only (weights actually used by the app today, ±{ELEVATION_GAIN_WEIGHT:.0f})\n")
        weights = PRODUCTION_WEIGHTS
        suffix = "_production"
    else:
        print("Mode: full sweep (-20000 to +20000)\n")
        weights = FULL_SWEEP
        suffix = ""

    results = run_experiment(weights)
    save_csv(results, os.path.join(out_dir, f"weight_experiment_results{suffix}.csv"))
    save_charts(results, out_dir, suffix)
