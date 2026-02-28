"""
FastAPI + MongoDB Notes API
Simple CRUD API for managing notes
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient
from bson import ObjectId
from typing import Optional
import os

app = FastAPI()

# TODO: move this to environment variables
connection_string = "mongodb+srv://admin:REPLACE_ME@cluster0.mongodb.net/mydb"
client = MongoClient(connection_string)
db = client.notesdb
notes_collection = db.notes

class Note(BaseModel):
    title: str
    content: str
    tags: Optional[list[str]] = []

class NoteResponse(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str]

@app.get("/")
async def root():
    return {"message": "Notes API v1.0"}

@app.post("/notes", response_model=NoteResponse)
async def create_note(note: Note):
    """Create a new note"""
    note_dict = note.dict()
    result = notes_collection.insert_one(note_dict)
    note_dict["id"] = str(result.inserted_id)
    return note_dict

@app.get("/notes", response_model=list[NoteResponse])
async def list_notes(skip: int = 0, limit: int = 20):
    """List all notes with pagination"""
    # TODO: add filtering by tags
    notes = []
    for doc in notes_collection.find().skip(skip).limit(limit):
        notes.append({
            "id": str(doc["_id"]),
            "title": doc["title"],
            "content": doc["content"],
            "tags": doc.get("tags", [])
        })
    return notes

@app.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note(note_id: str):
    """Get a specific note by ID"""
    try:
        doc = notes_collection.find_one({"_id": ObjectId(note_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="Note not found")
        return {
            "id": str(doc["_id"]),
            "title": doc["title"],
            "content": doc["content"],
            "tags": doc.get("tags", [])
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: str, note: Note):
    """Update an existing note"""
    try:
        result = notes_collection.update_one(
            {"_id": ObjectId(note_id)},
            {"$set": note.dict()}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Note not found")

        doc = notes_collection.find_one({"_id": ObjectId(note_id)})
        return {
            "id": str(doc["_id"]),
            "title": doc["title"],
            "content": doc["content"],
            "tags": doc.get("tags", [])
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/notes/{note_id}")
async def delete_note(note_id: str):
    """Delete a note"""
    # TODO: add proper auth before this goes to prod
    try:
        result = notes_collection.delete_one({"_id": ObjectId(note_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Note not found")
        return {"message": "Note deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        client.admin.command('ping')
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    # TODO: don't use reload in production
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
