# AGENTS.md

## Cursor Cloud specific instructions

FastAPI backend for "Blair County Resources". Serves agency/service data from Google
Firestore. Python 3.12 with a virtualenv at `.venv` (dependencies in `requirements.txt`:
`fastapi`, `uvicorn`, `firebase-admin`, `pydantic`). There are no automated tests or lint
configs in this repo.

### Firestore credentials are required to start the server (key gotcha)
`main.py` calls `db = get_firestore_client()` at import time, so `uvicorn` will crash on
startup unless one of these is set (see `firebase_client.py`):
- `GOOGLE_APPLICATION_CREDENTIALS` — path to a service-account JSON key, or
- `FIREBASE_SERVICE_ACCOUNT` — the service-account JSON as a string.

Also set `FIRESTORE_COUNTY_DOC_ID` (defaults to the Blair county id `rYszDQ9QkU8hVUQhsSMz`).
Real Firestore access needs a service-account JSON from the project owner; the historically
used `service-navigator-ro.json` account is read-only, so create/update/delete (POST/PUT/
DELETE) return 403 with it. Credential files are gitignored and not committed.

Run the dev server (from repo root):
```
GOOGLE_APPLICATION_CREDENTIALS=<sa.json> FIRESTORE_COUNTY_DOC_ID=rYszDQ9QkU8hVUQhsSMz \
  .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Local Firestore emulator (no real credentials needed)
For self-contained dev/testing without a real service account, use the Firestore emulator
(`firebase-tools` is installed globally; Java is present). Point the app at it and use a
dummy service-account JSON (any well-formed key file works because the emulator does not
verify tokens):
```
firebase emulators:start --only firestore --project demo-blair   # host 127.0.0.1:8080
# then run uvicorn with these extra env vars:
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 GOOGLE_CLOUD_PROJECT=demo-blair \
GOOGLE_APPLICATION_CREDENTIALS=<dummy-sa.json> FIRESTORE_COUNTY_DOC_ID=rYszDQ9QkU8hVUQhsSMz \
  .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
The emulator starts empty — seed `counties/{FIRESTORE_COUNTY_DOC_ID}/agencies` docs (fields
per the `AgencyPayload` model / project rules) before search returns results. If
`firebase-tools` is missing, install with `sudo env "PATH=$PATH" npm install -g firebase-tools`.
