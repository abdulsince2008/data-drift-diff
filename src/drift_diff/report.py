"""HTML report generation for drift detection results."""
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Data Drift Report - {{ dataset_name }}</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden; }
        header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; }
        h1 { margin: 0; font-size: 1.8rem; font-weight: 600; }
        .meta { margin-top: 10px; opacity: 0.9; font-size: 0.9rem; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; padding: 25px; background: #fafafa; border-bottom: 1px solid #eee; }
        .stat-card { background: white; padding: 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .stat-value { font-size: 2rem; font-weight: 700; color: #333; }
        .stat-label { font-size: 0.85rem; color: #666; margin-top: 4px; }
        .stat-card.drifted .stat-value { color: #e74c3c; }
        .stat-card.stable .stat-value { color: #27ae60; }
        .section { padding: 25px; border-bottom: 1px solid #eee; }
        .section:last-child { border-bottom: none; }
        h2 { font-size: 1.2rem; margin: 0 0 20px; color: #333; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #fafafa; font-weight: 600; color: #555; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; }
        tr:hover td { background: #fafafa; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
        .badge-drifted { background: #fdeaea; color: #c0392b; }
        .badge-stable { background: #eafaf1; color: #27ae60; }
        .badge-added { background: #fff3e0; color: #e67e22; }
        .badge-removed { background: #fdeaea; color: #c0392b; }
        .badge-type_changed { background: #e8eaf6; color: #3f51b5; }
        .drift-bar { height: 6px; background: #eee; border-radius: 3px; overflow: hidden; margin-top: 4px; }
        .drift-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
        .drift-fill.low { background: #27ae60; }
        .drift-fill.medium { background: #f39c12; }
        .drift-fill.high { background: #e74c3c; }
        .details { font-size: 0.85rem; color: #666; margin-top: 4px; }
        .no-drift { text-align: center; padding: 40px; color: #999; }
        .schema-change { background: #fff8e1; border-left: 4px solid #ffc107; padding: 15px; margin: 10px 0; border-radius: 4px; }
        .schema-change.removed { border-color: #e74c3c; background: #fdeaea; }
        .schema-change.added { border-color: #27ae60; background: #eafaf1; }
        footer { padding: 20px; text-align: center; color: #999; font-size: 0.8rem; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Data Drift Report</h1>
            <div class="meta">
                Dataset: <strong>{{ dataset_name }}</strong> |
                Run: <code>{{ run_id }}</strong> |
                Previous: <code>{{ previous_run_id or 'None (baseline)' }}</code> |
                Generated: {{ generated_at }}
            </div>
        </header>

        <div class="summary">
            <div class="stat-card {{ 'drifted' if summary.drifted_columns > 0 else 'stable' }}">
                <div class="stat-value">{{ summary.total_columns }}</div>
                <div class="stat-label">Total Columns</div>
            </div>
            <div class="stat-card {{ 'drifted' if summary.drifted_columns > 0 else 'stable' }}">
                <div class="stat-value">{{ summary.drifted_columns }}</div>
                <div class="stat-label">Drifted Columns</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.added_columns }}</div>
                <div class="stat-label">Added Columns</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.removed_columns }}</div>
                <div class="stat-label">Removed Columns</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ summary.type_changed }}</div>
                <div class="stat-label">Type Changes</div>
            </div>
        </div>

        <div class="section">
            <h2>📋 Column Drift Details</h2>
            {% if column_drifts %}
            <table>
                <thead>
                    <tr>
                        <th>Column</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Drift Score</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody>
                    {% for col_name, drift in column_drifts.items() %}
                    <tr>
                        <td><strong>{{ col_name }}</strong></td>
                        <td>{{ drift.type or 'Unknown' }}</td>
                        <td>
                            <span class="badge badge-{{ drift.status }}">
                                {{ drift.status }}
                            </span>
                        </td>
                        <td>
                            <div class="drift-bar">
                                <div class="drift-fill {{ 'low' if drift.drift_score < 0.05 else 'medium' if drift.drift_score < 0.2 else 'high' }}"
                                     style="width: {{ (drift.drift_score * 100) }}%"></div>
                            </div>
                            <small>{{ "%.2f"|format(drift.drift_score * 100) }}%</small>
                        </td>
                        <td><span class="details">{{ drift.details }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="no-drift">No column drift data available</div>
            {% endif %}
        </div>

        <div class="section">
            <h2>🔄 Schema Changes</h2>
            {% if schema_changes.added or schema_changes.removed or schema_changes.type_changed %}
                {% for col in schema_changes.added %}
                <div class="schema-change added">
                    <strong>➕ Added:</strong> {{ col }}
                </div>
                {% endfor %}
                {% for col in schema_changes.removed %}
                <div class="schema-change removed">
                    <strong>➖ Removed:</strong> {{ col }}
                </div>
                {% endfor %}
                {% for change in schema_changes.type_changed %}
                <div class="schema-change">
                    <strong>🔄 Type Changed:</strong> {{ change.column }} — <code>{{ change.from }}</code> → <code>{{ change.to }}</code>
                </div>
                {% endfor %}
            {% else %}
            <div class="no-drift">No schema changes detected</div>
            {% endif %}
        </div>

        <footer>
            Generated by <a href="https://github.com/yourusername/data-drift-diff" target="_blank">data-drift-diff</a> v0.1.0
        </footer>
    </div>
</body>
</html>
"""


def generate_report(
    drift_result: dict[str, Any],
    current_profile: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Generate HTML drift report."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prepare column drift data with types
    column_drifts = {}
    for col_name, drift in drift_result.get("column_drifts", {}).items():
        col_type = current_profile.get("columns", {}).get(col_name, {}).get("type", "Unknown")
        column_drifts[col_name] = {**drift, "type": col_type}

    template = Environment(
        loader=FileSystemLoader("."),
        autoescape=select_autoescape(),
    ).from_string(REPORT_TEMPLATE)

    html = template.render(
        dataset_name=drift_result.get("dataset_name", "Unknown"),
        run_id=drift_result.get("run_id", "Unknown"),
        previous_run_id=drift_result.get("previous_run_id"),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=drift_result.get("summary", {}),
        column_drifts=column_drifts,
        schema_changes=drift_result.get("schema_changes", {}),
    )

    output_path.write_text(html)
    return output_path