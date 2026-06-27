"""Put the data/ directory on sys.path so tests can `import digest`, `import
cashflow`, etc. — the pipeline scripts are flat modules in data/, not a package."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
