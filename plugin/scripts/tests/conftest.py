"""Put the plugin scripts/ dir on sys.path so tests can `import digest`,
`import cashflow`, `import goals`, etc. — the pipeline scripts are flat modules
in scripts/, not a package."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
