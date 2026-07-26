#!/usr/bin/env python3
"""Cashflow dashboard model — Phase 1 (today + breakdowns, no projection).

Reads the two digested outputs and emits ``data/digested/cashflow.json`` (+ a
human ``cashflow.md``), the model behind a Plangram-style "תזרים כספי" screen.
See ``docs/plangram-prd/01-cashflow.md`` for the full spec.

This file is self-contained and idempotent — safe to re-run after every digest.
It reads only ``transactions.json`` and ``snapshot.json``; it never scrapes or
mutates source data. Stdlib only.

Pipeline position::

    data/digested/{transactions,snapshot}.json  --(this)-->  data/digested/cashflow.json
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DIGESTED = os.path.join(HERE, "digested")
TRANSACTIONS = os.path.join(DIGESTED, "transactions.json")
SNAPSHOT = os.path.join(DIGESTED, "snapshot.json")
OUT_JSON = os.path.join(DIGESTED, "cashflow.json")
OUT_MD = os.path.join(DIGESTED, "cashflow.md")
OUT_HTML = os.path.join(DIGESTED, "cashflow.html")

CURRENCY = "₪"

# --- Category bucketing -----------------------------------------------------
# Raw Hebrew categories (from RiseUp / banks) folded into the canonical cashflow
# buckets the dashboard charts and KPIs agree on. Anything unmapped falls through
# to "other" (income) or "running" (expense) — the dominant 'uncategorized' bulk
# is everyday spend, so it reads as running expense.

INCOME_BUCKETS = {
    "work": "הכנסות מעבודה",
    "benefits": "הכנסה מקצבאות",
    "other": "הכנסה אחרת",
}
EXPENSE_BUCKETS = {
    "running": "הוצאה שוטפת",
    "goals": "יעדים",
    "loans": "הלוואות",
    "taxes": "מיסים",
    "investments": "השקעות",
    "other": "אחר",
}

# raw category -> expense bucket (only the non-"running" overrides need listing)
EXPENSE_CATEGORY_MAP = {
    "הלוואה": "loans",
    "משכנתא": "loans",
    "תשלומים": "loans",
    "השקעה וחיסכון": "investments",
    "ביטוח ופיננסים": "investments",
    "מוסדות": "taxes",
    "עמלות": "taxes",
    "דמי כרטיס": "taxes",
    "עמלת דמי כרטיס - בנקים": "taxes",
}
# raw category -> income bucket (default income -> "work" unless benefit-like)
INCOME_CATEGORY_MAP = {
    "קצבה": "benefits",
    "קצבאות": "benefits",
    "ביטוח לאומי": "benefits",
    "העברות": "other",
    "P2P BIT": "other",
}


def _expense_bucket(category):
    return EXPENSE_CATEGORY_MAP.get((category or "").strip(), "running")


def _income_bucket(category):
    return INCOME_CATEGORY_MAP.get((category or "").strip(), "work")


# --- Monthly aggregation ----------------------------------------------------

def aggregate_by_month(transactions):
    """Group transactions by ``YYYY-MM`` into income/expense/net + bucketed splits.

    Money-out is negative in the ledger; we report expense as a positive figure.
    Returns an ordered dict keyed by month.
    """
    months = defaultdict(lambda: {
        "income": 0.0,
        "expense": 0.0,
        "saved": 0.0,        # routed to own savings/investments — not spend
        "net": 0.0,
        "count": 0,
        "income_by_bucket": defaultdict(float),
        "expense_by_bucket": defaultdict(float),
    })
    for t in transactions:
        # Not cashflow: money moving between our own accounts, and card-bill
        # settlements (the underlying purchases are already in the ledger).
        if t.get("internal_transfer") or t.get("card_bill_payment"):
            continue
        date = t.get("date")
        if not date or len(date) < 7:
            continue
        ym = date[:7]
        amount = float(t.get("amount") or 0)
        cat = t.get("category")
        m = months[ym]
        m["count"] += 1
        if t.get("savings"):              # outflow, but saved not spent
            m["saved"] += -amount
        elif t.get("is_income") or amount > 0:
            m["income"] += amount
            m["income_by_bucket"][_income_bucket(cat)] += amount
        else:
            m["expense"] += -amount  # store as positive
            m["expense_by_bucket"][_expense_bucket(cat)] += -amount
    for m in months.values():
        # Net keeps savings on the books (it left the checking account), so the
        # cashflow line still reflects liquidity. 'saved' is surfaced separately.
        m["net"] = round(m["income"] - m["expense"] - m["saved"], 2)
        m["income"] = round(m["income"], 2)
        m["expense"] = round(m["expense"], 2)
        m["saved"] = round(m["saved"], 2)
        m["income_by_bucket"] = {k: round(v, 2) for k, v in m["income_by_bucket"].items()}
        m["expense_by_bucket"] = {k: round(v, 2) for k, v in m["expense_by_bucket"].items()}
    return dict(sorted(months.items()))


def pick_current_month(months):
    """The most relevant month to display: the current calendar month if it has
    data, otherwise the most recent month that does have data.

    The old design always excluded the current calendar month as "still accruing,"
    but that caused a systematic one-month lag (e.g. showing June on July 26 when
    July already had 157 transactions). We now show the current calendar month
    whenever the ledger contains any transactions for it, and fall back to the
    latest available month only when the current month is absent entirely (e.g.
    first hour of a new month before any transactions clear).
    """
    if not months:
        return None
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if this_month in months:
        return this_month
    # Current month not in ledger yet — return whatever is latest
    return list(months)[-1]


# --- Metrics ----------------------------------------------------------------

def _verdict(value, *, good_above=None, bad_below=None, bad_above=None, good_below=None):
    """Map a value to good/warning/bad given thresholds. None -> neutral."""
    if value is None:
        return None
    if good_above is not None and value >= good_above:
        return "good"
    if bad_below is not None and value < bad_below:
        return "bad"
    if bad_above is not None and value > bad_above:
        return "bad"
    if good_below is not None and value <= good_below:
        return "good"
    return "warning"


def build_metrics(month, snapshot):
    """The computable subset of Plangram's 28 metrics (PRD §4). Forward-looking
    metrics (Plangram score, growth, missing-piece) are deferred to phase 2."""
    income = month["income"]
    expense = month["expense"]
    net = month["net"]
    totals = snapshot.get("totals", {})
    net_worth = totals.get("tracked_net_position")
    loan_service = totals.get("monthly_loan_service") or 0.0
    overdraft = totals.get("bank_balances_sum")

    debt_repayment_pct = round(loan_service / expense * 100, 1) if expense else None
    # Savings% proxy: net cashflow as a share of income. True net-worth-delta
    # savings needs snapshot history (phase 2); flagged in `note`.
    savings_pct = round(max(net, 0) / income * 100, 1) if income else None

    metrics = [
        {
            "key": "net_cashflow", "name": "תזרים", "value": net, "units": CURRENCY,
            "rank": _verdict(net, good_above=0, bad_below=0), "higher_is_better": True,
            "description": "ההפרש בין ההכנסות להוצאות בחודש",
        },
        {
            "key": "income", "name": "הכנסות", "value": income, "units": CURRENCY,
            "rank": None, "higher_is_better": True,
            "description": "סך ההכנסות בחודש",
        },
        {
            "key": "expense", "name": "הוצאות", "value": expense, "units": CURRENCY,
            "rank": None, "higher_is_better": False,
            "description": "סך ההוצאות בחודש",
        },
        {
            "key": "net_worth", "name": "שווי נקי", "value": net_worth, "units": CURRENCY,
            "rank": _verdict(net_worth, good_above=0, bad_below=0), "higher_is_better": True,
            "description": "נכסים פחות התחייבויות (חשבונות במעקב בלבד)",
        },
        {
            "key": "debt_repayment_pct", "name": "אחוז החזר חוב", "value": debt_repayment_pct,
            "units": "%", "rank": _verdict(debt_repayment_pct, good_below=30, bad_above=50),
            "higher_is_better": False,
            "description": "שיעור החזר הלוואות מתוך סך ההוצאות החודשיות",
        },
        {
            "key": "savings_pct", "name": "אחוז חיסכון", "value": savings_pct, "units": "%",
            "rank": _verdict(savings_pct, good_above=15, bad_below=5), "higher_is_better": True,
            "description": "אומדן: התזרים החיובי כאחוז מההכנסה (אומדן — דורש היסטוריית שווי נקי לחישוב מדויק)",
            "estimated": True,
        },
        {
            "key": "overdraft", "name": "עודף בעובר ושב", "value": round(overdraft, 2) if overdraft is not None else None,
            "units": CURRENCY, "rank": _verdict(overdraft, good_above=0, bad_below=0),
            "higher_is_better": True,
            "description": "סך יתרות חשבונות העו""ש",
        },
    ]
    return metrics


# --- Charts -----------------------------------------------------------------

def _plot(graph_type, title, x_axis, datasets, ylabel=None, xlabel=None, name=None):
    return {
        "graph_type": graph_type, "graph_title": title,
        "xlabel": xlabel, "ylabel": ylabel,
        "x_axis": x_axis, "datasets": datasets, "unique_name": name,
    }


def build_charts(months, current_key):
    cur = months[current_key]

    today = {
        "income": cur["income"], "expense": cur["expense"],
        "saved": cur.get("saved", 0.0), "net": cur["net"],
    }

    income_ds = [
        {"name": INCOME_BUCKETS.get(b, b), "value": v}
        for b, v in sorted(cur["income_by_bucket"].items(), key=lambda kv: -kv[1])
    ]
    expense_ds = [
        {"name": EXPENSE_BUCKETS.get(b, b), "value": v}
        for b, v in sorted(cur["expense_by_bucket"].items(), key=lambda kv: -kv[1])
    ]

    # months trend (income / expense / net over available months)
    keys = list(months.keys())
    trend = _plot(
        "area", "תזרים לאורך זמן", keys,
        [
            {"name": "הכנסות", "ds": [months[k]["income"] for k in keys], "color": "#22c55e"},
            {"name": "הוצאות", "ds": [months[k]["expense"] for k in keys], "color": "#f97316"},
            {"name": "תזרים", "ds": [months[k]["net"] for k in keys], "color": "#6366f1"},
        ],
        ylabel=CURRENCY, name="cashflow_trend",
    )

    return {
        "today": today,
        "income_breakdown": _plot("pie", "הכנסות", [d["name"] for d in income_ds],
                                  income_ds, name="income_plot"),
        "expense_breakdown": _plot("pie", "הוצאות", [d["name"] for d in expense_ds],
                                   expense_ds, name="expense_plot"),
        "trend": trend,
    }


# --- Orchestration ----------------------------------------------------------

def build():
    with open(TRANSACTIONS, encoding="utf-8") as f:
        tx_doc = json.load(f)
    with open(SNAPSHOT, encoding="utf-8") as f:
        snapshot = json.load(f)

    transactions = tx_doc.get("transactions", [])
    months = aggregate_by_month(transactions)
    current = pick_current_month(months)
    if current is None:
        raise SystemExit("no transactions to build a cashflow from")

    metrics = build_metrics(months[current], snapshot)
    charts = build_charts(months, current)

    # Phase 2 — forward-looking net-worth projection
    import projection
    proj = projection.build(snapshot)
    metrics = metrics + proj["metrics"]

    model = {
        "generated_at": datetime.now(timezone.utc)
            .astimezone(timezone(timedelta(hours=3))).isoformat(timespec="seconds"),
        "currency": "ILS",
        "current_month": current,
        "note": (
            "Cashflow model (Phase 1: today + breakdowns). 'current_month' is the "
            "latest complete calendar month. Savings% is an estimate pending "
            "net-worth history. Forward projections not yet implemented."
        ),
        "metrics": metrics,
        "today": charts["today"],
        "charts": {
            **{k: v for k, v in charts.items() if k != "today"},
            "net_worth": proj["chart"],
        },
        "projection": {
            "config": proj["config"],
            "net_worth_today": proj["net_worth_today"],
            "net_worth_at_retirement": proj["net_worth_at_retirement"],
            "total_loan_balance_today": proj["total_loan_balance_today"],
            "loans_modeled": proj["loans_modeled"],
            "focal_points": proj["focal_points"],
        },
        "months": [
            {"month": k, "income": v["income"], "expense": v["expense"], "net": v["net"],
             "count": v["count"]}
            for k, v in months.items()
        ],
    }

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


if __name__ == "__main__":
    m = build()
    print(f"cashflow.json written — current month {m['current_month']}, "
          f"net {m['today']['net']:,.0f} ₪, {len(m['months'])} months")
