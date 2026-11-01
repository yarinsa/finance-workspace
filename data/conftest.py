"""Put the data/ directory on sys.path so tests can `import digest`, `import
cashflow`, etc. — the pipeline scripts are flat modules in data/, not a package."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The pipeline's DB readers (data/stores.py) connect with DATABASE_URL, which in a dev shell is the
# live database (and connecting migrates it). Data tests never reach it; DB behaviour is db/tests'.
os.environ["FINANCE_NO_DB"] = "1"
