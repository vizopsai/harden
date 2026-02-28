"""
Flask dashboard with BigQuery analytics
Uses Google Cloud BigQuery and external exchange rate API
"""

from flask import Flask, render_template_string, jsonify
from google.cloud import bigquery
import requests
import os
from datetime import datetime

app = Flask(__name__)

# BigQuery setup - this works for now but should use service account properly
GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "/path/to/service-account-key.json"
)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "my-project-123")
DATASET_ID = os.getenv("DATASET_ID", "analytics")

# Initialize BigQuery client
try:
    bq_client = bigquery.Client(project=PROJECT_ID)
except Exception as e:
    print(f"Failed to initialize BigQuery client: {e}")
    bq_client = None

# Simple HTML template - this works for now
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BigQuery Analytics Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }
        h1 { color: #333; }
        .metric { display: inline-block; margin: 10px; padding: 20px; background: #4285f4; color: white; border-radius: 8px; }
        .metric-value { font-size: 32px; font-weight: bold; }
        .metric-label { font-size: 14px; opacity: 0.9; }
        .exchange-rate { background: #34a853; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f0f0f0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Analytics Dashboard</h1>
        <div id="metrics"></div>
        <h2>Recent Data</h2>
        <div id="data"></div>
    </div>
    <script>
        fetch('/api/metrics').then(r => r.json()).then(data => {
            document.getElementById('metrics').innerHTML = `
                <div class="metric">
                    <div class="metric-label">Total Records</div>
                    <div class="metric-value">${data.total_records}</div>
                </div>
                <div class="metric exchange-rate">
                    <div class="metric-label">USD to EUR</div>
                    <div class="metric-value">${data.exchange_rate}</div>
                </div>
            `;
        });

        fetch('/api/data').then(r => r.json()).then(data => {
            let html = '<table><tr><th>ID</th><th>Value</th><th>Timestamp</th></tr>';
            data.rows.forEach(row => {
                html += `<tr><td>${row.id}</td><td>${row.value}</td><td>${row.timestamp}</td></tr>`;
            });
            html += '</table>';
            document.getElementById('data').innerHTML = html;
        });
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    """Dashboard homepage"""
    return render_template_string(TEMPLATE)

@app.route('/api/metrics')
def get_metrics():
    """Get analytics metrics from BigQuery and exchange rates"""
    metrics = {
        "total_records": 0,
        "exchange_rate": "N/A"
    }

    # Query BigQuery - this works for now but could be optimized
    if bq_client:
        try:
            query = f"""
                SELECT COUNT(*) as total
                FROM `{PROJECT_ID}.{DATASET_ID}.events`
                WHERE DATE(timestamp) = CURRENT_DATE()
            """
            query_job = bq_client.query(query)
            results = query_job.result()

            for row in results:
                metrics["total_records"] = row.total

        except Exception as e:
            print(f"BigQuery query failed: {e}")
            metrics["total_records"] = "Error"

    # Get exchange rate from external API
    try:
        response = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            metrics["exchange_rate"] = data["rates"].get("EUR", "N/A")
    except Exception as e:
        print(f"Exchange rate API failed: {e}")

    return jsonify(metrics)

@app.route('/api/data')
def get_data():
    """Get recent data from BigQuery"""
    rows = []

    if bq_client:
        try:
            # Query for recent events - this works for now
            query = f"""
                SELECT id, value, timestamp
                FROM `{PROJECT_ID}.{DATASET_ID}.events`
                ORDER BY timestamp DESC
                LIMIT 10
            """
            query_job = bq_client.query(query)
            results = query_job.result()

            for row in results:
                rows.append({
                    "id": row.id,
                    "value": row.value,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None
                })

        except Exception as e:
            print(f"BigQuery query failed: {e}")
            # Return mock data if query fails
            rows = [
                {"id": i, "value": f"Value {i}", "timestamp": datetime.now().isoformat()}
                for i in range(5)
            ]
    else:
        # Mock data when BigQuery is unavailable
        rows = [
            {"id": i, "value": f"Mock Value {i}", "timestamp": datetime.now().isoformat()}
            for i in range(5)
        ]

    return jsonify({"rows": rows})

@app.route('/analytics')
def analytics():
    """Custom analytics endpoint"""
    if not bq_client:
        return jsonify({"error": "BigQuery not configured"}), 503

    try:
        # Complex query - this works for now but needs optimization
        query = f"""
            SELECT
                DATE(timestamp) as date,
                COUNT(*) as count,
                AVG(value) as avg_value
            FROM `{PROJECT_ID}.{DATASET_ID}.events`
            WHERE DATE(timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            GROUP BY date
            ORDER BY date DESC
        """
        query_job = bq_client.query(query)
        results = query_job.result()

        data = []
        for row in results:
            data.append({
                "date": row.date.isoformat() if row.date else None,
                "count": row.count,
                "avg_value": float(row.avg_value) if row.avg_value else 0
            })

        return jsonify({"analytics": data})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    bq_ok = bq_client is not None

    # Check exchange rate API
    exchange_ok = False
    try:
        response = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=3
        )
        exchange_ok = response.status_code == 200
    except:
        pass

    return jsonify({
        "status": "healthy" if bq_ok else "degraded",
        "bigquery": bq_ok,
        "exchange_api": exchange_ok
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
