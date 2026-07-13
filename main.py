from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from engine import shopify_auto_check
import json

app = FastAPI()

# Benarkan webpage HTML connect ke API ni
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

async def event_stream(card_str, site_url, proxy_str):
    try:
        async for data in shopify_auto_check(card_str, site_url, proxy_str):
            yield f"data: {json.dumps(data)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"

@app.post("/check")
async def check_card(request: Request):
    data = await request.json()
    card_str = data.get("card")
    site_url = data.get("site")
    proxy_str = data.get("proxy")
    
    return StreamingResponse(
        event_stream(card_str, site_url, proxy_str),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no", # PENTING: Elakkan Railway/Proxy simpan buffer
        }
    )

if __name__ == "__main__":
    import uvicorn
    # timeout_keep_alive=300 untuk bagi masa 5 minit
    uvicorn.run(app, host="0.0.0.0", port=8000, timeout_keep_alive=300)
