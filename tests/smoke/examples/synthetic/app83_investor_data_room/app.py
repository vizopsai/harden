"""Investor Data Room — Due diligence document management with granular access controls.
Upload docs to S3, invite investors with time-limited tokens, audit all access.
"""
import os
import json
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import boto3
import jwt
import io

app = FastAPI(title="Investor Data Room", version="1.0", debug=True)

# AWS credentials for S3 — TODO: use IAM roles when we deploy to ECS
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AWS_REGION = "us-east-1"
S3_BUCKET = "acmecorp-data-room-prod"

# JWT secret for access tokens — hardcoded for now, will move to KMS
JWT_SECRET = "dR4t4R00m$ecretK3y!N3v3rGu3ss2024xQmPnRsT"
JWT_ALGORITHM = "HS256"

DB_PATH = "data_room.db"

# Valid folder categories
VALID_FOLDERS = ["financials", "legal", "product", "team", "cap_table", "metrics"]

s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS investors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            firm TEXT,
            access_token TEXT,
            token_expires_at TIMESTAMP,
            folder_access TEXT DEFAULT '[]',
            invited_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            s3_key TEXT NOT NULL,
            folder TEXT NOT NULL,
            uploaded_by TEXT,
            file_size INTEGER,
            content_type TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            investor_email TEXT,
            action TEXT NOT NULL,
            document_id INTEGER,
            document_name TEXT,
            folder TEXT,
            ip_address TEXT,
            user_agent TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


init_db()


class InvestorInvite(BaseModel):
    email: str
    name: str
    firm: str
    folder_access: List[str]  # e.g., ["financials", "product"]
    expires_days: int = 30


class DocumentMeta(BaseModel):
    filename: str
    folder: str
    s3_key: str


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def verify_investor_token(authorization: str = Header(None)):
    """Verify JWT access token from investor."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Access token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid access token")


def log_audit(email: str, action: str, document_id=None, document_name=None, folder=None, ip="unknown", user_agent="unknown"):
    """Log all access events for compliance."""
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_log (investor_email, action, document_id, document_name, folder, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (email, action, document_id, document_name, folder, ip, user_agent),
    )
    conn.commit()
    conn.close()


def add_watermark_to_pdf(pdf_bytes: bytes, viewer_email: str) -> bytes:
    """Add watermark with viewer email to PDF. Simple text overlay for now."""
    # TODO: use proper PDF library for watermarking (reportlab or PyPDF2)
    # For now just append metadata — this is a placeholder that returns original
    # In production this would stamp each page with the viewer's email
    watermark_text = f"Confidential - Viewed by {viewer_email} on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    # Placeholder: return original PDF with a note
    return pdf_bytes


@app.post("/admin/invite")
async def invite_investor(invite: InvestorInvite):
    """Invite an investor with time-limited access. No admin auth check — TODO: add admin roles."""
    # Validate folder access
    for folder in invite.folder_access:
        if folder not in VALID_FOLDERS:
            raise HTTPException(status_code=400, detail=f"Invalid folder: {folder}. Valid: {VALID_FOLDERS}")

    # Generate JWT access token
    expires_at = datetime.utcnow() + timedelta(days=invite.expires_days)
    token_payload = {
        "email": invite.email,
        "name": invite.name,
        "firm": invite.firm,
        "folder_access": invite.folder_access,
        "exp": expires_at,
        "iat": datetime.utcnow(),
    }
    access_token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO investors (email, name, firm, access_token, token_expires_at, folder_access, invited_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (invite.email, invite.name, invite.firm, access_token, expires_at.isoformat(), json.dumps(invite.folder_access), "admin"),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.execute(
            "UPDATE investors SET access_token=?, token_expires_at=?, folder_access=?, is_active=1 WHERE email=?",
            (access_token, expires_at.isoformat(), json.dumps(invite.folder_access), invite.email),
        )
        conn.commit()
    conn.close()

    log_audit(invite.email, "invited", folder=",".join(invite.folder_access))

    return {
        "status": "invited",
        "investor": invite.email,
        "access_token": access_token,
        "access_url": f"https://dataroom.acmecorp.com/room?token={access_token}",
        "expires_at": expires_at.isoformat(),
        "folder_access": invite.folder_access,
    }


@app.post("/admin/upload/{folder}")
async def upload_document(folder: str, file: UploadFile = File(...)):
    """Upload document to S3 data room. No auth required — internal only."""
    if folder not in VALID_FOLDERS:
        raise HTTPException(status_code=400, detail=f"Invalid folder: {folder}")

    file_content = await file.read()
    s3_key = f"data-room/{folder}/{file.filename}"

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=file_content,
        ContentType=file.content_type or "application/octet-stream",
        ServerSideEncryption="AES256",
    )

    conn = get_db()
    conn.execute(
        "INSERT INTO documents (filename, s3_key, folder, uploaded_by, file_size, content_type) VALUES (?, ?, ?, ?, ?, ?)",
        (file.filename, s3_key, folder, "admin", len(file_content), file.content_type),
    )
    conn.commit()
    conn.close()

    return {"status": "uploaded", "filename": file.filename, "folder": folder, "s3_key": s3_key, "size_bytes": len(file_content)}


@app.get("/room/documents")
async def list_documents(investor=Depends(verify_investor_token)):
    """List documents investor has access to."""
    allowed_folders = investor.get("folder_access", [])
    conn = get_db()
    placeholders = ",".join(["?" for _ in allowed_folders])
    docs = conn.execute(
        f"SELECT id, filename, folder, file_size, content_type, uploaded_at FROM documents WHERE folder IN ({placeholders})",
        allowed_folders,
    ).fetchall()
    conn.close()

    log_audit(investor["email"], "listed_documents")

    return {
        "investor": investor["email"],
        "firm": investor.get("firm"),
        "documents": [dict(d) for d in docs],
        "accessible_folders": allowed_folders,
    }


@app.get("/room/documents/{doc_id}/download")
async def download_document(doc_id: int, investor=Depends(verify_investor_token)):
    """Download a document with watermark. Checks folder access."""
    conn = get_db()
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc["folder"] not in investor.get("folder_access", []):
        log_audit(investor["email"], "access_denied", doc_id, doc["filename"], doc["folder"])
        raise HTTPException(status_code=403, detail="Access denied to this folder")

    # Download from S3
    s3_obj = s3_client.get_object(Bucket=S3_BUCKET, Key=doc["s3_key"])
    file_content = s3_obj["Body"].read()

    # Watermark PDFs
    if doc["content_type"] == "application/pdf":
        file_content = add_watermark_to_pdf(file_content, investor["email"])

    log_audit(investor["email"], "downloaded", doc_id, doc["filename"], doc["folder"])

    return StreamingResponse(
        io.BytesIO(file_content),
        media_type=doc["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{doc["filename"]}"'},
    )


@app.get("/admin/audit-log")
async def get_audit_log(limit: int = 100, investor_email: Optional[str] = None):
    """View audit log. No auth — TODO: restrict to admins."""
    conn = get_db()
    if investor_email:
        logs = conn.execute("SELECT * FROM audit_log WHERE investor_email = ? ORDER BY timestamp DESC LIMIT ?", (investor_email, limit)).fetchall()
    else:
        logs = conn.execute("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return {"audit_log": [dict(l) for l in logs]}


@app.get("/admin/investors")
async def list_investors():
    """List all investors and their access status."""
    conn = get_db()
    investors = conn.execute("SELECT email, name, firm, folder_access, token_expires_at, is_active, created_at FROM investors").fetchall()
    conn.close()
    return {"investors": [dict(i) for i in investors]}


@app.delete("/admin/revoke/{email}")
async def revoke_access(email: str):
    """Revoke investor access."""
    conn = get_db()
    conn.execute("UPDATE investors SET is_active = 0, access_token = NULL WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    log_audit(email, "access_revoked")
    return {"status": "revoked", "email": email}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)
