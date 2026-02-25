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
    "cloudbuild.googleapis.com" # Added to support remote builds
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

# 2. Build and Push Docker Image using Cloud Build
# This triggers whenever the Dockerfile in the same directory changes.
resource "null_resource" "docker_build_push" {
  triggers = {
    # Re-run build if the Dockerfile changes
    dockerfile_hash = filemd5("${path.module}/Dockerfile")
  }

  provisioner "local-exec" {
    command = <<EOT
      gcloud builds submit --tag us-central1-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.latency_repo.repository_id}/latency-app:latest .
    EOT
  }

  depends_on = [google_artifact_registry_repository.latency_repo]
}

# 3. Initialize Firestore Database
resource "google_firestore_database" "database" {
  name        = "latencys"
  location_id = "nam5" # Multi-region (US). Use 'eur3' for Europe.
  type        = "FIRESTORE_NATIVE"
  
  depends_on = [google_project_service.required_services]
}

# 4. Initialize the Configuration Collection
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

# 5. Initialize the Latency Logs Collection placeholder
resource "google_firestore_document" "logs_init" {
  project     = var.project_id
  database    = google_firestore_database.database.name
  collection  = "latency_logs"
  document_id = "init_marker"
  fields      = jsonencode({
    info      = { stringValue = "Collection initialized by Terraform" }
    timestamp = { serverTimestampValue = "REQUEST_TIME" }
  })
}

# 6. Fetch all available regions
data "google_compute_regions" "available" {}

# New Local variable to filter out the restricted region
locals {
  # Subtract the unwanted region from the list of all available regions
  target_regions = setsubtract(data.google_compute_regions.available.names, ["me-central2"])
}

# 7. Service Account and Permissions
resource "google_service_account" "latency_tester" {
  account_id   = "latency-tester-sa"
  display_name = "Latency Tester Service Account"
}

resource "google_project_iam_member" "firestore_access" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.latency_tester.email}"
}

# 8. Global Cloud Run Deployment
resource "google_cloud_run_v2_service" "latency_service" {
  for_each = toset(local.target_regions)

  name                = "latency-tester-${each.value}"
  location            = each.value
  deletion_protection = false

  template {
    service_account = google_service_account.latency_tester.email
    containers {
      # Points to the newly created Artifact Registry image
      image = "us-central1-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.latency_repo.repository_id}/latency-app:latest"
      ports { container_port = 8080 }
      env {
        name  = "PROJECT_ID"
        value = var.project_id

      }
      # New environment variable for the specific deployment region
      env {
        name  = "REGION"
        value = each.value
      }
    }
  }

  # Ensure the image is built and pushed before Cloud Run tries to pull it
  depends_on = [null_resource.docker_build_push]
}

# 9. IAM: Allow public pings (Required for cross-region testing)
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  for_each = google_cloud_run_v2_service.latency_service
  name     = each.value.name
  location = each.value.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# 10. Create Firestore Composite Index
# Required for: query(latency_logs).order_by("timestamp", DESC)
resource "google_firestore_index" "latency_logs_timestamp" {
  project  = var.project_id
  database = google_firestore_database.database.name

  collection = "latency_logs"

  fields {
    field_path = "timestamp"
    order      = "DESCENDING"
  }

  # Note: If you ever add filters like 'where from_region == X', 
  # you would add those fields here as well.
  
  depends_on = [google_firestore_database.database]
}

# 11. Outputs
output "firestore_console_url" {
  value = "https://console.cloud.google.com/firestore/data?project=${var.project_id}"
}

output "regions_deployed_count" {
  value = length(data.google_compute_regions.available.names)
}