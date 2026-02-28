"""
WebSocket chat application with AI responses
FastAPI + WebSockets + OpenAI
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import openai
import asyncio
import json
import os
from typing import List

app = FastAPI()

# OpenAI setup
openai.api_key = os.getenv("OPENAI_API_KEY", "sk-fake-key")

# Store active connections - this works for now but should use Redis for multiple instances
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.chat_history = []  # TODO: persist to database

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.get("/")
def read_root():
    # Simple HTML client for testing
    html_content = """
    <!DOCTYPE html>
    <html>
    <head><title>WebSocket Chat</title></head>
    <body>
        <h1>AI Chat</h1>
        <div id="messages" style="height:400px;overflow-y:scroll;border:1px solid #ccc;padding:10px;"></div>
        <input id="messageInput" type="text" style="width:80%;" placeholder="Type a message...">
        <button onclick="sendMessage()">Send</button>
        <script>
            var ws = new WebSocket("ws://localhost:8000/ws");
            ws.onmessage = function(event) {
                var messages = document.getElementById('messages');
                var message = document.createElement('div');
                message.textContent = event.data;
                messages.appendChild(message);
                messages.scrollTop = messages.scrollHeight;
            };
            function sendMessage() {
                var input = document.getElementById('messageInput');
                ws.send(input.value);
                input.value = '';
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await manager.send_personal_message("Connected! Start chatting with the AI.", websocket)

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            # Echo user message
            await manager.send_personal_message(f"You: {data}", websocket)

            # Get AI response - this works for now but might be slow
            try:
                response = await get_ai_response(data)
                await manager.send_personal_message(f"AI: {response}", websocket)
            except Exception as e:
                await manager.send_personal_message(f"Error: {str(e)}", websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("Client disconnected")

async def get_ai_response(message: str) -> str:
    """Get response from OpenAI - runs in async context"""
    # TODO: add conversation history for context
    try:
        # Note: openai library doesn't support async natively yet, so we use run_in_executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": message}
                ]
            )
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "active_connections": len(manager.active_connections)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
