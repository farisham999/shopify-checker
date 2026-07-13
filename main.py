from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from engine import shopify_auto_check
import asyncio

app = FastAPI()

# Benarkan webpage HTML connect ke API ni
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
    proxy_str = None 
    
    try:
        status, message, price = await shopify_auto_check(card_str, site_url, proxy_str)
        return {
            "status": status,
            "message": message,
            "price": price
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Server Error: {str(e)}",
            "price": "-"
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
