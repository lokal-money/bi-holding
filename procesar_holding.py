"""
procesar_holding.py
─────────────────────────────────────────────────────────────────
Genera el dashboard consolidado Lokal Money Holding.
Incluye TODOS los comercios del archivo TXN_LM_CP.xlsx.

Uso:
    python procesar_holding.py TXN_LM_CP.xlsx "contraseña"
"""

import pandas as pd
import json
import re
import sys
import os

EXCEL_FILE   = "TXN_LM_CP.xlsx"
SHEET_NAME   = "TXN Lokal Money Compago"
OUTPUT_FILE  = "index.html"
TEMPLATE_FILE = "index.template.html"
TZ_COL       = "UTC-6"   # UTC-6 para consolidado

def classify_fee(fee):
    if fee <= 2.45: return "Débito"
    if fee <= 2.84: return "Crédito"
    if fee <= 2.99: return "Crédito Plus"
    return "Crédito Internacional"

def procesar():
    excel_path = sys.argv[1] if len(sys.argv) > 1 else EXCEL_FILE
    password   = sys.argv[2] if len(sys.argv) > 2 else "Lokal#2026"

    print(f"Leyendo {excel_path}...")
    df = pd.read_excel(excel_path, sheet_name=SHEET_NAME)

    col_name = f"transaction_time ({TZ_COL})"
    df[col_name] = df[col_name].astype(str).str.replace(r"Z+$", "Z", regex=True)
    df["pt_dt"]  = pd.to_datetime(df[col_name], utc=True, errors="coerce")
    df = df.dropna(subset=["pt_dt"])

    df["date"]       = df["pt_dt"].dt.strftime("%Y-%m-%d")
    df["hour"]       = df["pt_dt"].dt.hour
    df["dow"]        = df["pt_dt"].dt.day_name()
    df["merchant"]   = df["merchant_name"].str.strip()
    df["card_class"] = df["merchant_fee_percentage"].apply(classify_fee)

    cols = ["date","hour","dow","transaction_status","transaction_amount",
            "total_fee_amount","net_amount_to_merchant","card_type",
            "issuing_bank","merchant_fee_percentage","card_class","merchant"]

    records   = df[cols].to_dict(orient="records")
    confirmed = [r for r in records if r["transaction_status"] == "CONFIRMED"]
    date_from = min(r["date"] for r in records)
    date_to   = max(r["date"] for r in records)

    print(f"OK: {len(records)} registros | {len(confirmed)} confirmados")
    print(f"OK: {df['merchant'].nunique()} comercios")
    print(f"OK: Periodo {date_from} a {date_to}")
    print(f"OK: Bruto total ${sum(r['transaction_amount'] for r in confirmed):,.2f}")

    json_data = json.dumps(records, separators=(",", ":"))

    template_path = TEMPLATE_FILE if os.path.exists(TEMPLATE_FILE) else OUTPUT_FILE
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Replace placeholders
    html = html.replace("{{MERCHANT_NAME}}", "LOKAL MONEY HOLDING")
    html = html.replace("{{ACCESS_PASSWORD}}", password)

    # Replace RAW block
    start  = html.find("let RAW = ")
    bracket = html.index("[", start)
    depth, pos = 0, bracket
    while pos < len(html):
        if   html[pos] == "[": depth += 1
        elif html[pos] == "]":
            depth -= 1
            if depth == 0:
                end = pos + 1
                break
        pos += 1
    if html[end] == ";": end += 1
    html = html[:start] + "let RAW = " + json_data + html[end:]

    # Update date inputs
    html = re.sub(r'<input[^>]*id="dateFrom"[^>]*/>', f'<input type="date" id="dateFrom" value="{date_from}"/>', html)
    html = re.sub(r'<input[^>]*id="dateTo"[^>]*/>', f'<input type="date" id="dateTo" value="{date_to}"/>', html)

    # Remove loadData from init
    init_pattern = re.compile(r'(scheduleRefresh\(\);)\s*(?://[^\n]*)?\s*loadData\(\);', re.MULTILINE)
    html, _ = init_pattern.subn(r'\1', html)

    # Add merchant breakdown section before events section
    MERCHANT_SECTION = '''
  <!-- POR COMERCIO -->
  <section class="section">
    <div class="section-header">
      <div class="section-icon">🏪</div>
      <div class="section-title">Desglose por Comercio</div>
      <div class="section-sub">Participación de cada sucursal</div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Ventas por comercio (MXN)</div>
        <div id="merchantBars"></div>
      </div>
      <div class="card">
        <div class="card-title">Distribución por comercio</div>
        <div class="chart-wrap" style="height:240px;"><canvas id="merchantChart"></canvas></div>
      </div>
    </div>
  </section>

'''
    if '<!-- ── EVENTOS' in html:
        html = html.replace('  <!-- ── EVENTOS', MERCHANT_SECTION + '  <!-- ── EVENTOS')
    elif 'id="evCancelled"' in html:
        html = html.replace('<section class="section">\n    <div class="section-header">\n      <div class="section-icon">⚡</div>',
                           MERCHANT_SECTION + '<section class="section">\n    <div class="section-header">\n      <div class="section-icon">⚡</div>')

    # Add merchant chart JS
    MERCHANT_JS = '''
  // ── MERCHANT BREAKDOWN ───────────────────────────────────────
  const merchantMap = {};
  confirmed.forEach(r => {
    const m = (r.merchant || 'OTROS').trim();
    if (!merchantMap[m]) merchantMap[m] = {count:0, gross:0};
    merchantMap[m].count++;
    merchantMap[m].gross += r.transaction_amount;
  });
  const merchants = Object.entries(merchantMap).sort((a,b) => b[1].gross - a[1].gross);
  const maxMerchant = merchants[0]?.[1].gross || 1;
  const mColors = ['#00c2a8','#3b82f6','#f5a623','#a78bfa','#e85d5d',
    '#06b6d4','#84cc16','#f97316','#ec4899','#8b5cf6',
    '#14b8a6','#eab308','#ef4444','#6366f1','#10b981'];

  const merchantBarsEl = document.getElementById('merchantBars');
  if (merchantBarsEl) {
    const totalMerchantGross = merchants.reduce((s,[,v]) => s + v.gross, 0);

    // Pareto: include merchants until cumulative = 80% of total
    let cumulative = 0;
    const paretoMerchants = [];
    for (const [name, v] of merchants) {
      paretoMerchants.push([name, v]);
      cumulative += v.gross;
      if (cumulative / totalMerchantGross >= 0.80) break;
    }
    const paretoGross = paretoMerchants.reduce((s,[,v]) => s + v.gross, 0);
    const paretoCount = paretoMerchants.length;

    const header = `
      <div style="display:flex;justify-content:space-between;align-items:center;
                  margin-bottom:4px;padding-bottom:10px;border-bottom:1px solid var(--border);">
        <span style="font-size:10px;font-weight:600;text-transform:uppercase;
                     letter-spacing:0.7px;color:var(--muted);">Total consolidado</span>
        <span style="font-family:'Barlow',sans-serif;font-size:20px;font-weight:800;
                     color:var(--teal);">${fmt(totalMerchantGross)}</span>
      </div>
      <div style="font-size:10.5px;color:var(--muted);margin-bottom:10px;">
        Top ${paretoCount} comercio${paretoCount>1?'s':''} representan el 80% del volumen total
      </div>`;

    const rows = paretoMerchants.map(([name,v], i) => `
      <div class="bank-row">
        <div class="bank-name" style="width:140px;font-size:11px;">${name}</div>
        <div class="bank-bar-wrap"><div class="bank-bar-fill" style="width:${(v.gross/maxMerchant*100).toFixed(1)}%;background:${mColors[i % mColors.length]};"></div></div>
        <div class="bank-amount">${fmt(v.gross)}</div>
      </div>`).join('');

    merchantBarsEl.innerHTML = header + rows;
  }

  destroyChart('merchantChart');
  if (document.getElementById('merchantChart')) {
    charts.merchantChart = new Chart(document.getElementById('merchantChart'), {
      type: 'doughnut',
      data: {
        labels: (() => {
          const total = merchants.reduce((s,[,v]) => s+v.gross, 0);
          let cum = 0;
          const labels = [];
          for (const [name,v] of merchants) {
            labels.push(name);
            cum += v.gross;
            if (cum/total >= 0.80) break;
          }
          if (cum < total) labels.push('Otros');
          return labels;
        })(),
        datasets: [{ data: (() => {
          const total = merchants.reduce((s,[,v]) => s+v.gross, 0);
          let cum = 0;
          const vals = [];
          for (const [,v] of merchants) {
            vals.push(v.gross);
            cum += v.gross;
            if (cum/total >= 0.80) break;
          }
          if (cum < total) vals.push(total - cum);
          return vals;
        })(),
          backgroundColor: (() => {
            const total = merchants.reduce((s,[,v]) => s+v.gross, 0);
            let cum = 0;
            const colors = [];
            for (let i=0; i<merchants.length; i++) {
              colors.push(mColors[i % mColors.length]);
              cum += merchants[i][1].gross;
              if (cum/total >= 0.80) break;
            }
            if (cum < total) colors.push('rgba(120,130,150,0.4)');
            return colors;
          })(),
          borderWidth: 0, hoverOffset: 6 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '55%',
        plugins: {
          legend: { display: true, position: 'right',
            labels: { boxWidth: 10, font: { size: 10 }, padding: 8 }
          },
          tooltip: {
            callbacks: {
              label: ctx => {
                const total = ctx.dataset.data.reduce((a,b) => a+b, 0);
                const pct = (ctx.raw/total*100).toFixed(1);
                return ' ' + ctx.label + ': ' + fmt(ctx.raw) + ' (' + pct + '%)';
              }
            }
          },
          datalabels: false
        },
        animation: { onComplete: function() {
          const chart = this;
          const ctx2 = chart.ctx;
          const total = chart.data.datasets[0].data.reduce((a,b) => a+b, 0);
          chart.data.datasets[0].data.forEach((val, i) => {
            const pct = (val/total*100);
            if (pct < 3) return;
            const meta = chart.getDatasetMeta(0);
            const arc  = meta.data[i];
            const mid  = arc.startAngle + (arc.endAngle - arc.startAngle) / 2;
            const r    = (arc.outerRadius + arc.innerRadius) / 2;
            const x    = arc.x + Math.cos(mid) * r;
            const y    = arc.y + Math.sin(mid) * r;
            ctx2.save();
            ctx2.fillStyle = '#fff';
            ctx2.font = 'bold 11px Barlow, sans-serif';
            ctx2.textAlign = 'center';
            ctx2.textBaseline = 'middle';
            ctx2.fillText(pct.toFixed(1) + '%', x, y);
            ctx2.restore();
          });
        }}
      }
    });
  }

'''
    if '// ── FEE TABLE' in html:
        html = html.replace('  // ── FEE TABLE', MERCHANT_JS + '  // ── FEE TABLE')
    else:
        last_script = html.rfind('render();')
        html = html[:last_script] + MERCHANT_JS + html[last_script:]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"LISTO: {OUTPUT_FILE} generado ({size_kb:.1f} KB)")

if __name__ == "__main__":
    procesar()
