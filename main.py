import time
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from firebase_client import get_firestore_client

app = FastAPI()
db = get_firestore_client()


class AgencyPayload(BaseModel):
    name: str
    address_line_one: str
    city: str
    zip_code: str
    phone_num: str
    state_code: str = "PA"
    contact_name: Optional[str] = ""
    email: Optional[str] = ""
    services_description: Optional[str] = ""
    services: list[str] = []

CACHE_TTL_SECONDS = 3600

_agency_cache = {"data": None, "timestamp": 0}


def _invalidate_cache():
    _agency_cache["data"] = None
    _agency_cache["timestamp"] = 0


def _build_firestore_doc(payload: AgencyPayload) -> dict:
    services_dict = {}
    for svc in payload.services:
        services_dict[svc] = {"has_schedule": False}

    return {
        "name": payload.name,
        "address_line_one": payload.address_line_one,
        "city": payload.city,
        "state_code": payload.state_code,
        "zip_code": payload.zip_code,
        "phone_num": payload.phone_num,
        "contact_name": payload.contact_name,
        "email": payload.email,
        "services_description": payload.services_description,
        "services": services_dict,
        "hours_of_operation": [],
    }


def _get_all_agencies():
    now = time.time()
    if _agency_cache["data"] is not None and (now - _agency_cache["timestamp"]) < CACHE_TTL_SECONDS:
        return _agency_cache["data"]

    agencies = []
    for doc in db.collection("agencies").stream():
        data = doc.to_dict()
        data["id"] = doc.id
        agencies.append(data)

    _agency_cache["data"] = agencies
    _agency_cache["timestamp"] = now
    return agencies


@app.get("/agencies/{agency_id}")
def get_agency(agency_id: str):
    for agency in _get_all_agencies():
        if agency["id"] == agency_id:
            return agency

    raise HTTPException(status_code=404, detail="Agency not found")


@app.get("/services")
def get_all_services():
    service_set = set()
    for agency in _get_all_agencies():
        services = agency.get("services", {})
        service_set.update(services.keys())

    return sorted(service_set)


@app.get("/agencies/by-service/{service_name:path}")
def get_agencies_by_service(service_name: str):
    results = []
    for agency in _get_all_agencies():
        if service_name in agency.get("services", {}):
            results.append({
                "name": agency.get("name"),
                "phone_num": agency.get("phone_num"),
                "address_line_one": agency.get("address_line_one"),
                "services_description": agency.get("services_description"),
            })

    return results


@app.get("/agencies")
def list_agencies():
    return [
        {"name": a["name"], "id": a["id"]}
        for a in _get_all_agencies()
    ]


@app.post("/agencies", status_code=201)
def create_agency(payload: AgencyPayload):
    doc_ref = db.collection("agencies").document(payload.name)
    if doc_ref.get().exists:
        raise HTTPException(status_code=409, detail="Agency already exists")

    doc_ref.set(_build_firestore_doc(payload))
    _invalidate_cache()
    return {"message": "Agency created", "name": payload.name}


@app.put("/agencies/{agency_name:path}")
def update_agency(agency_name: str, payload: AgencyPayload):
    doc_ref = db.collection("agencies").document(agency_name)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Agency not found")

    existing = doc_ref.get().to_dict()
    existing_services = existing.get("services", {})
    new_services = {}
    for svc in payload.services:
        if svc in existing_services:
            new_services[svc] = existing_services[svc]
        else:
            new_services[svc] = {"has_schedule": False}

    doc_data = _build_firestore_doc(payload)
    doc_data["services"] = new_services
    doc_data["hours_of_operation"] = existing.get("hours_of_operation", [])

    doc_ref.set(doc_data)
    _invalidate_cache()
    return {"message": "Agency updated", "name": payload.name}