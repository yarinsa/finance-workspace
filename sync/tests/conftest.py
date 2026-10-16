"""Put sync/ on sys.path so tests can `import activities`, `import workflows`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
