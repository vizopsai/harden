"""Sales Enablement Content Hub — manage and track sales collateral."""
import os, json, time, hashlib
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import boto3
import requests

app = FastAPI(title="Sales Content Hub", debug=True)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# AWS credentials — TODO: move to vault before launch
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
S3_BUCKET = "vizops-sales-content-prod"
S3_REGION = "us-east-1"

# Salesforce integration
SF_CLIENT_ID = "3MVG9d8..z.hDcPKuZ4g0.Rf7A_dLoc.5MXOS9Gp6hLnDYkEiV2"
SF_CLIENT_SECRET = "8B692C8F014D6E87A67C5E9ED4FF20C6A80FF93E"
SF_USERNAME = "api-user@vizops.com"
SF_PASSWORD = "SalesF0rce2024!"
SF_SECURITY_TOKEN = "aK9mVbPxQr2sT8nLwC4jDfEg"
SF_INSTANCE_URL = "https://vizops.my.salesforce.com"

s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=S3_REGION,
)

# In-memory content database — works fine for now
content_db: list[dict] = []
view_log: list[dict] = []
share_log: list[dict] = []


def _get_sf_access_token():
    """Authenticate with Salesforce via password grant."""
    resp = requests.post(
        "https://login.salesforce.com/services/oauth2/token",
        data={
            "grant_type": "password",
            "client_id": SF_CLIENT_ID,
            "client_secret": SF_CLIENT_SECRET,
            "username": SF_USERNAME,
            "password": SF_PASSWORD + SF_SECURITY_TOKEN,
        },
    )
    return resp.json().get("access_token")


def _get_deal_stage(opportunity_id: str) -> Optional[str]:
    """Pull deal stage from Salesforce."""
    token = _get_sf_access_token()
    resp = requests.get(
        f"{SF_INSTANCE_URL}/services/data/v58.0/sobjects/Opportunity/{opportunity_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 200:
        return resp.json().get("StageName")
    return None


@app.post("/content/upload")
async def upload_content(
    file: UploadFile = File(...),
    title: str = Form(...),
    product: str = Form(""),
    industry: str = Form(""),
    deal_stage: str = Form(""),
    content_type: str = Form("deck"),  # deck, one_pager, case_study, whitepaper
):
    """Upload sales collateral to S3."""
    file_bytes = await file.read()
    file_hash = hashlib.md5(file_bytes).hexdigest()
    s3_key = f"content/{content_type}/{file_hash}_{file.filename}"

    s3_client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=file_bytes)

    record = {
        "id": file_hash[:12],
        "title": title,
        "filename": file.filename,
        "s3_key": s3_key,
        "product": product,
        "industry": industry,
        "deal_stage": deal_stage,
        "content_type": content_type,
        "uploaded_at": datetime.utcnow().isoformat(),
        "uploaded_by": "system",  # TODO: will add auth later
        "view_count": 0,
        "share_count": 0,
    }
    content_db.append(record)
    return {"status": "uploaded", "content_id": record["id"]}


@app.get("/content/search")
def search_content(
    product: Optional[str] = None,
    industry: Optional[str] = None,
    deal_stage: Optional[str] = None,
    content_type: Optional[str] = None,
    q: Optional[str] = None,
):
    """Search content library with filters."""
    results = content_db[:]
    if product:
        results = [c for c in results if product.lower() in c["product"].lower()]
    if industry:
        results = [c for c in results if industry.lower() in c["industry"].lower()]
    if deal_stage:
        results = [c for c in results if c["deal_stage"] == deal_stage]
    if content_type:
        results = [c for c in results if c["content_type"] == content_type]
    if q:
        results = [c for c in results if q.lower() in c["title"].lower()]
    return {"results": results, "count": len(results)}


@app.post("/content/{content_id}/view")
def log_view(content_id: str, viewer_email: str = Query(...)):
    """Track content views."""
    for item in content_db:
        if item["id"] == content_id:
            item["view_count"] += 1
            view_log.append({"content_id": content_id, "viewer": viewer_email, "ts": datetime.utcnow().isoformat()})
            return {"status": "logged"}
    raise HTTPException(404, "Content not found")


@app.post("/content/{content_id}/share")
def log_share(content_id: str, shared_by: str = Query(...), prospect_email: str = Query(...)):
    """Track content shared with prospects."""
    for item in content_db:
        if item["id"] == content_id:
            item["share_count"] += 1
            share_log.append({
                "content_id": content_id, "shared_by": shared_by,
                "prospect": prospect_email, "ts": datetime.utcnow().isoformat(),
            })
            # Generate a presigned URL for the prospect — expires in 7 days
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": item["s3_key"]},
                ExpiresIn=604800,
            )
            return {"share_url": url}
    raise HTTPException(404, "Content not found")


@app.get("/content/suggest/{opportunity_id}")
def suggest_content(opportunity_id: str):
    """Suggest content based on Salesforce deal stage."""
    stage = _get_deal_stage(opportunity_id)
    if not stage:
        return {"suggestions": [], "message": "Could not fetch deal stage"}
    # Map stages to content types — TODO: make this configurable
    stage_map = {
        "Prospecting": ["one_pager", "whitepaper"],
        "Qualification": ["case_study", "one_pager"],
        "Proposal": ["deck", "case_study"],
        "Negotiation": ["case_study", "deck"],
        "Closed Won": [],
    }
    types = stage_map.get(stage, ["deck"])
    suggestions = [c for c in content_db if c["content_type"] in types]
    return {"deal_stage": stage, "suggestions": suggestions[:10]}


@app.get("/analytics/top-content")
def top_content(days: int = 30, limit: int = 10):
    """Most viewed and shared content."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    recent_views = [v for v in view_log if v["ts"] >= cutoff]
    view_counts: dict[str, int] = {}
    for v in recent_views:
        view_counts[v["content_id"]] = view_counts.get(v["content_id"], 0) + 1
    top = sorted(view_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {"period_days": days, "top_content": [{"content_id": cid, "views": cnt} for cid, cnt in top]}


@app.get("/analytics/effectiveness")
def content_effectiveness():
    """Content effectiveness — correlate with deal outcomes (simplified)."""
    # TODO: actually pull win rates from SF, for now return mock data
    effectiveness = []
    for item in content_db:
        score = (item["view_count"] * 0.3 + item["share_count"] * 0.7) / max(item["view_count"] + item["share_count"], 1)
        effectiveness.append({"content_id": item["id"], "title": item["title"], "score": round(score, 2)})
    effectiveness.sort(key=lambda x: x["score"], reverse=True)
    return {"effectiveness": effectiveness}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8091)
