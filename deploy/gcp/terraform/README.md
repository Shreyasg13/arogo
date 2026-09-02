# Terraform — GCP e2-micro, one-shot deploy

`terraform apply` creates the VM, static IP, and firewall rule, then the
instance's startup script (`startup.sh.tpl`) provisions itself on first
boot — clones the repo, runs `../provision.sh`, writes `arogo.env`, installs
the systemd units and Caddyfile, starts everything. One command instead of
the manual SSH steps in `../../../DEPLOY.md`.

This does **not** create the database (Neon/Supabase — see `DEPLOY.md`) or
the domain/DNS record. Those stay manual: pick a database and a domain
first, then apply.

## One-time bootstrap (you do this — needs your own GCP login)

1. Create a GCP project (or use an existing one) and **enable billing** —
   required even to use the Always Free tier.
2. Enable the Compute Engine API:
   ```bash
   gcloud services enable compute.googleapis.com --project=YOUR_PROJECT_ID
   ```
3. Authenticate Terraform. Easiest for local use:
   ```bash
   gcloud auth application-default login
   ```
   For the GitHub Actions workflow (`.github/workflows/terraform.yml`)
   instead, create a service account and give it the `roles/compute.admin`
   role, then add its JSON key as the `GCP_SA_KEY` GitHub secret, and the
   project ID as the `GCP_PROJECT_ID` secret:
   ```bash
   gcloud iam service-accounts create arogo-terraform --project=YOUR_PROJECT_ID
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
     --member="serviceAccount:arogo-terraform@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/compute.admin"
   gcloud iam service-accounts keys create key.json \
     --iam-account="arogo-terraform@YOUR_PROJECT_ID.iam.gserviceaccount.com"
   # paste key.json's contents into the GCP_SA_KEY secret, then delete the local file
   ```

## Apply locally

```bash
cd deploy/gcp/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in real values
terraform init
terraform plan
terraform apply
```

Then point your domain's `A` record at the `static_ip` output. Caddy
issues the HTTPS cert automatically once that resolves — no separate step.

## Apply via GitHub Actions instead

`.github/workflows/terraform.yml` runs `terraform plan` automatically on
any PR touching `deploy/gcp/terraform/`, and `terraform apply` only on
manual trigger (Actions tab → "Terraform" → **Run workflow**) — applying
real cloud infrastructure never happens silently on a push. It reads
`terraform.tfvars` equivalents from repo secrets (`TF_VAR_project_id`,
`TF_VAR_app_repo_url`, `TF_VAR_domain`, `TF_VAR_secret_key`,
`TF_VAR_database_url`) plus `GCP_SA_KEY`/`GCP_PROJECT_ID` for auth — add
those under Settings → Secrets and variables → Actions before the first
run.

## Updating the app after this

The startup script only runs on first boot. For app updates afterward,
SSH in and use the "Updating" steps in `../../../DEPLOY.md`'s GCP section
— `terraform apply` won't re-deploy app code on its own (by design: it
provisions infrastructure, not continuous deploys).
