from __future__ import annotations

import importlib
import sys

# Alias the kimi_code package to consilium for compatibility.
sys.modules[__name__] = importlib.import_module("consilium")
