package main

# Fails the CI build if the Terraform plan would create or update an IAM
# policy statement with a wildcard action AND wildcard resource together
# ("*:*" style over-privilege) — the single most common real-world IAM
# misconfiguration. Run via: conftest test tfplan.json --policy policy/

deny[msg] {
  resource := input.resource_changes[_]
  resource.type == "aws_iam_role_policy"
  change := resource.change.after
  statement := json.unmarshal(change.policy).Statement[_]
  statement.Effect == "Allow"
  contains_wildcard(statement.Action)
  contains_wildcard(statement.Resource)
  msg := sprintf("IAM policy on resource '%s' grants wildcard action AND wildcard resource — scope this down before merging", [resource.address])
}

contains_wildcard(value) {
  value == "*"
}

contains_wildcard(value) {
  value[_] == "*"
}

deny[msg] {
  resource := input.resource_changes[_]
  resource.type == "aws_iam_role_policy_attachment"
  change := resource.change.after
  endswith(change.policy_arn, "AdministratorAccess")
  msg := sprintf("resource '%s' attaches AdministratorAccess directly — use a scoped policy instead", [resource.address])
}