# Latency Monitor: Multi-Region Cloud Run Testing

This project provides a serverless architecture to measure and log network latency between all Google Cloud Platform regions. It consists of a FastAPI application deployed to every available GCP region via Terraform. Each instance self-registers its endpoint in Firestore and continuously performs cross-region latency tests.

---

## Architecture Overview

* **Compute:** Google Cloud Run (Fully Managed).
* **Database:** Google Cloud Firestore (Native Mode).
* **Orchestration:** Terraform (using `for_each` across all dynamic regions).
* **Language:** Python 3.11 with FastAPI and AsyncIO.

Each instance performs two roles simultaneously:
1.  **Server:** Provides a `/ping` endpoint that returns the instance's region.
2.  **Client:** Runs a background worker that fetches the list of all active regional endpoints from Firestore and measures the Round Trip Time (RTT) to each.



---

## File Structure

* `main.py`: The FastAPI application containing the server logic, metadata discovery, and the background testing loop.
* `requirements.txt`: Python dependencies (FastAPI, Uvicorn, Firebase-Admin, HTTPX).
* `Dockerfile`: Container configuration for Cloud Run deployment.
* `main.tf`: Terraform configuration to provision the Service Account, IAM permissions, and Cloud Run services globally.

---

## Local Development Setup

To run the application locally for testing or debugging, follow these steps using `virtualenv`.

### 1. Prerequisites
* Python 3.11 or higher.
* A Google Cloud Service Account JSON key with **Cloud Datastore User** permissions (to access Firestore).
* Enable the GCP APIS
```
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    firestore.googleapis.com \
    compute.googleapis.com
```

### 2. Environment Setup
```bash
# Install virtualenv if you haven't already
pip install virtualenv

# Create the virtual environment
virtualenv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
.\venv\Scripts\activate

# Install dependencies
pip install -r app/requirements.txt

# Run the App Locally
cd app/
uvicorn main:app --host 0.0.0.0 --port 8080
```

### 3. Build Docker Image
# 1. Configure Docker to authenticate with GCP
`gcloud auth configure-docker`

# 2. Build the image
`docker build -t us-docker.pkg.dev/$YOUR_PROJECT_ID/latency/latency-app:latest .`

# 3. Push to Google Container Registry
`docker push us-docker.pkg.dev/$YOUR_PROJECT_ID/latency/latency-app:latest`

### 4. Push to GCR
# Replace YOUR_PROJECT_ID with your actual GCP Project ID
```
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/latency-app:latest .
```

### 5. Deploy With Terraform
```
terraform init
terraform apply -var="project_id=YOUR_PROJECT_ID"
```