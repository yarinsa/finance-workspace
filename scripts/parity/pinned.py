"""Run one pipeline script in-process with the clock pinned: pinned.py <script.py> [args...].

PIN (ISO instant, default 2026-11-01T12:00:00+02:00) is the moment every `today`, `now()`
and `generated_at` sees, so two runs on the same data produce the same bytes."""
import os
import runpy
import sys

import time_machine

WHEN = os.environ.get("PIN", "2026-11-01T12:00:00+02:00")
script, *args = sys.argv[1:]
sys.argv = [script, *args]
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
with time_machine.travel(WHEN, tick=False):
    runpy.run_path(script, run_name="__main__")
