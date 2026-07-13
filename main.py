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
    async for data in shopify_auto_check(card_str, site_url, proxy_str):
        yield f"data: {json.dumps(data)}\n\n"

@app.post("/check")
async def check_card(request: Request):
    data = await request.json()
    card_str = data.get("card")
    site_url = data.get("site")
    proxy_str = data.get("proxy")
    
    return StreamingResponse(
        event_stream(card_str, site_url, proxy_str),
        media_type="text/event-stream"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
