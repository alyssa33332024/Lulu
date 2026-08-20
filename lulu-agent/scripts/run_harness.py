from __future__ import annotations

import sys
from pathlib import Path

# Ensure lulu-agent root is on sys.path when run as script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.harness.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
