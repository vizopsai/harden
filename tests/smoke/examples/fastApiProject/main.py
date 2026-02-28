from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import Optional
import requests

load_dotenv()

app = FastAPI()

# Mounting static directory for performance reasons
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")

# OpenAI API key
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

# Alpha Vantage API key
alpha_vantage_api = os.environ.get("ALPHA_VANTAGE_API_KEY")


@app.get("/")
def test_root():
    return {"test message": "Hello World"}


# Browser icon implementation
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")


@app.post("/chat")
async def post_chat_message(request: Request):
    data = await request.json()
    message = data.get("text")

    try:
        chat_completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": message}]
        )
        gpt_message = chat_completion.choices[0].message.content
        return {"text": gpt_message}
    except Exception as e:
        return {"error": str(e)}


# GET request to display 'chat' html
@app.get("/chat", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# GET request to display 'stock' html
@app.get("/stock", response_class=HTMLResponse)
async def get_stock_page(request: Request):
    return templates.TemplateResponse("stock.html", {"request": request})


@app.get("/stock_price")
async def get_stock_price(ticker: Optional[str] = None):


    search_url = f"https://www.alphavantage.co/query?function=SYMBOL_SEARCH&keywords={ticker}&apikey={alpha_vantage_api}"
    search_response = requests.get(search_url)
    search_data = search_response.json()

    print(f"Search Data: {search_data}")  # Debugging print statement

    try:
        # Fetch only name from JSON
        stock_name = search_data["bestMatches"][0]["2. name"]
    except (KeyError, IndexError) as e:
        print(f"Error while fetching stock name: {e}")  # Debugging print statement

        return {"error": "Invalid ticker or no matches found"}


    quote_url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={alpha_vantage_api}"
    quote_response = requests.get(quote_url)
    quote_data = quote_response.json()

    print(f"Quote Data: {quote_data}")  # Debugging print statement

    try:
        # Fetch only price from JSON
        latest_price = quote_data["Global Quote"]["05. price"]
        return {"stock_name": stock_name, "price": latest_price}
    except KeyError:
        return {"error": "Failed to  retrieve stock price"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info", reload=True)
