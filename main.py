from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from engine import run_background_process, get_stream_generator
import asyncio
import uuid

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Memory storage sementara untuk hold stream results
active_streams = {}

@app.post("/start")
async def start_check(request: Request):
    data = await request.json()
    card_str = data.get("card")
    site_url = data.get("site")
    proxy_str = data.get("proxy")
    
    if not card_str or not site_url:
        return JSONResponse({"error": "Missing card or site"}, status_code=400)
        
    job_id = str(uuid.uuid4())
    
    # Mulakan proses berat di background SEGERA
    asyncio.create_task(run_background_process(job_id, card_str, site_url, proxy_str))
    
    # Hantar ID kepada HTML dengan serta-merta (mengelakkan timeout)
    return JSONResponse({"job_id": job_id})

@app.get("/stream/{job_id}")
async def stream_check(job_id: str):
    generator = get_stream_generator(job_id)
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
