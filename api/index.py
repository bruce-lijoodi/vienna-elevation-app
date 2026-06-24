import os
# Default to GraphHopper mode on Vercel — no local graph available.
# Override by setting USE_GRAPHHOPPER=0 in Vercel Variables if needed.
os.environ.setdefault("USE_GRAPHHOPPER", "1")

from backend.main import app
