import os
import time
import uuid
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.api_core import exceptions as google_exceptions
from pydantic import BaseModel

from firebase_client import get_firestore_client

app = FastAPI()
db = get_firestore_client()

# Browsers reject Access-Control-Allow-Origin: * together with credentials.
# Default to * without credentials so localhost / Vercel can call the API.
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "*").split(",")
    if o.strip()
]
_allow_all_origins = _cors_origins == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Blair county doc in service-navigator (override per environment if needed).
COUNTY_DOC_ID = os.environ.get("FIRESTORE_COUNTY_DOC_ID", "rYszDQ9QkU8hVUQhsSMz")


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
    last_audited_date: Optional[str] = None


class ServiceRenamePayload(BaseModel):
    current_name: str
    new_name: str


CACHE_TTL_SECONDS = 3600

_agency_cache = {"data": None, "timestamp": 0}


def _invalidate_cache():
    _agency_cache["data"] = None
    _agency_cache["timestamp"] = 0


def _agencies_col():
    return (
        db.collection("counties")
        .document(COUNTY_DOC_ID)
        .collection("agencies")
    )


def _normalize_audit_date(value: Optional[str]) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="last_audited_date must be YYYY-MM-DD",
        )


def _build_firestore_doc(payload: AgencyPayload) -> dict:
    services_dict = {}
    for svc in payload.services:
        services_dict[svc] = {"has_schedule": False}

    doc = {
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
    audited = _normalize_audit_date(payload.last_audited_date)
    if audited:
        doc["last_audited_date"] = audited
    return doc


def _get_all_agencies():
    now = time.time()
    if _agency_cache["data"] is not None and (now - _agency_cache["timestamp"]) < CACHE_TTL_SECONDS:
        return _agency_cache["data"]

    agencies = []
    for doc in _agencies_col().stream():
        data = doc.to_dict()
        data["id"] = doc.id
        agencies.append(data)

    _agency_cache["data"] = agencies
    _agency_cache["timestamp"] = now
    return agencies


def _name_already_used(name: str, exclude_id: Optional[str] = None) -> bool:
    for agency in _get_all_agencies():
        if agency.get("name") == name and (exclude_id is None or agency["id"] != exclude_id):
            return True
    return False


def _handle_firestore_write_error(exc: Exception) -> None:
    if isinstance(exc, google_exceptions.PermissionDenied):
        raise HTTPException(
            status_code=403,
            detail=(
                "Firestore denied this write. The configured service account needs "
                "Cloud Datastore User (or similar) on this project. "
                "Datastore Viewer / read-only accounts cannot create, update, or delete."
            ),
        ) from exc


def _service_names(agency: dict) -> list[str]:
    services = agency.get("services") or {}
    if isinstance(services, dict):
        return sorted(services.keys())
    if isinstance(services, list):
        return [str(s) for s in services]
    return []


def _iter_service_names(services) -> list[str]:
    if isinstance(services, dict):
        return [name for name in services.keys() if isinstance(name, str)]
    if isinstance(services, list):
        return [item for item in services if isinstance(item, str)]
    return []


def _with_renamed_service(services, old_name: str, new_name: str):
    """Return a copy of an agency's services with one name changed.

    Dict values (including schedule data) stay attached to the renamed key.
    Returns None when this agency does not offer the service.
    """
    if isinstance(services, dict):
        if old_name not in services:
            return None
        updated = dict(services)
        updated[new_name] = updated.pop(old_name)
        return updated
    if isinstance(services, list):
        if old_name not in services:
            return None
        return [new_name if item == old_name else item for item in services]
    return None


def _agency_details(agency: dict) -> dict:
    return {
        "id": agency.get("id"),
        "name": agency.get("name") or "",
        "address_line_one": agency.get("address_line_one") or "",
        "city": agency.get("city") or "",
        "state_code": agency.get("state_code") or "",
        "zip_code": agency.get("zip_code") or "",
        "phone_num": agency.get("phone_num") or "",
        "contact_name": agency.get("contact_name") or "",
        "email": agency.get("email") or "",
        "services": _service_names(agency),
        "services_description": agency.get("services_description") or "",
        "last_audited_date": agency.get("last_audited_date") or None,
    }


# Static / collection routes before /agencies/{agency_id} so paths like
# /agencies/by-service/... and /agencies/details are not captured as an agency id.


@app.get("/agencies")
def list_agencies():
    return [
        {"name": a["name"], "id": a["id"]}
        for a in _get_all_agencies()
    ]


@app.get("/agencies/details")
def list_agency_details():
    agencies = sorted(
        _get_all_agencies(),
        key=lambda a: (a.get("name") or "").lower(),
    )
    return [_agency_details(a) for a in agencies]


@app.get("/agencies/by-service/{service_name:path}")
def get_agencies_by_service(service_name: str):
    results = []
    for agency in _get_all_agencies():
        if service_name in agency.get("services", {}):
            results.append({
                "id": agency.get("id"),
                "name": agency.get("name"),
                "phone_num": agency.get("phone_num"),
                "address_line_one": agency.get("address_line_one"),
                "services_description": agency.get("services_description"),
            })

    return results


@app.get("/agencies/{agency_id}")
def get_agency(agency_id: str):
    try:
        snap = _agencies_col().document(agency_id).get()
    except google_exceptions.PermissionDenied as e:
        raise HTTPException(
            status_code=403,
            detail="Firestore denied read access. Check service account permissions.",
        ) from e

    if not snap.exists:
        raise HTTPException(status_code=404, detail="Agency not found")

    data = snap.to_dict()
    data["id"] = snap.id
    return data


@app.get("/services")
def get_all_services():
    service_set = set()
    for agency in _get_all_agencies():
        service_set.update(_iter_service_names(agency.get("services")))

    return sorted(service_set)


_FIRESTORE_BATCH_LIMIT = 500


@app.post("/services/rename")
def rename_service(payload: ServiceRenamePayload):
    old_name = payload.current_name
    new_name = payload.new_name.strip()
    if not isinstance(old_name, str) or not old_name:
        raise HTTPException(status_code=400, detail="Current service name is required")
    if not new_name:
        raise HTTPException(status_code=400, detail="New service name is required")
    if new_name == old_name:
        raise HTTPException(
            status_code=400,
            detail="New service name matches the current name",
        )

    try:
        snapshots = list(_agencies_col().stream())
    except google_exceptions.PermissionDenied as e:
        raise HTTPException(
            status_code=403,
            detail="Firestore denied read access. Check service account permissions.",
        ) from e

    known_names = set()
    pending = []
    for snap in snapshots:
        services = (snap.to_dict() or {}).get("services")
        known_names.update(_iter_service_names(services))
        renamed = _with_renamed_service(services, old_name, new_name)
        if renamed is not None:
            pending.append((snap.reference, renamed))

    if old_name not in known_names:
        raise HTTPException(status_code=404, detail="Service not found")
    if new_name in known_names:
        raise HTTPException(
            status_code=409,
            detail="A service with that name already exists. Choose a different name.",
        )

    updated = 0
    wrote_any = False
    try:
        for start in range(0, len(pending), _FIRESTORE_BATCH_LIMIT):
            batch = db.batch()
            chunk = pending[start : start + _FIRESTORE_BATCH_LIMIT]
            for ref, services in chunk:
                batch.update(ref, {"services": services})
            batch.commit()
            wrote_any = True
            updated += len(chunk)
    except google_exceptions.PermissionDenied as e:
        if wrote_any:
            _invalidate_cache()
        _handle_firestore_write_error(e)
    except Exception:
        if wrote_any:
            _invalidate_cache()
        raise

    _invalidate_cache()
    return {
        "message": "Service renamed",
        "current_name": old_name,
        "new_name": new_name,
        "agencies_updated": updated,
    }


@app.post("/agencies", status_code=201)
def create_agency(payload: AgencyPayload):
    if _name_already_used(payload.name):
        raise HTTPException(status_code=409, detail="Agency already exists")

    doc_id = str(uuid.uuid4())
    doc_ref = _agencies_col().document(doc_id)
    try:
        doc_ref.set(_build_firestore_doc(payload))
    except google_exceptions.PermissionDenied as e:
        _handle_firestore_write_error(e)

    _invalidate_cache()
    return {"message": "Agency created", "id": doc_id, "name": payload.name}


@app.put("/agencies/{agency_id}")
def update_agency(agency_id: str, payload: AgencyPayload):
    doc_ref = _agencies_col().document(agency_id)
    try:
        snap = doc_ref.get()
    except google_exceptions.PermissionDenied as e:
        _handle_firestore_write_error(e)

    if not snap.exists:
        raise HTTPException(status_code=404, detail="Agency not found")

    if _name_already_used(payload.name, exclude_id=agency_id):
        raise HTTPException(status_code=409, detail="Another agency already uses this name")

    existing = snap.to_dict() or {}
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

    # Clients that omit last_audited_date (mobile manage) must not wipe a stored date.
    if "last_audited_date" not in payload.model_fields_set:
        existing_date = existing.get("last_audited_date")
        if existing_date:
            doc_data["last_audited_date"] = existing_date

    try:
        doc_ref.set(doc_data)
    except google_exceptions.PermissionDenied as e:
        _handle_firestore_write_error(e)

    _invalidate_cache()
    return {"message": "Agency updated", "id": agency_id, "name": payload.name}


@app.delete("/agencies/{agency_id}")
def delete_agency(agency_id: str):
    doc_ref = _agencies_col().document(agency_id)
    try:
        snap = doc_ref.get()
    except google_exceptions.PermissionDenied as e:
        _handle_firestore_write_error(e)

    if not snap.exists:
        raise HTTPException(status_code=404, detail="Agency not found")

    try:
        doc_ref.delete()
    except google_exceptions.PermissionDenied as e:
        _handle_firestore_write_error(e)

    _invalidate_cache()
    return {"message": "Agency deleted", "id": agency_id}
