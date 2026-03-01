import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

def get_firestore_client():
    if not firebase_admin._apps:
        # Option A: use env var path to service account
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        if cred_path:
            cred = credentials.Certificate(cred_path)
        else:
            # Option B: load from Streamlit-style secrets JSON string
            firebase_config = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
            cred = credentials.Certificate(firebase_config)

        firebase_admin.initialize_app(cred)

    return firestore.client()