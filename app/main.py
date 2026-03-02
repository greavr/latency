import asyncio
import os
import time
import httpx
import json
import re
import logging
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import firebase_admin
from firebase_admin import firestore

# Import our new Gemini service module
from gemini_agent import generate_chat_response

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s"
)
logger = logging.getLogger("latency_app")

# --- Configuration ---
REGION = os.getenv("REGION", "local-dev")
PROJECT_ID = os.getenv("PROJECT_ID", "unknown")
REGION_REGEX = r'([a-z]{2,10}-[a-z]{4,10}\d)'

def get_region_from_url(url: str) -> str:
    match = re.search(REGION_REGEX, url)
    return match.group(1) if match else url.split('//')[-1].split('.')[0]

# --- Firebase Initialization ---
if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client(database_id="latency")

app = FastAPI()

# --- Templates & Static Files ---
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

class ChatRequest(BaseModel):
    message: str

def get_latency_class(ms: float) -> str:
    if ms < 50: return "lat-excellent"
    if ms < 150: return "lat-good"
    if ms < 300: return "lat-fair"
    return "lat-poor"

# --- Endpoints & Background Tasks ---

@app.post("/api/chat")
async def chat_with_gemini(req: ChatRequest):
    # Fetch latest matrix context for the AI
    logs = db.collection("latency_logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(300).stream()
    latest_matrix = {}
    
    for doc in logs:
        d = doc.to_dict()
        src = d.get('from_region', 'unknown')
        dst = d.get('to_region', 'unknown')
        lat = d.get('latency_ms', 0)
        
        if src not in latest_matrix: latest_matrix[src] = {}
        # Only keep the most recent ping for the prompt context to save tokens
        if dst not in latest_matrix[src]: latest_matrix[src][dst] = round(lat, 2)

    # Call the isolated Gemini logic
    reply = await generate_chat_response(req.message, latest_matrix)
    return {"reply": reply}

@app.get("/ping")
async def ping():
    return {"status": "ok", "region": REGION}

async def latency_worker():
    logger.info("Latency worker started. Waiting 10 seconds before first run...")
    await asyncio.sleep(10)
    
    while True:
        try:
            logger.debug("Fetching targets from Firebase...")
            targets_ref = await asyncio.to_thread(db.collection("index").document("targets").get)
            
            if not targets_ref.exists:
                logger.warning("Targets document does not exist yet. Skipping this cycle.")
                await asyncio.sleep(30)
                continue
                
            targets_data = targets_ref.to_dict()
            urls = targets_data.get("urls", [])
            
            if not urls:
                logger.info("No target URLs found in index/targets. Skipping.")
            
            for url in urls:
                target_region = get_region_from_url(url)
                logger.info(f"Pinging {url} ({target_region})...")
                
                start_time = time.time()
                async with httpx.AsyncClient(timeout=10.0) as client:
                    try:
                        resp = await client.get(f"{url}/ping")
                        resp.raise_for_status()
                        latency_ms = (time.time() - start_time) * 1000
                        logger.info(f"Ping successful to {target_region}: {latency_ms:.2f}ms")
                        
                        logger.debug(f"Attempting to write latency to Firebase for {target_region}...")
                        
                        await asyncio.to_thread(
                            db.collection("latency_logs").add,
                            {
                                "from_region": REGION,
                                "to_region": target_region,
                                "latency_ms": latency_ms,
                                "timestamp": firestore.SERVER_TIMESTAMP
                            }
                        )
                        logger.info(f"Successfully wrote {target_region} latency to Firebase.")
                        
                    except httpx.RequestError as e:
                        logger.error(f"HTTP Request failed for {url}: {str(e)}")
                    except httpx.HTTPStatusError as e:
                        logger.error(f"HTTP Status Error for {url}: {e.response.status_code}")

        except Exception as e:
            logger.error("FATAL error in latency_worker cycle!", exc_info=True)
            
        logger.info("Cycle complete. Sleeping for 60 seconds.")
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(latency_worker())

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    raw_url = str(request.base_url).rstrip("/")
    current_call_url = raw_url.replace("http://", "https://")
    
    targets_ref = db.collection("index").document("targets")
    targets_ref.set({"urls": firestore.ArrayUnion([current_call_url]), f"region_map.{REGION}": current_call_url}, merge=True)

    logs = db.collection("latency_logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(500).stream()

    matrix = {}
    regions = {REGION}

    for doc in logs:
        d = doc.to_dict()
        src = d.get('from_region') or 'unknown'
        dst = d.get('to_region') or 'unknown'
        lat = d.get('latency_ms', 0)
        
        ts = d.get('timestamp')
        ts_str = ts.strftime("%H:%M:%S") if ts else "N/A"
        
        regions.add(src)
        regions.add(dst)

        if src not in matrix: matrix[src] = {}
        if dst not in matrix[src]: matrix[src][dst] = []
        matrix[src][dst].append({"ms": round(lat, 2), "time": ts_str})

    sorted_regions = sorted(list(regions))
    
    header_html = "<tr><th>From \\ To</th>" + "".join([f"<th>{r}</th>" for r in sorted_regions]) + "</tr>"
    rows_html = ""
    for src in sorted_regions:
        row = f"<tr><td class='region-label'>{src}</td>"
        for dst in sorted_regions:
            if src == dst:
                row += "<td class='cell-self'>-</td>"
            else:
                history = matrix.get(src, {}).get(dst, [])
                if history:
                    latest = history[0]['ms']
                    row += f"""<td class='cell-active {get_latency_class(latest)}' 
                                onclick='showHistory("{src}", "{dst}", {json.dumps(history[::-1])})'>
                                {latest}ms
                              </td>"""
                else:
                    row += "<td class='cell-empty'>N/A</td>"
        rows_html += row + "</tr>"

    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "header_html": header_html, 
            "rows_html": rows_html,
            "current_url": current_call_url,
            "matrix_json": json.dumps(matrix)
        }
    )