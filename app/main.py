import asyncio
import os
import time
import httpx
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# --- Configuration ---
REGION = os.getenv("REGION", "local-dev")
PROJECT_ID = os.getenv("PROJECT_ID", "unknown")

# Initialize Firebase
if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client(database_id="latencys")
app = FastAPI()

# --- Background Worker Logic ---

async def latency_worker():
    """Background loop to measure latency to other registered regions."""
    client = httpx.AsyncClient(timeout=10.0)
    print(f"Starting latency worker in region: {REGION}")
    
    while True:
        try:
            # Fetch target URLs and interval from Firestore
            targets_doc = db.collection("index").document("targets").get()
            if not targets_doc.exists:
                await asyncio.sleep(10)
                continue
            
            data = targets_doc.to_dict()
            urls = data.get("urls", [])
            interval = data.get("test_interval_seconds", 30)

            for url in urls:
                # Skip self-pinging to keep data clean
                if f"/{REGION}" in url or REGION in url:
                    continue
                
                start_time = time.perf_counter()
                try:
                    # Ping the remote /ping endpoint
                    response = await client.get(f"{url}/ping")
                    latency = (time.perf_counter() - start_time) * 1000 # Convert to ms
                    
                    if response.status_code == 200:
                        # Log success to Firestore
                        db.collection("latency_logs").add({
                            "from_region": REGION,
                            "to_url": url,
                            "latency_ms": latency,
                            "timestamp": firestore.SERVER_TIMESTAMP,
                            "status": "success"
                        })
                except Exception as e:
                    print(f"Error pinging {url}: {e}")

            await asyncio.sleep(interval)
        except Exception as e:
            print(f"Worker Error: {e}")
            await asyncio.sleep(10)

@app.on_event("startup")
async def startup_event():
    """Start the background worker when the FastAPI app launches."""
    asyncio.create_task(latency_worker())

# --- Routes ---

@app.get("/ping")
async def ping():
    return {"status": "ok", "region": REGION, "timestamp": time.time()}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # 1. Registration Logic
    raw_url = str(request.base_url).rstrip("/")
    current_call_url = raw_url.replace("http://", "https://")
    targets_ref = db.collection("index").document("targets")
    
    try:
        targets_ref.update({
            "urls": firestore.ArrayUnion([current_call_url]),
            f"region_map.{REGION}": current_call_url
        })
    except Exception:
        targets_ref.set({
            "urls": [current_call_url],
            "region_map": {REGION: current_call_url},
            "test_interval_seconds": 30
        }, merge=True)

    # 2. Fetch Latency Data for Dashboard
    logs_ref = db.collection("latency_logs")
    query = logs_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(100)
    docs = query.stream()

    # Organize data: { "Source → Dest": [list of latencies] }
    stats = {}
    for doc in docs:
        d = doc.to_dict()
        # Clean up URL for display
        dest_display = d.get('to_url').split('//')[-1].split('.')[0]
        key = f"{d.get('from_region')} → {dest_display}"
        
        if key not in stats:
            stats[key] = []
        stats[key].append(d.get("latency_ms", 0))

    # Prepare rows for the HTML table
    table_rows = ""
    for route, values in stats.items():
        latest = f"{values[0]:.2f} ms" if values else "N/A"
        # Reverse values so trend goes left-to-right (chronological)
        history = list(reversed(values[:10])) 
        route_id = route.replace(" ", "").replace("→", "").replace("-", "")
        
        table_rows += f"""
        <tr>
            <td>{route}</td>
            <td style="font-weight: bold; color: #2c3e50;">{latest}</td>
            <td><canvas id="chart-{route_id}" width="150" height="40"></canvas></td>
            <script>
                new Chart(document.getElementById('chart-{route_id}'), {{
                    type: 'line',
                    data: {{
                        labels: {list(range(len(history)))},
                        datasets: [{{
                            data: {history},
                            borderColor: '#3498db',
                            borderWidth: 2,
                            pointRadius: 1,
                            fill: false,
                            tension: 0.3
                        }}]
                    }},
                    options: {{
                        responsive: false,
                        maintainAspectRatio: true,
                        scales: {{ x: {{display: false}}, y: {{display: false}} }},
                        plugins: {{ legend: {{display: false}}, tooltip: {{enabled: false}} }}
                    }}
                }});
            </script>
        </tr>
        """

    return f"""
    <html>
        <head>
            <title>Global Latency Monitor</title>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ font-family: 'Segoe UI', system-ui, sans-serif; margin: 40px; background: #f0f2f5; color: #1a1a1b; }}
                .card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); max-width: 1000px; margin: auto; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 25px; }}
                th, td {{ padding: 16px; text-align: left; border-bottom: 1px solid #eef0f2; }}
                th {{ background-color: #f8f9fa; color: #707070; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; }}
                .status-tag {{ font-size: 0.75rem; padding: 4px 10px; border-radius: 20px; background: #e7f6ed; color: #0d3c26; font-weight: bold; }}
                h1 {{ margin-top: 0; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Latency Monitor: <span style="color:#3498db;">{REGION}</span></h1>
                <p>Project: <code>{PROJECT_ID}</code> <span class="status-tag">System Active</span></p>
                
                <table>
                    <thead>
                        <tr>
                            <th>Route</th>
                            <th>Latest</th>
                            <th>Trend (Last 10)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows if table_rows else '<tr><td colspan="3">Waiting for logs... Data appears after first background test.</td></tr>'}
                    </tbody>
                </table>
                <p style="margin-top: 25px; font-size: 0.85rem; color: #888;">
                    Local Node: {current_call_url} | Refreshing every 30s
                </p>
            </div>
            <script>setTimeout(() => {{ location.reload(); }}, 30000);</script>
        </body>
    </html>
    """