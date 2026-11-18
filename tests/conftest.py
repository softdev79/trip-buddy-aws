import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ["shared", "services/mcp_server", "services/trip_buddy", "services/guide_agent"]:
    sys.path.insert(0, str(ROOT / p))
