from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from engine import shopify_auto_check
import json
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/check")
async def check_card(request: Request):
    data = await request.json()
    card_str = data.get("card")
    site_url = data.get("site")
    proxy_str = data.get("proxy") 
    
    try:
        # engine sekarang pulangkan 4 benda: status, message, price, logs
        status, message, price, logs = await shopify_auto_check(card_str, site_url, proxy_str)
        return {
            "status": status,
            "message": message,
            "price": price,
            "logs": logs # KITA HANTAR LOGS NI KE WEBPAGE
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Server Error: {str(e)}",
            "price": "-",
            "logs": [f"[X] Server Exception: {str(e)}"]
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
