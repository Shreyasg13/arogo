variable "project_id" {
  description = "GCP project ID (must already exist, with billing enabled and the Compute Engine API turned on)."
  type        = string
}

variable "region" {
  description = "Must be us-west1, us-central1, or us-east1 for e2-micro Always Free eligibility."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zone within region."
  type        = string
  default     = "us-central1-a"
}

variable "machine_type" {
  type    = string
  default = "e2-micro"
}

variable "app_repo_url" {
  description = "Clone URL for your Arogo repo (the VM pulls the app + deploy/gcp/ from here on boot)."
  type        = string
}

variable "domain" {
  description = "Public domain this instance will serve, e.g. arogo.yourdomain.com. Point its DNS A record at the static IP from the 'static_ip' output after apply."
  type        = string
}

variable "secret_key" {
  description = "Flask SECRET_KEY. Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
  type        = string
  sensitive   = true
}

variable "database_url" {
  description = "Postgres connection string from Neon/Supabase (create the project there first — Terraform doesn't provision the database itself)."
  type        = string
  sensitive   = true
}
