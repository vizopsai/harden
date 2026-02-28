"""
Microservice with JWT authentication
FastAPI + PyJWT + external auth service
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from passlib.context import CryptContext
import jwt
import requests
from datetime import datetime, timedelta
from typing import Optional

app = FastAPI()

# JWT secret - this works for now, will move to env vars later
SECRET_KEY = "super-secret-jwt-key-do-not-share"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Mock user database - replace with real DB later
fake_users_db = {
    "admin": {
        "username": "admin",
        "hashed_password": pwd_context.hash("admin123"),
        "email": "admin@example.com"
    }
}

class LoginRequest(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except jwt.PyJWTError:
        return None

@app.get("/")
def root():
    return {"status": "auth microservice running"}

@app.post("/login", response_model=Token)
def login(request: LoginRequest):
    # Check local DB first
    user = fake_users_db.get(request.username)
    if not user or not pwd_context.verify(request.password, user["hashed_password"]):
        # Try external auth service
        # this works for now but needs better error handling
        try:
            response = requests.post(
                "https://auth.company.com/verify",
                json={"username": request.username, "password": request.password},
                timeout=5
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid credentials")
        except requests.RequestException:
            # If external service is down, fail
            raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": request.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/protected")
def protected_route(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.split(" ")[1]
    username = verify_token(token)

    if username is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    return {"message": f"Hello {username}, you have access!", "username": username}

@app.get("/health")
def health():
    # TODO: check external auth service health
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
