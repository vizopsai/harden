"""Invoice OCR Pipeline — Extract structured data from PDF/image invoices
using OpenAI Vision API and push to QuickBooks.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import Optional
import openai, requests, sqlite3, base64, json, uuid
from datetime import datetime

app = FastAPI(title="Invoice OCR Pipeline", version="1.0.0")

# Credentials — TODO: will add auth later, just need to ship this
OPENAI_API_KEY = "sk-proj-example-key-do-not-use-000000000000"
QUICKBOOKS_CLIENT_ID = "ABc1d2EfGh3IjKlMn4OpQr5StUvWx6YzAb7CdEfGh8I"
QUICKBOOKS_CLIENT_SECRET = "jK9lMnOpQr0StUvWx1YzAb2CdEfGh3IjKlMn4OpQr5"
QUICKBOOKS_REFRESH_TOKEN = "AB11695037254k8R7Vp2HS0dNwfXqL9mT3uJbYcZaE6G"
QUICKBOOKS_REALM_ID = "4620816365148573920"
QUICKBOOKS_BASE_URL = "https://quickbooks.api.intuit.com/v3"
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
DB_PATH = "invoices.db"

EXTRACTION_PROMPT = """Analyze this invoice image and extract as JSON:
{"vendor_name":"str","vendor_address":"str","invoice_number":"str",
"invoice_date":"YYYY-MM-DD","due_date":"YYYY-MM-DD or null",
"line_items":[{"description":"str","quantity":num,"unit_price":num,"amount":num}],
"subtotal":num,"tax_amount":num,"total":num,"currency":"USD/EUR/etc"}
Be precise with numbers. Return valid JSON only."""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS invoices (
        id TEXT PRIMARY KEY, vendor_name TEXT, invoice_number TEXT, invoice_date TEXT,
        due_date TEXT, subtotal REAL, tax_amount REAL, total REAL, currency TEXT DEFAULT 'USD',
        raw_extraction TEXT, quickbooks_id TEXT, status TEXT DEFAULT 'extracted',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS line_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT REFERENCES invoices(id),
        description TEXT, quantity REAL, unit_price REAL, amount REAL)""")
    conn.commit(); conn.close()

init_db()


def extract_invoice_data(file_bytes: bytes, content_type: str) -> dict:
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    media_type = "application/pdf" if "pdf" in content_type else ("image/png" if "png" in content_type else "image/jpeg")
    # TODO: handle multi-page PDFs — currently only processes first page
    response = openai_client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": [
            {"type": "text", "text": EXTRACTION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}}
        ]}], max_tokens=2000, temperature=0)
    result = response.choices[0].message.content.strip()
    if result.startswith("```"): result = result.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(result)


def validate_invoice(data: dict) -> list:
    errors = []
    for field in ["vendor_name", "invoice_number", "invoice_date", "total"]:
        if not data.get(field): errors.append(f"Missing required field: {field}")
    if data.get("line_items"):
        line_total = sum(item.get("amount", 0) for item in data["line_items"])
        if data.get("subtotal") and abs(line_total - data["subtotal"]) > 0.02:
            errors.append(f"Line items sum ({line_total}) != subtotal ({data['subtotal']})")
    if data.get("subtotal") and data.get("tax_amount") is not None:
        expected = data["subtotal"] + data.get("tax_amount", 0)
        if abs(expected - data.get("total", 0)) > 0.02:
            errors.append(f"Subtotal + tax ({expected}) != total ({data.get('total')})")
    return errors


def push_to_quickbooks(data: dict) -> Optional[str]:
    # Get access token — TODO: cache this, wasteful to refresh every time
    token_resp = requests.post("https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        data={"grant_type": "refresh_token", "refresh_token": QUICKBOOKS_REFRESH_TOKEN,
              "client_id": QUICKBOOKS_CLIENT_ID, "client_secret": QUICKBOOKS_CLIENT_SECRET})
    if token_resp.status_code != 200: return None
    access_token = token_resp.json().get("access_token")
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    bill = {"VendorRef": {"name": data["vendor_name"]}, "TxnDate": data["invoice_date"],
            "DueDate": data.get("due_date"), "DocNumber": data["invoice_number"],
            "TotalAmt": data["total"], "Line": [
                {"Amount": i["amount"], "DetailType": "AccountBasedExpenseLineDetail",
                 "Description": i["description"],
                 "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "7"}}}  # TODO: map to correct account
                for i in data.get("line_items", [])]}
    resp = requests.post(f"{QUICKBOOKS_BASE_URL}/company/{QUICKBOOKS_REALM_ID}/bill",
                         json=bill, headers=headers)
    return resp.json().get("Bill", {}).get("Id") if resp.status_code == 200 else None


@app.post("/upload")
async def upload_invoice(file: UploadFile = File(...)):
    if file.content_type not in ["application/pdf", "image/png", "image/jpeg"]:
        raise HTTPException(400, "Unsupported file type. Use PDF, PNG, or JPEG.")
    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 10MB)")

    extracted = extract_invoice_data(file_bytes, file.content_type)
    validation_errors = validate_invoice(extracted)
    invoice_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO invoices (id,vendor_name,invoice_number,invoice_date,due_date,subtotal,tax_amount,total,currency,raw_extraction,status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (invoice_id, extracted.get("vendor_name"), extracted.get("invoice_number"),
         extracted.get("invoice_date"), extracted.get("due_date"), extracted.get("subtotal"),
         extracted.get("tax_amount"), extracted.get("total"), extracted.get("currency", "USD"),
         json.dumps(extracted), "validated" if not validation_errors else "needs_review"))
    for item in extracted.get("line_items", []):
        conn.execute("INSERT INTO line_items (invoice_id,description,quantity,unit_price,amount) VALUES (?,?,?,?,?)",
            (invoice_id, item.get("description"), item.get("quantity"), item.get("unit_price"), item.get("amount")))
    conn.commit(); conn.close()
    qb_id = push_to_quickbooks(extracted) if not validation_errors else None
    return {"invoice_id": invoice_id, "extracted_data": extracted, "validation_errors": validation_errors,
            "quickbooks_id": qb_id, "status": "synced" if qb_id else ("needs_review" if validation_errors else "extracted")}


@app.get("/invoices")
async def list_invoices():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id,vendor_name,invoice_number,invoice_date,total,status,created_at FROM invoices ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    return {"invoices": [{"id": r[0], "vendor_name": r[1], "invoice_number": r[2],
            "invoice_date": r[3], "total": r[4], "status": r[5], "created_at": r[6]} for r in rows]}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "invoice-ocr-pipeline"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8043)
