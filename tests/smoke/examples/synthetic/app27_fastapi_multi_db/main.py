"""
FastAPI app using both PostgreSQL and Redis
Demonstrates multi-database architecture
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
import redis
import json
import os
from typing import Optional

app = FastAPI()

# Database configs - this works for now
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:REPLACE_ME@localhost:5432/mydb")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Redis connection - TODO: use connection pool
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def get_db_connection():
    """Get PostgreSQL connection - this works for now but should use connection pooling"""
    return psycopg2.connect(DATABASE_URL)

class User(BaseModel):
    id: Optional[int] = None
    name: str
    email: str

class CacheItem(BaseModel):
    key: str
    value: str
    ttl: Optional[int] = 3600

@app.on_event("startup")
async def startup_event():
    """Initialize database tables if needed"""
    conn = get_db_connection()
    cur = conn.cursor()
    # Create users table - this works for now
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255),
            email VARCHAR(255) UNIQUE
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.get("/")
def root():
    return {"status": "multi-db service running"}

@app.get("/users")
def list_users():
    """Get all users from PostgreSQL"""
    # Check cache first
    cached = redis_client.get("users:all")
    if cached:
        return {"users": json.loads(cached), "from_cache": True}

    # Query database
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email FROM users")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    users = [{"id": r[0], "name": r[1], "email": r[2]} for r in rows]

    # Cache for 5 minutes
    redis_client.setex("users:all", 300, json.dumps(users))

    return {"users": users, "from_cache": False}

@app.post("/users")
def create_user(user: User):
    """Create user in PostgreSQL"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (name, email) VALUES (%s, %s) RETURNING id",
            (user.name, user.email)
        )
        user_id = cur.fetchone()[0]
        conn.commit()

        # Invalidate cache
        redis_client.delete("users:all")

        return {"id": user_id, "name": user.name, "email": user.email}

    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Email already exists")
    finally:
        cur.close()
        conn.close()

@app.get("/cache/{key}")
def get_cache(key: str):
    """Get value from Redis cache"""
    value = redis_client.get(key)
    if value is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"key": key, "value": value}

@app.post("/cache")
def set_cache(item: CacheItem):
    """Set value in Redis cache with optional TTL"""
    if item.ttl:
        redis_client.setex(item.key, item.ttl, item.value)
    else:
        redis_client.set(item.key, item.value)
    return {"key": item.key, "status": "cached", "ttl": item.ttl}

@app.delete("/cache/{key}")
def delete_cache(key: str):
    """Delete key from Redis"""
    result = redis_client.delete(key)
    if result == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"key": key, "status": "deleted"}

@app.get("/health")
def health():
    """Health check for both databases"""
    # Check PostgreSQL
    postgres_ok = False
    try:
        conn = get_db_connection()
        conn.close()
        postgres_ok = True
    except:
        pass

    # Check Redis
    redis_ok = False
    try:
        redis_client.ping()
        redis_ok = True
    except:
        pass

    return {
        "status": "healthy" if (postgres_ok and redis_ok) else "degraded",
        "postgres": postgres_ok,
        "redis": redis_ok
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
