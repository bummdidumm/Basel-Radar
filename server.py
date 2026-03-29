import os
import subprocess
from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Basel Radar Dashboard")

# Serve debug JSON files
app.mount("/data", StaticFiles(directory="debug_gemini_day_scan"), name="data")

# Serve the main dashboard
@app.get("/")
async def get_dashboard():
    return FileResponse("index.html")

class ScanRequest(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None

def run_scan_script(date_from: Optional[str], date_to: Optional[str]):
    env = os.environ.copy()
    if date_from:
        env["DATE_FROM"] = date_from
    if date_to:
        env["DATE_TO"] = date_to

    # Run the scraper script
    subprocess.run(["python", "scraper/gemini_day_scan.py"], env=env)

@app.post("/api/scan")
async def trigger_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scan_script, request.date_from, request.date_to)
    return {"message": "Scan started in background"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
