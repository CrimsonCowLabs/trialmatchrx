"""Write FastAPI's OpenAPI schema to a file (default: api/openapi.json) for `make types`."""

import json
import sys
from pathlib import Path

from app.main import app

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2) + "\n")
print(f"wrote {out}")
