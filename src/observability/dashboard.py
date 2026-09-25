from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import now_utc, read_json, write_text

STATES = ("baseline", "corrupted", "repaired")
STATE_COLORS = {"baseline": "#2563eb", "corrupted": "#dc2626", "repaired": "#16a34a"}
METRICS = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy")


def _load(path: Path) -> Any:
    return read_json(path) if path.exists() else None


def _metric_bars(metrics: dict[str, dict[str, Any]]) -> str:
    width, height, pad, group_w = 560, 220, 30, 170
    bar_w = 44
    parts = [f'<svg viewBox="0 0 {width} {height + 40}" role="img" aria-label="Metrics by state">']
    parts.append(f'<line x1="{pad}" y1="{height}" x2="{width}" y2="{height}" class="axis"/>')
    for g, metric in enumerate(METRICS):
        x0 = pad + 10 + g * group_w
        for s, state in enumerate(STATES):
            value = float((metrics.get(state) or {}).get(metric) or 0.0)
            h = value * (height - 20)
            x = x0 + s * (bar_w + 4)
            parts.append(
                f'<rect x="{x}" y="{height - h:.1f}" width="{bar_w}" height="{h:.1f}" fill="{STATE_COLORS[state]}">'
                f"<title>{state} {metric}: {value:.3f}</title></rect>"
            )
            parts.append(f'<text x="{x + bar_w / 2}" y="{height - h - 4:.1f}" class="val">{value:.2f}</text>')
        parts.append(f'<text x="{x0 + 70}" y="{height + 18}" class="lbl">{metric}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _age_histogram(frames: dict[str, pd.DataFrame], threshold: int) -> str:
    bins = list(range(0, 721, 60))
    width, height, pad = 560, 200, 30
    bin_w = (width - pad) / (len(bins) - 1)
    counts = {
        state: pd.cut(pd.to_numeric(df["age_days"], errors="coerce"), bins=bins, right=False).value_counts(sort=False).tolist()
        for state, df in frames.items()
    }
    peak = max([max(c) for c in counts.values()] + [1])
    parts = [f'<svg viewBox="0 0 {width} {height + 40}" role="img" aria-label="age_days distribution">']
    parts.append(f'<line x1="{pad}" y1="{height}" x2="{width}" y2="{height}" class="axis"/>')
    sub_w = bin_w / max(len(counts), 1) - 1
    for s, (state, values) in enumerate(counts.items()):
        for i, value in enumerate(values):
            h = value / peak * (height - 20)
            x = pad + i * bin_w + s * (sub_w + 1)
            parts.append(
                f'<rect x="{x:.1f}" y="{height - h:.1f}" width="{sub_w:.1f}" height="{h:.1f}" fill="{STATE_COLORS[state]}">'
                f"<title>{state} {bins[i]}-{bins[i + 1]}d: {value}</title></rect>"
            )
    tx = pad + threshold / bins[-1] * (width - pad)
    parts.append(f'<line x1="{tx:.1f}" y1="0" x2="{tx:.1f}" y2="{height}" class="sla"/>')
    parts.append(f'<text x="{tx + 4:.1f}" y="12" class="lbl">SLA {threshold}d</text>')
    for i in range(0, len(bins), 2):
        parts.append(f'<text x="{pad + i * bin_w:.1f}" y="{height + 18}" class="lbl">{bins[i]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _badge(ok: Any) -> str:
    if ok is None:
        return '<span class="badge na">n/a</span>'
    return f'<span class="badge {"ok" if ok else "bad"}">{"PASS" if ok else "FAIL"}</span>'


def build_dashboard(settings: Settings, output_path: Path | None = None) -> Path:
    """Render a static observability dashboard (bonus B1) from pipeline artifacts."""
    paths = settings.paths
    output_path = output_path or paths.project_dir / "data" / "reports" / "dashboard.html"
    metrics = {
        "baseline": _load(paths.baseline_metrics),
        "corrupted": _load(paths.corrupted_metrics),
        "repaired": _load(paths.repaired_metrics),
    }
    quality = {
        "baseline": _load(paths.baseline_quality_report),
        "corrupted": _load(paths.corrupted_quality_report),
        "repaired": _load(paths.quality_dir / "repaired_quality_report.json"),
    }
    frames = {}
    for state, path in (("baseline", paths.clean_json), ("corrupted", paths.corrupted_clean_json), ("repaired", paths.repaired_clean_json)):
        if path.exists():
            frames[state] = pd.DataFrame(read_json(path))
    repair = _load(paths.project_dir / "data" / "results" / "repair_summary.json") or {}

    cards = []
    for state in STATES:
        q = quality.get(state) or {}
        f = q.get("freshness") or {}
        m = metrics.get(state) or {}
        cards.append(
            f'<div class="card" style="border-top:4px solid {STATE_COLORS[state]}"><h3>{state.title()}</h3>'
            f"<p>Rows: <b>{q.get('row_count', '-')}</b></p>"
            f"<p>GX gate: {_badge(q.get('success'))}</p>"
            f"<p>Freshness: {_badge(f.get('is_fresh'))} stale {f.get('stale_rows', '-')}/{f.get('total_rows', '-')}</p>"
            f"<p>Hit rate: <b>{m.get('retrieval_hit_rate', '-')}</b> · F1: <b>{round(m.get('mean_token_f1', 0) or 0, 3)}</b></p></div>"
        )

    checks = [e["check"] for e in (quality.get("baseline") or quality.get("corrupted") or {}).get("expectations", [])]
    rows = []
    for check in checks:
        cells = []
        for state in STATES:
            match = next((e for e in (quality.get(state) or {}).get("expectations", []) if e["check"] == check), None)
            cells.append(f"<td>{_badge(match['success'] if match else None)}</td>")
        rows.append(f"<tr><td><code>{escape(check)}</code></td>{''.join(cells)}</tr>")

    legend = "".join(f'<span class="key" style="background:{c}"></span>{s} ' for s, c in STATE_COLORS.items())
    repair_rows = "".join(f"<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>" for k, v in repair.items())
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data Observability Dashboard</title>
<style>
:root {{ --bg:#f8fafc; --fg:#0f172a; --muted:#64748b; --card:#ffffff; --line:#cbd5e1; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0f172a; --fg:#e2e8f0; --muted:#94a3b8; --card:#1e293b; --line:#334155; }} }}
body {{ margin:0; padding:16px; font-family:system-ui,sans-serif; background:var(--bg); color:var(--fg); }}
main {{ max-width:1100px; margin:0 auto; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }}
.card {{ background:var(--card); border-radius:8px; padding:12px 16px; box-shadow:0 1px 2px #0002; }}
.card p {{ margin:6px 0; }} h1 {{ font-size:1.5rem; }} h2 {{ font-size:1.15rem; margin-top:28px; }}
.badge {{ padding:1px 8px; border-radius:10px; font-size:.8rem; font-weight:600; color:#fff; }}
.ok {{ background:#16a34a; }} .bad {{ background:#dc2626; }} .na {{ background:#64748b; }}
table {{ border-collapse:collapse; width:100%; background:var(--card); }} td,th {{ border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; }}
svg {{ width:100%; height:auto; background:var(--card); border-radius:8px; }}
svg .axis {{ stroke:var(--muted); }} svg .sla {{ stroke:#f59e0b; stroke-dasharray:4 3; }}
svg text {{ fill:var(--fg); font-size:11px; text-anchor:middle; }} svg .lbl {{ fill:var(--muted); }}
.key {{ display:inline-block; width:10px; height:10px; margin:0 4px 0 10px; border-radius:2px; }}
.muted {{ color:var(--muted); font-size:.85rem; }} .scroll {{ overflow-x:auto; }}
</style></head><body><main>
<h1>Data Observability Dashboard — Crossref RAG pipeline</h1>
<p class="muted">Generated {now_utc().isoformat()} from artifacts in <code>data/</code>. {legend}</p>
<div class="grid">{''.join(cards)}</div>
<h2>RAG metrics by state</h2>{_metric_bars(metrics)}
<h2>Paper age distribution (age_days, 60-day bins)</h2>{_age_histogram(frames, settings.freshness_threshold_days) if frames else '<p>No data</p>'}
<h2>Great Expectations checks</h2><div class="scroll"><table><tr><th>Check</th><th>Baseline</th><th>Corrupted</th><th>Repaired</th></tr>{''.join(rows)}</table></div>
<h2>Self-healing / idempotent repair</h2><div class="scroll"><table>{repair_rows or '<tr><td>Run the corruption flow first.</td></tr>'}</table></div>
</main></body></html>
"""
    write_text(output_path, html)
    return output_path
