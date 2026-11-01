#!/usr/bin/env python3
"""Cashflow dashboard model: writes ``data/digested/cashflow.json`` (+ ``.md``, ``.html``).

The figures are computed by finance/views (household.py assembles them); this script loads
the inputs (data/inputs.py), writes the files and mirrors the actions into the inbox.
Idempotent — safe to re-run after every digest; it never scrapes or mutates source data.
See ``docs/plangram-prd/01-cashflow.md`` for the spec.

Pipeline position::

    data/digested/{transactions,snapshot}.json  --(this)-->  data/digested/cashflow.json
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

from finance.paths import data_root
from finance.views.cashflow import CURRENCY

HERE = os.path.dirname(os.path.abspath(__file__))
DIGESTED = os.path.join(str(data_root()), "digested")
OUT_JSON = os.path.join(DIGESTED, "cashflow.json")
OUT_MD = os.path.join(DIGESTED, "cashflow.md")
OUT_HTML = os.path.join(DIGESTED, "cashflow.html")


def _local_today():
    """Today in Israel (UTC+3, matching ``generated_at``) — the pace cut-off."""
    return datetime.now(timezone(timedelta(hours=3))).date()


def build():
    """cashflow.json (+ .md, .html) from the digested files, through finance/views/household.py."""
    import inputs
    from finance.views.household import Household
    today = _local_today()
    household = Household(inputs.load(today), today)
    model = household.cashflow_document(
        datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).isoformat(timespec="seconds"))

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)

    _write_md(model)
    _write_html(model)
    return model


def _write_md(model):
    cur = model["current_month"]
    t = model["today"]
    lines = [
        f"# Cashflow — {cur}", "",
        f"*Generated {model['generated_at']} · currency ILS*", "",
        "## This month", "",
        f"| | {CURRENCY} |", "|---|---:|",
        f"| הכנסות | {t['income']:,.0f} |",
        f"| הוצאות | {t['expense']:,.0f} |",
        *( [f"| חיסכון | {t['saved']:,.0f} |"] if t.get('saved') else [] ),
        f"| **תזרים** | **{t['net']:,.0f}** |",
        "", "## Metrics", "",
        "| מדד | ערך | דירוג |", "|---|---:|:---:|",
    ]
    pill = {"good": "🟢", "bad": "🔴", "warning": "🟡", None: "·"}
    for m in model["metrics"]:
        v = m["value"]
        vs = "—" if v is None else (f"{v:,.1f}%" if m["units"] == "%" else f"{v:,.0f} {m['units']}")
        lines.append(f"| {m['name']} | {vs} | {pill.get(m['rank'], '·')} |")
    lines += ["", "## Expense breakdown", ""]
    for d in model["charts"]["expense_breakdown"]["datasets"]:
        lines.append(f"- {d['name']}: {d['value']:,.0f} {CURRENCY}")
    lines += ["", "## Income breakdown", ""]
    for d in model["charts"]["income_breakdown"]["datasets"]:
        lines.append(f"- {d['name']}: {d['value']:,.0f} {CURRENCY}")
    rw = model.get("runway")
    if rw:
        lines += ["", "## Balance runway", "",
                  f"- Start balance: {rw['start_balance']:,.0f} {CURRENCY} (limit {rw['overdraft_limit']:,.0f})"]
        if rw["next_payday"]:
            lines.append(f"- Next payday: {rw['next_payday']['date']} (+{rw['next_payday']['amount']:,.0f})")
        if rw["safe_to_spend"] is not None:
            lines.append(f"- Safe to spend until payday: {rw['safe_to_spend']:,.0f} {CURRENCY}")
        lines.append(f"- Low point: {rw['low_point']['balance']:,.0f} on {rw['low_point']['date']}")
    lines.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_html(model):
    """Self-contained RTL dashboard with the model embedded inline (opens via
    file:// — no server, no CORS). Charts via Chart.js CDN; degrades to tables
    offline."""
    payload = json.dumps(model, ensure_ascii=False)
    html = _HTML_TEMPLATE.replace("/*__DATA__*/null", payload)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>תזרים כספי</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root{ --bg:#f1f0ee; --card:#fff; --ink:#1f2430; --muted:#6b7280;
         --good:#16a34a; --goodbg:#dcfce7; --bad:#dc2626; --badbg:#fee2e2;
         --warn:#b45309; --warnbg:#fef3c7; --accent:#6366f1; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:-apple-system,"Segoe UI",Rubik,Arial,sans-serif}
  .wrap{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
  header{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px}
  h1{font-size:26px;margin:0}
  .sub{color:var(--muted);font-size:13px;margin-bottom:22px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:22px}
  .kpi{background:var(--card);border-radius:16px;padding:18px;text-align:center;
       box-shadow:0 1px 3px rgba(0,0,0,.05)}
  .kpi .name{color:var(--muted);font-size:14px;margin-bottom:8px}
  .kpi .val{font-size:30px;font-weight:700;letter-spacing:-.5px}
  .kpi .pill{display:inline-block;margin-top:10px;font-size:12px;font-weight:600;
             padding:3px 12px;border-radius:999px}
  .good{color:var(--good);background:var(--goodbg)}
  .bad{color:var(--bad);background:var(--badbg)}
  .warn{color:var(--warn);background:var(--warnbg)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:760px){.grid{grid-template-columns:1fr}}
  .panel{background:var(--card);border-radius:16px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
  .panel h2{font-size:16px;margin:0 0 14px}
  .today{display:flex;justify-content:space-around;text-align:center;margin-bottom:6px}
  .today .t{font-size:13px;color:var(--muted)}
  .today .n{font-size:22px;font-weight:700}
  .pos{color:var(--good)} .neg{color:var(--bad)}
  .note{margin-top:26px;font-size:12px;color:var(--muted);line-height:1.6;
        background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:14px}
  canvas{max-height:260px}
  .brand{font-weight:700;color:var(--accent)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>תזרים כספי</h1>
    <span class="brand">Finance</span>
  </header>
  <div class="sub" id="sub"></div>

  <div class="kpis" id="kpis"></div>

  <div class="panel" style="margin-bottom:18px">
    <h2>עו"ש — שווי נקי לאורך זמן</h2>
    <canvas id="netWorthChart" style="max-height:300px"></canvas>
  </div>

  <div class="grid">
    <div class="panel">
      <h2>התזרים — נכון לחודש</h2>
      <div class="today" id="today"></div>
      <canvas id="todayChart"></canvas>
    </div>
    <div class="panel">
      <h2>תזרים לאורך זמן</h2>
      <canvas id="trendChart"></canvas>
    </div>
    <div class="panel">
      <h2>הכנסות</h2>
      <canvas id="incomeChart"></canvas>
    </div>
    <div class="panel">
      <h2>הוצאות</h2>
      <canvas id="expenseChart"></canvas>
    </div>
  </div>

  <div class="note" id="note"></div>
</div>

<script>
const MODEL = /*__DATA__*/null;
const ILS = new Intl.NumberFormat('he-IL',{maximumFractionDigits:0});
const fmt = (v,u)=> v==null ? '—' : (u==='%' ? ILS.format(v)+'%' : ILS.format(v)+' ₪');
const rankClass = r => r==='good'?'good':r==='bad'?'bad':r==='warning'?'warn':'';
const rankLabel = r => r==='good'?'מעולה':r==='bad'?'לא משהו':r==='warning'?'בינוני':'';

document.getElementById('sub').textContent =
  `החודש: ${MODEL.current_month} · נוצר ${MODEL.generated_at}`;

// KPI cards
const kpis = document.getElementById('kpis');
MODEL.metrics.forEach(m=>{
  const pill = m.rank ? `<div class="pill ${rankClass(m.rank)}">${rankLabel(m.rank)}</div>` : '';
  kpis.insertAdjacentHTML('beforeend',
    `<div class="kpi"><div class="name">${m.name}</div>
       <div class="val">${fmt(m.value,m.units)}</div>${pill}</div>`);
});

// Today tiles
const t = MODEL.today;
document.getElementById('today').innerHTML =
  `<div><div class="t">הכנסות</div><div class="n pos">${fmt(t.income,'₪')}</div></div>
   <div><div class="t">הוצאות</div><div class="n neg">${fmt(t.expense,'₪')}</div></div>
   ${t.saved ? `<div><div class="t">חיסכון</div><div class="n" style="color:var(--accent)">${fmt(t.saved,'₪')}</div></div>` : ''}
   <div><div class="t">תזרים</div><div class="n ${t.net>=0?'pos':'neg'}">${fmt(t.net,'₪')}</div></div>`;

if (typeof Chart === 'undefined') {
  document.getElementById('note').textContent =
    'אין חיבור לאינטרנט — הגרפים לא נטענו (Chart.js). הנתונים המספריים מוצגים מעלה.';
} else {
  const PIE = ['#6366f1','#22c55e','#f97316','#eab308','#06b6d4','#ec4899','#94a3b8'];
  new Chart(todayChart,{type:'bar',data:{labels:['הכנסות','הוצאות'],
    datasets:[{data:[t.income,t.expense],backgroundColor:['#22c55e','#f97316']}]},
    options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true}}}});

  const tr = MODEL.charts.trend;
  new Chart(trendChart,{type:'line',data:{labels:tr.x_axis,
    datasets:tr.datasets.map(d=>({label:d.name,data:d.ds,borderColor:d.color,
      backgroundColor:d.color+'33',fill:true,tension:.3}))},
    options:{plugins:{legend:{position:'bottom'}}}});

  const nw = MODEL.charts.net_worth;
  if (nw) new Chart(netWorthChart,{type:'line',data:{labels:nw.x_axis,
    datasets:nw.datasets.map(d=>({label:d.name,data:d.ds,borderColor:d.color,
      backgroundColor:d.color+'22',fill:d.name.includes('שווי'),tension:.25,
      pointRadius:0}))},
    options:{plugins:{legend:{position:'bottom'}},
      scales:{y:{ticks:{callback:v=>ILS.format(v)}}}}});

  const pie = (cv,plot)=> new Chart(cv,{type:'doughnut',
    data:{labels:plot.datasets.map(d=>d.name),
      datasets:[{data:plot.datasets.map(d=>d.value),backgroundColor:PIE}]},
    options:{plugins:{legend:{position:'bottom'}}}});
  pie(incomeChart, MODEL.charts.income_breakdown);
  pie(expenseChart, MODEL.charts.expense_breakdown);
}

document.getElementById('note').textContent = (document.getElementById('note').textContent||'')
  + ' ' + (MODEL.note||'');
</script>
</body>
</html>
"""


def sync_inbox(model):
    """Mirror `model["actions"]` into the notifications inbox (db/inbox.py).

    Best-effort: with no database configured, or an unreachable one, this prints to
    stderr and returns None so the digest carries on."""
    import goals
    url = goals.database_url()
    if not url:
        return None
    db = os.path.join(os.path.dirname(HERE), "db")
    sys.path.insert(0, db)
    try:
        import inbox
        from ledger import connect
        with connect(url) as conn:
            return inbox.sync(conn, model["actions"])
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"inbox: database unavailable ({e})", file=sys.stderr)
        return None
    finally:
        sys.path.remove(db)


if __name__ == "__main__":
    from finance.tenancy import use_cli_tenant
    use_cli_tenant()
    m = build()
    sync_inbox(m)
    print(f"cashflow.json written — current month {m['current_month']}, "
          f"net {m['today']['net']:,.0f} ₪, {len(m['months'])} months")
