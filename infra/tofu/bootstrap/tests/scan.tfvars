# Synthetic scanner inputs only. Never use these for a real Azure plan/apply.
environment                  = "dev"
location                     = "westeurope"
subscription_id              = "11111111-1111-4111-8111-111111111111"
tenant_id                    = "22222222-2222-4222-8222-222222222222"
bootstrap_operator_object_id = "99999999-9999-4999-8999-999999999999"
bootstrap_phase              = "state"
bootstrap_allowed_ip_ranges  = ["203.0.113.10"]
enable_github_oidc           = true
