#!/usr/bin/env bash
# Delete the stack (and, with DELETE_IMAGES=1, the ECR repositories). Stops all charges.
#   ENV_NAME=dev ./scripts/destroy.sh
set -euo pipefail
ENV_NAME="${ENV_NAME:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STACK="trip-buddy-${ENV_NAME}"

echo "==> Deleting ${STACK}"
aws cloudformation delete-stack --region "$AWS_REGION" --stack-name "$STACK"
aws cloudformation wait stack-delete-complete --region "$AWS_REGION" --stack-name "$STACK"
echo "==> Stack deleted"

if [[ "${DELETE_IMAGES:-0}" == "1" ]]; then
  for svc in mcp_server guide_agent trip_buddy; do
    aws ecr delete-repository --region "$AWS_REGION" --repository-name "trip-buddy-${svc}" --force >/dev/null \
      && echo "==> Deleted ECR repository trip-buddy-${svc}" || true
  done
fi
