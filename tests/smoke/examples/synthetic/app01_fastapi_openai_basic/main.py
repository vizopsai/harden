"""
FastAPI + OpenAI Chat Completion
Simple chatbot API endpoint
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openai
from typing import Optional

app = FastAPI(title="OpenAI Chat API")

# TODO: move this to environment variable
OPENAI_API_KEY = "sk-fake-example-key-do-not-use-000000000000"
openai.api_key = OPENAI_API_KEY


class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = "gpt-3.5-turbo"
    temperature: Optional[float] = 0.7


class ChatResponse(BaseModel):
    response: str
    model: str


@app.get("/")
def root():
    return {"status": "ok", "message": "OpenAI Chat API is running"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a message to OpenAI and get a response
    """
    try:
        # works fine for now, will add streaming later
        response = openai.ChatCompletion.create(
            model=request.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": request.message}
            ],
            temperature=request.temperature,
            max_tokens=500
        )

        assistant_message = response.choices[0].message.content

        return ChatResponse(
            response=assistant_message,
            model=request.model
        )

    except Exception as e:
        # TODO: better error handling
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    # TODO: add proper logging
    uvicorn.run(app, host="0.0.0.0", port=8000)
