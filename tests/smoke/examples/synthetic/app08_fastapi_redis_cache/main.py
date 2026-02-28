"""
FastAPI + Redis Caching
Simple API with Redis-based caching layer
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import json
from typing import Optional
from datetime import datetime
import hashlib

app = FastAPI(title="Redis Cache API")

# Redis connection - hardcoded for now
# TODO: move to environment variables
redis_client = redis.Redis(
    host="redis.internal.company.com",
    port=6379,
    password="secret123",
    decode_responses=True,
    socket_connect_timeout=5
)

# Cache TTL in seconds
CACHE_TTL = 300  # 5 minutes


class DataRequest(BaseModel):
    query: str
    use_cache: Optional[bool] = True


class DataResponse(BaseModel):
    query: str
    result: dict
    cached: bool
    timestamp: str


def generate_cache_key(query: str) -> str:
    """Generate a cache key from query"""
    return f"cache:{hashlib.md5(query.encode()).hexdigest()}"


def expensive_operation(query: str) -> dict:
    """
    Simulate an expensive database query or API call
    In reality, this would query a database or external API
    """
    # works fine for now - just returns dummy data
    return {
        "query": query,
        "data": f"Result for: {query}",
        "processed_at": datetime.now().isoformat(),
        "rows": 42
    }


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Redis Cache API",
        "redis_connected": check_redis_connection()
    }


def check_redis_connection() -> bool:
    """Check if Redis is accessible"""
    try:
        redis_client.ping()
        return True
    except:
        return False


@app.post("/data", response_model=DataResponse)
async def get_data(request: DataRequest):
    """
    Get data with caching
    If use_cache=True, checks Redis first before expensive operation
    """
    cache_key = generate_cache_key(request.query)
    cached = False

    # Try to get from cache if enabled
    if request.use_cache:
        try:
            cached_data = redis_client.get(cache_key)
            if cached_data:
                result = json.loads(cached_data)
                return DataResponse(
                    query=request.query,
                    result=result,
                    cached=True,
                    timestamp=datetime.now().isoformat()
                )
        except redis.RedisError as e:
            # TODO: add proper logging
            print(f"Redis error: {e}")
            # Continue without cache

    # Perform expensive operation
    result = expensive_operation(request.query)

    # Store in cache for next time
    if request.use_cache:
        try:
            redis_client.setex(
                cache_key,
                CACHE_TTL,
                json.dumps(result)
            )
        except redis.RedisError as e:
            print(f"Failed to cache result: {e}")
            # Continue anyway

    return DataResponse(
        query=request.query,
        result=result,
        cached=False,
        timestamp=datetime.now().isoformat()
    )


@app.delete("/cache/{query}")
async def clear_cache(query: str):
    """Clear cache for a specific query"""
    cache_key = generate_cache_key(query)

    try:
        deleted = redis_client.delete(cache_key)
        return {
            "message": "Cache cleared" if deleted else "Cache key not found",
            "deleted": bool(deleted)
        }
    except redis.RedisError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/cache")
async def clear_all_cache():
    """
    Clear all cache entries
    TODO: add auth to this endpoint
    """
    try:
        # Get all cache keys
        keys = redis_client.keys("cache:*")
        if keys:
            deleted = redis_client.delete(*keys)
            return {
                "message": f"Cleared {deleted} cache entries",
                "deleted": deleted
            }
        else:
            return {"message": "No cache entries found", "deleted": 0}
    except redis.RedisError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def cache_stats():
    """Get cache statistics"""
    try:
        keys = redis_client.keys("cache:*")
        return {
            "total_cached_items": len(keys),
            "redis_info": {
                "connected_clients": redis_client.info().get('connected_clients'),
                "used_memory_human": redis_client.info().get('used_memory_human')
            }
        }
    except redis.RedisError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    redis_ok = check_redis_connection()
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
