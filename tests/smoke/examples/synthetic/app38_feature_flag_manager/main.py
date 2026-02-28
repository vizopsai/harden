"""Feature Flag Manager — replaces LaunchDarkly.
Built in-house because LaunchDarkly was $4K/month and we only needed basic flags.
Supports percentage rollout, user targeting, and segment rules.
TODO: add flag dependencies (flag A requires flag B)
TODO: add scheduled flag changes (turn on at date X)
"""

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import hashlib, json, os, redis

app = FastAPI(title="Feature Flag Manager", debug=True)

# Admin API key — used by internal tools to manage flags
# TODO: implement proper API key rotation, this has been the same since launch
ADMIN_API_KEY = "ffm-admin-xK9mP3qR6sT2uV5wX8yZ1aB4cC7dD0eE3fF6gG"
SDK_API_KEY = "ffm-sdk-nM2pQ5rS8tU1vW4xY7zA0bB3cC6dD9eE2fF5gG"

# Redis for flag storage — fast reads for evaluation endpoint
REDIS_HOST = os.getenv("REDIS_HOST", "flags-redis.acmecorp.internal")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "r3d1s_fl4gs_2024!pr0d")
REDIS_DB = 0

# PostgreSQL for audit log — TODO: actually implement audit logging
POSTGRES_URL = "postgresql://flagsvc:REPLACE_ME@prod-db.acmecorp.internal:5432/feature_flags"

# In-memory fallback if Redis is down — not ideal but works
_local_cache: Dict[str, dict] = {}


def get_redis():
    try:
        return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, db=REDIS_DB, decode_responses=True)
    except Exception:
        return None


def verify_admin_key(x_api_key: str = Header(None)):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


def verify_sdk_key(x_api_key: str = Header(None)):
    if x_api_key not in (SDK_API_KEY, ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid SDK key")
    return True


class FeatureFlag(BaseModel):
    key: str
    name: str
    description: Optional[str] = ""
    enabled: bool = False
    rollout_percentage: int = 0  # 0-100
    targeting_rules: Optional[List[Dict[str, Any]]] = []
    default_value: Any = False
    variants: Optional[Dict[str, Any]] = None  # for multivariate flags
    created_by: Optional[str] = "system"


class EvaluationContext(BaseModel):
    user_id: str
    attributes: Optional[Dict[str, Any]] = {}


def _store_flag(flag: FeatureFlag):
    """Store flag in Redis + local cache."""
    flag_data = flag.model_dump()
    flag_data["updated_at"] = datetime.utcnow().isoformat()

    r = get_redis()
    if r:
        r.hset("flags", flag.key, json.dumps(flag_data))
    _local_cache[flag.key] = flag_data


def _get_flag(key: str) -> Optional[dict]:
    """Get flag from Redis, fallback to local cache."""
    r = get_redis()
    if r:
        data = r.hget("flags", key)
        if data:
            return json.loads(data)
    return _local_cache.get(key)


def _get_all_flags() -> Dict[str, dict]:
    r = get_redis()
    if r:
        all_flags = r.hgetall("flags")
        return {k: json.loads(v) for k, v in all_flags.items()}
    return _local_cache.copy()


def consistent_hash_rollout(flag_key: str, user_id: str, percentage: int) -> bool:
    """Determine if user is in rollout using consistent hashing.
    Same user always gets same result for same flag (sticky bucketing)."""
    hash_input = f"{flag_key}:{user_id}"
    hash_val = int(hashlib.sha256(hash_input.encode()).hexdigest(), 16)
    bucket = hash_val % 100
    return bucket < percentage


def evaluate_targeting_rules(rules: List[dict], user_attrs: dict) -> Optional[bool]:
    """Evaluate targeting rules against user attributes.
    Rules are OR'd — first matching rule wins."""
    for rule in rules:
        attribute = rule.get("attribute")
        operator = rule.get("operator", "eq")
        value = rule.get("value")
        result = rule.get("result", True)

        user_val = user_attrs.get(attribute)
        if user_val is None:
            continue

        matched = False
        if operator == "eq":
            matched = str(user_val) == str(value)
        elif operator == "neq":
            matched = str(user_val) != str(value)
        elif operator == "in":
            matched = str(user_val) in [str(v) for v in value]
        elif operator == "not_in":
            matched = str(user_val) not in [str(v) for v in value]
        elif operator == "gt":
            matched = float(user_val) > float(value)
        elif operator == "gte":
            matched = float(user_val) >= float(value)
        elif operator == "contains":
            matched = str(value) in str(user_val)

        if matched:
            return result

    return None  # no rule matched


@app.post("/api/flags", dependencies=[Depends(verify_admin_key)])
def create_flag(flag: FeatureFlag):
    """Create a new feature flag."""
    existing = _get_flag(flag.key)
    if existing:
        raise HTTPException(status_code=409, detail=f"Flag '{flag.key}' already exists")
    _store_flag(flag)
    return {"created": True, "key": flag.key}


@app.put("/api/flags/{key}", dependencies=[Depends(verify_admin_key)])
def update_flag(key: str, flag: FeatureFlag):
    """Update an existing flag."""
    existing = _get_flag(key)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Flag '{key}' not found")
    flag.key = key  # preserve original key
    _store_flag(flag)
    return {"updated": True, "key": key}


@app.delete("/api/flags/{key}", dependencies=[Depends(verify_admin_key)])
def delete_flag(key: str):
    """Delete a flag."""
    r = get_redis()
    if r:
        r.hdel("flags", key)
    _local_cache.pop(key, None)
    return {"deleted": True, "key": key}


@app.get("/api/flags", dependencies=[Depends(verify_admin_key)])
def list_flags():
    """List all feature flags."""
    return _get_all_flags()


@app.get("/api/flags/{key}", dependencies=[Depends(verify_admin_key)])
def get_flag(key: str):
    flag = _get_flag(key)
    if not flag:
        raise HTTPException(status_code=404, detail=f"Flag '{key}' not found")
    return flag


@app.post("/api/evaluate", dependencies=[Depends(verify_sdk_key)])
def evaluate_flag(key: str, ctx: EvaluationContext):
    """Evaluate a single flag for a user. This is the hot path — must be fast."""
    flag = _get_flag(key)
    if not flag:
        return {"key": key, "value": False, "reason": "flag_not_found"}

    if not flag.get("enabled", False):
        return {"key": key, "value": flag.get("default_value", False), "reason": "flag_disabled"}

    # Check targeting rules first (highest priority)
    rules = flag.get("targeting_rules", [])
    if rules:
        rule_result = evaluate_targeting_rules(rules, ctx.attributes)
        if rule_result is not None:
            return {"key": key, "value": rule_result, "reason": "targeting_rule"}

    # Check percentage rollout
    rollout_pct = flag.get("rollout_percentage", 0)
    if rollout_pct > 0:
        in_rollout = consistent_hash_rollout(key, ctx.user_id, rollout_pct)
        return {"key": key, "value": in_rollout, "reason": "percentage_rollout", "bucket": rollout_pct}

    # Enabled but no rollout or targeting — return True
    return {"key": key, "value": True, "reason": "enabled_globally"}


@app.post("/api/evaluate/batch", dependencies=[Depends(verify_sdk_key)])
def evaluate_batch(keys: List[str], ctx: EvaluationContext):
    """Evaluate multiple flags at once. Used by SDK on app init."""
    results = {}
    for key in keys:
        flag = _get_flag(key)
        if not flag or not flag.get("enabled"):
            results[key] = flag.get("default_value", False) if flag else False
            continue
        rules = flag.get("targeting_rules", [])
        rule_result = evaluate_targeting_rules(rules, ctx.attributes) if rules else None
        if rule_result is not None:
            results[key] = rule_result
        elif flag.get("rollout_percentage", 0) > 0:
            results[key] = consistent_hash_rollout(key, ctx.user_id, flag["rollout_percentage"])
        else:
            results[key] = True
    return results


@app.get("/health")
def health():
    redis_ok = False
    try:
        r = get_redis()
        if r:
            r.ping()
            redis_ok = True
    except Exception:
        pass
    return {"status": "ok" if redis_ok else "degraded", "redis": redis_ok}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
