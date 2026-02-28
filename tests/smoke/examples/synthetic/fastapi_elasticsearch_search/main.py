"""
FastAPI + Elasticsearch search service
Provides full-text search across documents
"""
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from elasticsearch import Elasticsearch
from typing import Optional, List
import os

app = FastAPI(title="Search API")

# Initialize Elasticsearch client
# TODO: move credentials to secrets manager
es = Elasticsearch(
    ["http://es-cluster.internal:9200"],
    api_key="base64encodedkey=="
)

INDEX_NAME = "documents"

class Document(BaseModel):
    title: str
    content: str
    category: Optional[str] = None
    tags: Optional[List[str]] = []

class SearchResponse(BaseModel):
    total: int
    hits: List[dict]
    took: int

@app.on_event("startup")
async def startup_event():
    """Initialize Elasticsearch index on startup"""
    # TODO: add proper index mapping
    if not es.indices.exists(index=INDEX_NAME):
        es.indices.create(index=INDEX_NAME, body={
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0
            },
            "mappings": {
                "properties": {
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                    "category": {"type": "keyword"},
                    "tags": {"type": "keyword"}
                }
            }
        })

@app.get("/")
async def root():
    return {"message": "Search API v1", "index": INDEX_NAME}

@app.post("/documents")
async def index_document(doc: Document):
    """Index a new document"""
    try:
        result = es.index(
            index=INDEX_NAME,
            document=doc.dict()
        )
        return {
            "id": result["_id"],
            "result": result["result"],
            "message": "Document indexed successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., description="Search query"),
    category: Optional[str] = None,
    size: int = Query(10, ge=1, le=100)
):
    """
    Full-text search across documents
    """
    # Build query
    query = {
        "bool": {
            "must": [
                {
                    "multi_match": {
                        "query": q,
                        "fields": ["title^2", "content"],
                        "type": "best_fields"
                    }
                }
            ]
        }
    }

    # Add category filter if specified
    if category:
        query["bool"]["filter"] = [{"term": {"category": category}}]

    try:
        response = es.search(
            index=INDEX_NAME,
            query=query,
            size=size
        )

        hits = []
        for hit in response["hits"]["hits"]:
            hits.append({
                "id": hit["_id"],
                "score": hit["_score"],
                **hit["_source"]
            })

        return {
            "total": response["hits"]["total"]["value"],
            "hits": hits,
            "took": response["took"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    """Retrieve a document by ID"""
    try:
        result = es.get(index=INDEX_NAME, id=doc_id)
        return {
            "id": result["_id"],
            **result["_source"]
        }
    except Exception as e:
        if "NotFoundError" in str(type(e)):
            raise HTTPException(status_code=404, detail="Document not found")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document"""
    # TODO: add authentication before enabling this in production
    try:
        result = es.delete(index=INDEX_NAME, id=doc_id)
        return {"message": "Document deleted", "result": result["result"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Check Elasticsearch cluster health"""
    try:
        health = es.cluster.health()
        return {
            "status": "ok",
            "cluster_status": health["status"],
            "number_of_nodes": health["number_of_nodes"]
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
