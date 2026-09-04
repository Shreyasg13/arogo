output "static_ip" {
  description = "Point your domain's A record here."
  value       = google_compute_address.arogo.address
}

output "ssh_command" {
  value = "gcloud compute ssh arogo --zone=${var.zone} --project=${var.project_id}"
}
