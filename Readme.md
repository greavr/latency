# Latency Monitor: Multi-Region Cloud Run Testing

This project provides a serverless architecture to measure and log network latency between all Google Cloud Platform regions. It consists of a FastAPI application deployed to every available GCP region via Terraform. Each instance self-registers its endpoint in Firestore and continuously performs cross-region latency tests.

---

## Architecture Overview



* **Compute:** Google Cloud Run (Fully Managed).
* **Database:** Google Cloud Firestore (Native Mode).
* **Orchestration:** Terraform (using `for_each` across all dynamic regions).
* **CI/CD Pipeline:** Google Artifact Registry -> Pub/Sub (`gcr` topic) -> Cloud Build Trigger.
* **Language:** Python 3.11 with FastAPI and AsyncIO.

Each instance performs two roles simultaneously:
1.  **Server:** Provides a `/ping` endpoint that returns the instance's region.
2.  **Client:** Runs a background worker that fetches the list of all active regional endpoints from Firestore and measures the Round Trip Time (RTT) to each.

---

## File Structure

* `main.py`: The FastAPI application containing the server logic, metadata discovery, and the background testing loop.
* `requirements.txt`: Python dependencies (FastAPI, Uvicorn, Firebase-Admin, HTTPX).
* `Dockerfile`: Container configuration for Cloud Run deployment.
* `main.tf`: Terraform configuration to provision the Artifact Registry, Pub/Sub topic, Cloud Build Trigger, IAM permissions, and Cloud Run services globally.

---

## 1. Local Development Setup

To run the application locally for testing or debugging, follow these steps using `virtualenv`.

### Prerequisites
* Python 3.11 or higher.
* A Google Cloud Service Account JSON key with **Cloud Datastore User** permissions (to access Firestore).
* Enable the necessary GCP APIs (Terraform will also attempt to do this, but doing it beforehand prevents timing issues):

```bash
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    firestore.googleapis.com \
    compute.googleapis.com \
    artifactregistry.googleapis.com \
    pubsub.googleapis.com
```

### Environment Setup

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

---

## 2. Deploy Infrastructure (Terraform)

Before you can push your Docker image, you must deploy the underlying infrastructure. This creates the Artifact Registry repository, sets up the Pub/Sub trigger, and deploys "placeholder" Cloud Run services globally.

```bash
# Initialize Terraform workspace
terraform init

# Review and apply the infrastructure changes
terraform apply -var="project_id=YOUR_PROJECT_ID"
```

---

## 3. Trigger a Deployment (Build & Push)

Once Terraform has successfully created the `latency-repo` Artifact Registry repository and the Cloud Build trigger, pushing a new Docker image will automatically trigger a global rollout to all your Cloud Run services.

### Authenticate Docker
Configure Docker to authenticate with your specific Artifact Registry region:

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

### Build the Image
Build your Docker image locally, tagging it with the Artifact Registry path:

```bash
docker build -t us-central1-docker.pkg.dev/$PROJECT_ID/latency-repo/latency-app:latest .
```

### Push the Image
Push the image to Artifact Registry. Once the upload completes, Artifact Registry will publish a message to the `gcr` Pub/Sub topic, which Cloud Build will intercept and use to deploy the app to all regions.

```bash
docker push us-central1-docker.pkg.dev/$YOUR_$PROJECT_ID/latency-repo/latency-app:latest
```

> **Note:** You can view the progress of your deployment by visiting the **Cloud Build** page in the Google Cloud Console.