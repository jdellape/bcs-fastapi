import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import ast

def get_firestore_client():
    if not firebase_admin._apps:
        # Option A: use env var path to service account
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        if cred_path:
            cred = credentials.Certificate(cred_path)
        else:
            # Option B: load from Streamlit-style secrets JSON string
            raw_secret = os.environ["FIREBASE_SERVICE_ACCOUNT"]
            try:
                firebase_config = json.loads(raw_secret)
            except json.JSONDecodeError:
                # FastAPI Cloud CLI can occasionally store dict-like text with single quotes.
                # Fall back to safe literal parsing for compatibility.
                firebase_config = ast.literal_eval(raw_secret)
                if not isinstance(firebase_config, dict):
                    raise ValueError("FIREBASE_SERVICE_ACCOUNT must be a JSON object")
            cred = credentials.Certificate(firebase_config)

        firebase_admin.initialize_app(cred)

    return firestore.client()