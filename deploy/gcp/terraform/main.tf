terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Local state on purpose: this manages one VM for one personal project, so
  # a remote backend (GCS bucket, Terraform Cloud) is unneeded ceremony.
  # terraform.tfstate WILL contain the secrets below in plaintext — it's
  # gitignored; never commit it, and treat it like any other secrets file.
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

resource "google_compute_address" "arogo" {
  name   = "arogo-ip"
  region = var.region
}

resource "google_compute_firewall" "arogo_web" {
  name    = "arogo-allow-web"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["arogo"]
}

resource "google_compute_instance" "arogo" {
  name         = "arogo"
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["arogo"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.arogo.address
    }
  }

  metadata_startup_script = templatefile("${path.module}/startup.sh.tpl", {
    repo_url     = var.app_repo_url
    domain       = var.domain
    secret_key   = var.secret_key
    database_url = var.database_url
    use_https    = var.use_https
  })
}
