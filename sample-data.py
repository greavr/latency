import firebase_admin
from firebase_admin import credentials, firestore
import random
from datetime import datetime, timezone

# Initialize Firestore
if not firebase_admin._apps:
    firebase_admin.initialize_app()

# Matches your specific database ID 'latency'
db = firestore.client(database_id="latency")

GCP_REGIONS = [
    "africa-south1", "asia-east1", "asia-east2", "asia-northeast1", "asia-northeast2",
    "asia-northeast3", "asia-south1", "asia-south2", "asia-southeast1",
    "asia-southeast2","asia-southeast3", "australia-southeast1", "australia-southeast2",
    "europe-central2", "europe-north1", "europe-north2","europe-southwest1",
    "europe-west1", "europe-west2", "europe-west3", "europe-west4",
    "europe-west6", "europe-west8", "europe-west9", "europe-west10",
    "europe-west12", "me-central1", "me-central2", "me-west1",
    "northamerica-northeast1", "northamerica-northeast2","northamerica-south1",
    "southamerica-east1", "southamerica-west1", "us-central1", "us-east1", 
    "us-east4", "us-east5", "us-south1", "us-west1", "us-west2", "us-west3", "us-west4"
]

def estimate_latency(src, dst):
    """Generates realistic latency based on region prefixes."""
    prefixes = {
        'us': 1, 'northamerica': 1, 'southamerica': 3,
        'europe': 2, 'me': 3, 'africa': 4, 'asia': 4, 'australia': 5
    }
    s_p = src.split('-')[0]
    d_p = dst.split('-')[0]
    
    if s_p == d_p:
        return random.uniform(8.0, 40.0)  # Intra-continental
    
    # Calculate rough distance jump
    diff = abs(prefixes.get(s_p, 3) - prefixes.get(d_p, 3))
    base = 80.0 + (diff * 60.0)
    return base + random.uniform(-10.0, 20.0)

def commit_batch(docs):
    """Helper to handle Firestore's 500-limit per batch."""
    batch = db.batch()
    for ref, data in docs:
        batch.set(ref, data)
    batch.commit()
    print(f"Committed {len(docs)} records...")

def seed_full_mesh():
    all_docs = []
    collection_ref = db.collection("latency_logs")
    
    print(f"Starting full mesh generation for {len(GCP_REGIONS)} regions...")
    
    for src in GCP_REGIONS:
        for dst in GCP_REGIONS:
            if src == dst:
                continue
            
            latency = estimate_latency(src, dst)
            doc_data = {
                "from_region": src,
                "to_region": dst,
                "latency_ms": round(latency, 2),
                "timestamp": datetime.now(timezone.utc)
            }
            
            # Add to our local list for batching
            all_docs.append((collection_ref.document(), doc_data))
            
            # Commit in chunks of 450 to stay under the 500 limit
            if len(all_docs) >= 450:
                commit_batch(all_docs)
                all_docs = []

    # Commit remaining
    if all_docs:
        commit_batch(all_docs)

    print("\n✅ Full Mesh Complete. 1,806 pairs generated.")

if __name__ == "__main__":
    seed_full_mesh()