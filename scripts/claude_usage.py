"""Measure Claude Code usage on this project from the local session logs.

Reads every ~/.claude/projects/*Code-Finance*/**/*.jsonl (main sessions, worktree
sessions and subagent sidechains), dedupes assistant messages by message id and
reports token use per ISO week, plus the context a session starts with (the first
assistant turn's prompt size) — the fixed overhead that CLAUDE.md, skills and MCP
tools add to every turn.

    poetry run python scripts/claude_usage.py                 # print the report
    poetry run python scripts/claude_usage.py --write NAME    # also save docs/claude-setup/measurements/NAME.{md,json}

"Weighted" tokens approximate what counts against the plan limit, using API price
ratios: input 1, cache write 1.25, cache read 0.1, output 5.
"""

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LOGS = Path.home() / ".claude" / "projects"
OUT = Path(__file__).resolve().parent.parent / "docs" / "claude-setup" / "measurements"
WEIGHTS = {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0}


def load(since=None):
    """Yield one dict per unique assistant message: session, sidechain, model, week, token counts."""
    seen = set()
    for path in LOGS.glob("*Code-Finance*/**/*.jsonl"):
        for line in path.open(errors="replace"):
            if '"assistant"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            m = e.get("message") or {}
            u = m.get("usage")
            if e.get("type") != "assistant" or not u or m.get("id") in seen:
                continue
            seen.add(m.get("id"))
            ts = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
            if since and ts.date() < since:
                continue
            yield {
                "session": e.get("sessionId") or path.stem,
                "sidechain": bool(e.get("isSidechain")) or "subagents" in path.parts,
                "model": m.get("model", "?"),
                "ts": ts,
                "week": f"{ts.isocalendar()[0]}-W{ts.isocalendar()[1]:02d}",
                "input": u.get("input_tokens", 0),
                "cache_write": u.get("cache_creation_input_tokens", 0),
                "cache_read": u.get("cache_read_input_tokens", 0),
                "output": u.get("output_tokens", 0),
            }


def weighted(r):
    return sum(r[k] * w for k, w in WEIGHTS.items())


def report(rows):
    rows.sort(key=lambda r: r["ts"])
    weeks = defaultdict(lambda: defaultdict(float))
    sessions = defaultdict(list)
    for r in rows:
        w = weeks[r["week"]]
        for k in WEIGHTS:
            w[k] += r[k]
        w["weighted"] += weighted(r)
        w["turns"] += 1
        w["sub_weighted"] += weighted(r) if r["sidechain"] else 0
        sessions[(r["session"], r["sidechain"])].append(r)
    for (sid, side), rs in sessions.items():
        weeks[rs[0]["week"]]["sessions" if not side else "subagent_runs"] += 1

    main = [rs for (s, side), rs in sessions.items() if not side]
    start_ctx = [rs[0]["input"] + rs[0]["cache_write"] + rs[0]["cache_read"] for rs in main]
    turn_ctx = [r["input"] + r["cache_write"] + r["cache_read"] for rs in main for r in rs]
    per_session = [sum(weighted(r) for r in rs) for rs in main]
    models = defaultdict(float)
    for r in rows:
        models[r["model"]] += weighted(r)
    med = lambda xs: int(statistics.median(xs)) if xs else 0
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "range": [rows[0]["ts"].date().isoformat(), rows[-1]["ts"].date().isoformat()] if rows else None,
        "sessions": len(main),
        "subagent_runs": len(sessions) - len(main),
        "start_context_median": med(start_ctx),
        "turn_context_median": med(turn_ctx),
        "weighted_per_session_median": med(per_session),
        "subagent_share": round(sum(weighted(r) for r in rows if r["sidechain"]) / max(1, sum(map(weighted, rows))), 3),
        "by_model": {k: int(v) for k, v in sorted(models.items(), key=lambda kv: -kv[1])},
        "by_week": {k: {kk: int(vv) for kk, vv in v.items()} for k, v in sorted(weeks.items())},
    }


def markdown(rep, name):
    lines = [
        f"# Claude usage — {name}",
        "",
        f"Generated {rep['generated_at']} from the local session logs, {rep['range'][0]} to {rep['range'][1]}.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Main sessions | {rep['sessions']} |",
        f"| Subagent runs | {rep['subagent_runs']} |",
        f"| Context at session start (median tokens) | {rep['start_context_median']:,} |",
        f"| Context per turn (median tokens) | {rep['turn_context_median']:,} |",
        f"| Weighted tokens per session (median) | {rep['weighted_per_session_median']:,} |",
        f"| Subagent share of weighted tokens | {rep['subagent_share']:.0%} |",
        "",
        "## By week (weighted tokens)",
        "",
        "| Week | Sessions | Subagent runs | Turns | Weighted | Of which subagents | Output | Cache read |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for wk, v in rep["by_week"].items():
        lines.append(
            f"| {wk} | {v.get('sessions', 0)} | {v.get('subagent_runs', 0)} | {v['turns']} | {v['weighted']:,} "
            f"| {v['sub_weighted']:,} | {v['output']:,} | {v['cache_read']:,} |"
        )
    lines += ["", "## By model (weighted tokens)", "", "| Model | Weighted |", "|---|---|"]
    lines += [f"| {m} | {v:,} |" for m, v in rep["by_model"].items()]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=lambda s: datetime.fromisoformat(s).date())
    ap.add_argument("--write", metavar="NAME", help="save docs/claude-setup/measurements/NAME.{md,json}")
    a = ap.parse_args()
    rep = report(list(load(a.since)))
    md = markdown(rep, a.write or "now")
    print(md)
    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{a.write}.json").write_text(json.dumps(rep, indent=2) + "\n")
        (OUT / f"{a.write}.md").write_text(md)


if __name__ == "__main__":
    main()
