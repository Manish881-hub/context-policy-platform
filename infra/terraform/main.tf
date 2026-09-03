terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}
variable "region" {
  description = "Region close to Bhubaneswar"
  type        = string
  default     = "asia-south1"
}
variable "image" {
  description = "Container image gcr.io/$PROJECT_ID/context-policy-platform:$COMMIT_SHA"
  type        = string
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Artifact Registry (for Docker images) — or use GCR
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "context-policy-platform"
  format        = "DOCKER"
}

# Cloud SQL Postgres (provisioning DB) — SQLite mock in demo, swap to Postgres with same adapter interface
# Commented for cost; uncomment when ready for prod Cloud SQL
# resource "google_sql_database_instance" "provisioning" {
#   name             = "provisioning-db"
#   database_version = "POSTGRES_15"
#   region           = var.region
#   settings {
#     tier = "db-f1-micro"
#     ip_configuration {
#       ipv4_enabled = false
#       private_network = google_compute_network.vpc.id
#     }
#   }
# }

# Cloud Run service — policy platform
resource "google_cloud_run_service" "api" {
  name     = "context-policy-platform"
  location = var.region

  template {
    spec {
      containers {
        image = var.image
        ports {
          container_port = 8080
        }
        env {
          name  = "PROVISIONING_DB_PATH"
          value = "/app/src/provisioning/provisioning.db"
        }
        # Example: mount Cloud SQL via Cloud SQL Auth Proxy sidecar or direct connection string via Secret Manager
        # env {
        #   name = "DATABASE_URL"
        #   value_from {
        #     secret_key_ref {
        #       name = google_secret_manager_secret.db_url.secret_id
        #       key  = "latest"
        #     }
        #   }
        # }
        resources {
          limits = {
            cpu    = "1000m"
            memory = "512Mi"
          }
        }
      }
      service_account_name = google_service_account.run_sa.email
    }
    metadata {
      annotations = {
        "autoscaling.knative.dev/minScale" = "0"
        "autoscaling.knative.dev/maxScale" = "10"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

resource "google_cloud_run_service_iam_member" "public" {
  service  = google_cloud_run_service.api.name
  location = google_cloud_run_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Service account with minimal perms (Cloud SQL Client, Secret Accessor)
resource "google_service_account" "run_sa" {
  account_id   = "context-policy-run"
  display_name = "Context Policy Cloud Run SA"
}

resource "google_project_iam_member" "run_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.run_sa.email}"
}

# Secret for any future sensitive config (WIFI_PSK never stored here — policy gates it)
# resource "google_secret_manager_secret" "db_url" {
#   secret_id = "provisioning-db-url"
#   replication { auto {} }
# }

output "cloud_run_url" {
  value = google_cloud_run_service.api.status[0].url
}
