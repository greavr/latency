variable "project_id" {
  type        = string
  description = "The GCP Project ID where resources will be deployed"
}

provider "google" {
  project = var.project_id
}

# 0. Enable Required GCP Services
resource "google_project_service" "required_services" {
  for_each = toset([
    "run.googleapis.com",
    "firestore.googleapis.com",
    "compute.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "storage-api.googleapis.com",
    "storage-component.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "pubsub.googleapis.com" # Added for Artifact Registry event triggering
  ])

  project                    = var.project_id
  service                    = each.key
  disable_on_destroy         = false
  disable_dependent_services = false
}

# 1. Artifact Registry Repository
resource "google_artifact_registry_repository" "latency_repo" {
  location      = "us-central1"
  repository_id = "latency-repo"
  description   = "Docker repository for latency app"
  format        = "DOCKER"

  depends_on = [google_project_service.required_services]
}

# 2. Pub/Sub Topic for Artifact Registry Events
resource "google_pubsub_topic" "gcr_topic" {
  name = "gcr" # Artifact Registry automatically publishes here if it exists
  
  depends_on = [google_project_service.required_services]
}

# 3. Cloud Build Service Account & Permissions
resource "google_service_account" "cloud_build_sa" {
  account_id   = "cloud-build-sa"
  display_name = "Custom Cloud Build Service Account"
}

resource "google_project_iam_member" "cloud_build_roles" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/storage.admin",
    "roles/artifactregistry.writer",
    "roles/iam.serviceAccountUser",
    "roles/run.admin"
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.cloud_build_sa.email}"

  depends_on = [google_service_account.cloud_build_sa]
}

# 4. Cloud Build Trigger (Deploy on Image Push)
resource "google_cloudbuild_trigger" "automated_deploy_on_image" {
  name        = "latency-app-deploy-on-image"
  description = "Deploys the latency app whenever a new image is pushed to AR"
  location    = "us-central1"
  
  service_account = google_service_account.cloud_build_sa.id

  pubsub_config {
    topic = google_pubsub_topic.gcr_topic.id
  }

  substitutions = {
    _TARGET_REGIONS = join(" ", local.target_regions)
    _IMAGE_NAME     = "$(body.message.data.tag)" 
  }

  build {
    # Set timeout to 30 minutes (1800 seconds)
    timeout = "1800s"
    
    step {
      name       = "gcr.io/google.com/cloudsdktool/cloud-sdk"
      entrypoint = "bash"
      args = [
        "-c",
        <<-EOT
        for region in $_TARGET_REGIONS; do
          echo "Deploying to $region..."
          gcloud run services update latency-tester-$region \
            --image us-central1-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.latency_repo.repository_id}/latency-app:latest \
            --region $region
        done
        EOT
      ]
    }

    options {
      logging = "CLOUD_LOGGING_ONLY"
    }
  }

  depends_on = [
    google_artifact_registry_repository.latency_repo,
    google_project_iam_member.cloud_build_roles,
    google_pubsub_topic.gcr_topic
  ]
}

# 5. Initialize Firestore Database
resource "google_firestore_database" "database" {
  name        = "latency"
  location_id = "nam5"
  type        = "FIRESTORE_NATIVE"
  
  depends_on = [google_project_service.required_services]
}

# 6. Initialize the Configuration Collection
resource "google_firestore_document" "targets_config" {
  project     = var.project_id
  database    = google_firestore_database.database.name
  collection  = "index"
  document_id = "targets"
  fields      = jsonencode({
    test_interval_seconds = { integerValue = 30 }
    urls                  = { arrayValue = { values = [] } }
  })
}

# 7. Initialize the Latency Logs Collection placeholder
resource "google_firestore_document" "logs_init" {
  project     = var.project_id
  database    = google_firestore_database.database.name
  collection  = "latency_logs"
  document_id = "init_marker"
  fields      = jsonencode({
    info      = { stringValue = "Collection initialized by Terraform" }
    timestamp = { timestampValue = timestamp() } 
  })
}

# 8. Fetch all available regions
data "google_compute_regions" "available" {}

locals {
  target_regions = setsubtract(data.google_compute_regions.available.names, ["me-central2"])
}

# 9. Service Account and Permissions for the App
resource "google_service_account" "latency_tester" {
  account_id   = "latency-sa"
  display_name = "Latency Tester Service Account"
}

resource "google_project_iam_member" "firestore_access" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.latency_tester.email}"
}

# 10. Global Cloud Run Deployment
resource "google_cloud_run_v2_service" "latency_service" {
  for_each = toset(local.target_regions)

  name                = "latency-tester-${each.value}"
  location            = each.value
  deletion_protection = false

  template {
    service_account = google_service_account.latency_tester.email
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      
      ports { container_port = 8080 }
      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = each.value
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image
    ]
  }
}

# 11. IAM: Allow public pings
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  for_each = google_cloud_run_v2_service.latency_service
  name     = each.value.name
  location = each.value.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# 12. Create Firestore Composite Index
resource "google_firestore_index" "latency_logs_timestamp" {
  project    = var.project_id
  database   = google_firestore_database.database.name
  collection = "latency_logs"

  fields {
    field_path = "REGION"
    order      = "ASCENDING"
  }

  fields {
    field_path = "timestamp"
    order      = "DESCENDING"
  }
}

# 13. Outputs
output "firestore_console_url" {
  value = "https://console.cloud.google.com/firestore/data?project=${var.project_id}"
}

output "regions_deployed_count" {
  value = length(local.target_regions)
}