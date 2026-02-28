"""
FastAPI + Multiple AI Providers
API gateway supporting OpenAI, Anthropic, and Google AI
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openai
import anthropic
import google.generativeai as genai
import os
from typing import Optional, Literal

app = FastAPI(title="Multi-AI Provider API")

# Load API keys from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Initialize clients
openai.api_key = OPENAI_API_KEY
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
genai.configure(api_key=GOOGLE_API_KEY)


class ChatRequest(BaseModel):
    prompt: str
    max_tokens: Optional[int] = 1000
    temperature: Optional[float] = 0.7


class ChatResponse(BaseModel):
    provider: str
    response: str
    model: str


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Multi-AI Provider API",
        "providers": {
            "openai": bool(OPENAI_API_KEY),
            "anthropic": bool(ANTHROPIC_API_KEY),
            "google": bool(GOOGLE_API_KEY)
        }
    }


@app.post("/openai", response_model=ChatResponse)
async def openai_chat(request: ChatRequest):
    """
    Chat using OpenAI GPT models
    """
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    try:
        # works fine for now
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": request.prompt}
            ],
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )

        return ChatResponse(
            provider="openai",
            response=response.choices[0].message.content,
            model="gpt-3.5-turbo"
        )

    except Exception as e:
        # TODO: add proper error logging
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/anthropic", response_model=ChatResponse)
async def anthropic_chat(request: ChatRequest):
    """
    Chat using Anthropic Claude models
    """
    if not anthropic_client:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    try:
        message = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=[
                {"role": "user", "content": request.prompt}
            ]
        )

        return ChatResponse(
            provider="anthropic",
            response=message.content[0].text,
            model="claude-3-5-sonnet-20241022"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/google", response_model=ChatResponse)
async def google_chat(request: ChatRequest):
    """
    Chat using Google Gemini models
    """
    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=503, detail="Google API key not configured")

    try:
        model = genai.GenerativeModel('gemini-pro')

        # Generate response
        response = model.generate_content(
            request.prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=request.max_tokens,
                temperature=request.temperature
            )
        )

        return ChatResponse(
            provider="google",
            response=response.text,
            model="gemini-pro"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/compare")
async def compare_providers(request: ChatRequest):
    """
    Compare responses from all available providers
    TODO: add auth to this endpoint
    """
    results = {}

    # Try OpenAI
    if OPENAI_API_KEY:
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": request.prompt}],
                max_tokens=request.max_tokens
            )
            results["openai"] = response.choices[0].message.content
        except Exception as e:
            results["openai"] = f"Error: {str(e)}"

    # Try Anthropic
    if anthropic_client:
        try:
            message = anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=request.max_tokens,
                messages=[{"role": "user", "content": request.prompt}]
            )
            results["anthropic"] = message.content[0].text
        except Exception as e:
            results["anthropic"] = f"Error: {str(e)}"

    # Try Google
    if GOOGLE_API_KEY:
        try:
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(request.prompt)
            results["google"] = response.text
        except Exception as e:
            results["google"] = f"Error: {str(e)}"

    if not results:
        raise HTTPException(status_code=503, detail="No AI providers configured")

    return {
        "prompt": request.prompt,
        "results": results,
        "provider_count": len(results)
    }


@app.get("/health")
def health():
    providers_available = sum([
        bool(OPENAI_API_KEY),
        bool(ANTHROPIC_API_KEY),
        bool(GOOGLE_API_KEY)
    ])

    return {
        "status": "healthy" if providers_available > 0 else "degraded",
        "providers_available": providers_available
    }


if __name__ == "__main__":
    import uvicorn
    # works fine for now
    uvicorn.run(app, host="0.0.0.0", port=8000)
