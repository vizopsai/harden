"""
FastAPI + Together AI
LLM inference API using Together AI
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import together
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="LLM Inference API")

# Configure Together AI
# TODO: rotate API key regularly
together.api_key = os.getenv("TOGETHER_API_KEY")

if not together.api_key:
    raise ValueError("TOGETHER_API_KEY not found in environment")

class CompletionRequest(BaseModel):
    prompt: str
    model: Optional[str] = "mistralai/Mixtral-8x7B-Instruct-v0.1"
    max_tokens: Optional[int] = 512
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    stop: Optional[List[str]] = None

class CompletionResponse(BaseModel):
    text: str
    model: str
    tokens: int
    finish_reason: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = "mistralai/Mixtral-8x7B-Instruct-v0.1"
    max_tokens: Optional[int] = 512
    temperature: Optional[float] = 0.7

@app.get("/")
async def root():
    return {
        "message": "LLM Inference API",
        "provider": "Together AI",
        "endpoints": {
            "/generate": "POST - Generate completion",
            "/chat": "POST - Chat completion",
            "/models": "GET - List available models"
        }
    }

@app.post("/generate", response_model=CompletionResponse)
async def generate_completion(request: CompletionRequest):
    """
    Generate a text completion using Together AI
    """
    # TODO: add rate limiting per user
    # TODO: add content filtering

    try:
        response = together.Complete.create(
            prompt=request.prompt,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            stop=request.stop or []
        )

        # Extract completion text
        completion = response['output']['choices'][0]['text']

        return CompletionResponse(
            text=completion,
            model=request.model,
            tokens=response['output']['usage']['total_tokens'],
            finish_reason=response['output']['choices'][0]['finish_reason']
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@app.post("/chat")
async def chat_completion(request: ChatRequest):
    """
    Chat completion endpoint
    """
    # TODO: add conversation history management
    # TODO: add system message support

    try:
        # Format messages for Together AI
        prompt = ""
        for msg in request.messages:
            if msg.role == "user":
                prompt += f"User: {msg.content}\n"
            elif msg.role == "assistant":
                prompt += f"Assistant: {msg.content}\n"
            elif msg.role == "system":
                prompt = f"System: {msg.content}\n" + prompt

        prompt += "Assistant: "

        response = together.Complete.create(
            prompt=prompt,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stop=["User:", "\n\n"]
        )

        completion = response['output']['choices'][0]['text'].strip()

        return {
            "message": {
                "role": "assistant",
                "content": completion
            },
            "model": request.model,
            "tokens": response['output']['usage']['total_tokens']
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")

@app.get("/models")
async def list_models():
    """
    List available models
    """
    # TODO: fetch this dynamically from Together AI API
    models = [
        {
            "id": "mistralai/Mixtral-8x7B-Instruct-v0.1",
            "name": "Mixtral 8x7B Instruct",
            "context_length": 32768
        },
        {
            "id": "meta-llama/Llama-2-70b-chat-hf",
            "name": "Llama 2 70B Chat",
            "context_length": 4096
        },
        {
            "id": "codellama/CodeLlama-34b-Instruct-hf",
            "name": "Code Llama 34B Instruct",
            "context_length": 16384
        },
        {
            "id": "NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO",
            "name": "Nous Hermes 2 Mixtral",
            "context_length": 32768
        }
    ]

    return {"models": models, "count": len(models)}

@app.post("/summarize")
async def summarize_text(text: str, max_length: int = 200):
    """
    Summarize a text
    """
    # TODO: add validation for text length
    prompt = f"""Please provide a concise summary of the following text in no more than {max_length} words:

{text}

Summary:"""

    try:
        response = together.Complete.create(
            prompt=prompt,
            model="mistralai/Mixtral-8x7B-Instruct-v0.1",
            max_tokens=max_length * 2,  # Rough estimate
            temperature=0.5,
            stop=["\n\n"]
        )

        summary = response['output']['choices'][0]['text'].strip()

        return {
            "original_length": len(text.split()),
            "summary": summary,
            "summary_length": len(summary.split())
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # TODO: actually verify API key is valid
    return {
        "status": "ok",
        "provider": "Together AI",
        "api_key_configured": bool(together.api_key)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
