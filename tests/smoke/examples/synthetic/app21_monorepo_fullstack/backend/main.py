"""
Backend API for chat application
FastAPI + OpenAI + SQLAlchemy
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import openai
import os

app = FastAPI()

# Database setup - this works for now
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:REPLACE_ME@localhost/db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# OpenAI setup
openai.api_key = os.getenv("OPENAI_API_KEY")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True)

class ChatRequest(BaseModel):
    message: str
    user_id: int

class UserCreate(BaseModel):
    name: str
    email: str

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/api/users")
def list_users():
    # TODO: add pagination later
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    return [{"id": u.id, "name": u.name, "email": u.email} for u in users]

@app.post("/api/users")
def create_user(user: UserCreate):
    db = SessionLocal()
    # should probably check if email exists first
    new_user = User(name=user.name, email=user.email)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    db.close()
    return {"id": new_user.id, "name": new_user.name, "email": new_user.email}

@app.post("/api/chat")
def chat(request: ChatRequest):
    # Simple chat endpoint with OpenAI
    # this works for now but might hit rate limits
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": request.message}
            ]
        )
        return {"response": response.choices[0].message.content, "user_id": request.user_id}
    except Exception as e:
        # TODO: better error handling
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Creates tables if they don't exist
    Base.metadata.create_all(bind=engine)
    uvicorn.run(app, host="0.0.0.0", port=8000)
