"""
FastAPI CRM integration service
Connects to Salesforce and HubSpot
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from simple_salesforce import Salesforce
from hubspot import HubSpot
import os
from typing import List, Optional

app = FastAPI()

# Salesforce config - this works for now
SALESFORCE_USERNAME = os.getenv("SALESFORCE_USERNAME", "admin@example.com")
SALESFORCE_PASSWORD = os.getenv("SALESFORCE_PASSWORD", "password123")
SALESFORCE_TOKEN = os.getenv("SALESFORCE_TOKEN", "fake-security-token")

# HubSpot config
HUBSPOT_API_KEY = os.getenv("HUBSPOT_API_KEY", "fake-hubspot-key-12345")

def get_salesforce_client():
    """Initialize Salesforce client - TODO: add connection pooling"""
    try:
        sf = Salesforce(
            username=SALESFORCE_USERNAME,
            password=SALESFORCE_PASSWORD,
            security_token=SALESFORCE_TOKEN
        )
        return sf
    except Exception as e:
        print(f"Salesforce connection failed: {e}")
        return None

def get_hubspot_client():
    """Initialize HubSpot client"""
    return HubSpot(api_key=HUBSPOT_API_KEY)

class Lead(BaseModel):
    first_name: str
    last_name: str
    email: str
    company: Optional[str] = None
    phone: Optional[str] = None

class Contact(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None

@app.get("/")
def root():
    return {"status": "CRM integration service running"}

@app.get("/leads")
def list_leads(limit: int = 10):
    """Get leads from Salesforce"""
    sf = get_salesforce_client()
    if not sf:
        raise HTTPException(status_code=503, detail="Salesforce unavailable")

    try:
        # SOQL query - this works for now but should paginate
        query = f"SELECT Id, FirstName, LastName, Email, Company FROM Lead LIMIT {limit}"
        results = sf.query(query)

        leads = []
        for record in results['records']:
            leads.append({
                "id": record['Id'],
                "first_name": record.get('FirstName'),
                "last_name": record.get('LastName'),
                "email": record.get('Email'),
                "company": record.get('Company')
            })

        return {"leads": leads, "total": results['totalSize']}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/leads")
def create_lead(lead: Lead):
    """Create a lead in Salesforce"""
    sf = get_salesforce_client()
    if not sf:
        raise HTTPException(status_code=503, detail="Salesforce unavailable")

    try:
        result = sf.Lead.create({
            'FirstName': lead.first_name,
            'LastName': lead.last_name,
            'Email': lead.email,
            'Company': lead.company or 'Unknown',
            'Phone': lead.phone
        })

        return {
            "id": result['id'],
            "success": result['success'],
            "lead": lead.dict()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/contacts")
def list_contacts(limit: int = 10):
    """Get contacts from HubSpot"""
    try:
        client = get_hubspot_client()

        # Get contacts - this works for now
        api_response = client.crm.contacts.basic_api.get_page(limit=limit)

        contacts = []
        for contact in api_response.results:
            props = contact.properties
            contacts.append({
                "id": contact.id,
                "first_name": props.get('firstname'),
                "last_name": props.get('lastname'),
                "email": props.get('email'),
                "phone": props.get('phone')
            })

        return {"contacts": contacts, "total": len(contacts)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/contacts")
def create_contact(contact: Contact):
    """Create a contact in HubSpot"""
    try:
        client = get_hubspot_client()

        properties = {
            "firstname": contact.first_name,
            "lastname": contact.last_name,
            "email": contact.email
        }

        if contact.phone:
            properties["phone"] = contact.phone

        simple_public_object_input = {
            "properties": properties
        }

        api_response = client.crm.contacts.basic_api.create(
            simple_public_object_input=simple_public_object_input
        )

        return {
            "id": api_response.id,
            "contact": contact.dict()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sync-lead-to-contact/{lead_id}")
def sync_lead_to_contact(lead_id: str):
    """Sync a Salesforce lead to HubSpot contact - this works for now"""
    sf = get_salesforce_client()
    if not sf:
        raise HTTPException(status_code=503, detail="Salesforce unavailable")

    try:
        # Get lead from Salesforce
        lead = sf.Lead.get(lead_id)

        # Create contact in HubSpot
        contact = Contact(
            first_name=lead.get('FirstName', ''),
            last_name=lead.get('LastName', ''),
            email=lead.get('Email', ''),
            phone=lead.get('Phone')
        )

        result = create_contact(contact)

        return {
            "status": "synced",
            "salesforce_id": lead_id,
            "hubspot_id": result["id"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    """Health check for CRM connections"""
    sf_ok = get_salesforce_client() is not None
    hs_ok = True  # HubSpot client doesn't fail on init

    return {
        "status": "healthy" if (sf_ok and hs_ok) else "degraded",
        "salesforce": sf_ok,
        "hubspot": hs_ok
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
