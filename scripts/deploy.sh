#!/usr/bin/env bash
# Build the 3 images, push them to ECR and deploy the CloudFormation stack.
# Used by GitHub Actions and by hand (Git Bash on Windows works).
#
#   ENV_NAME=dev ./scripts/deploy.sh
#
# Optional env vars: AWS_REGION (us-east-1), IMAGE_TAG (git SHA), LLM_PROVIDER (bedrock|openai),
#                    OPENAI_BASE_URL, OPENAI_PROJECT_ID, OPENAI_MODEL, EMBEDDINGS_PROVIDER (local),
#                    (the API key itself goes in SSM: /trip-buddy/openai-api-key)
#                    CFN_EXECUTION_ROLE_ARN, ALARM_EMAIL, DESIRED_COUNT (1)
set -euo pipefail

ENV_NAME="${ENV_NAME:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short=12 HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
STACK="trip-buddy-${ENV_NAME}"
SERVICES=(mcp_server guide_agent trip_buddy)

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
PREFIX="${REGISTRY}/trip-buddy"
cd "$(dirname "$0")/.."

echo "==> Deploying ${STACK} (tag ${IMAGE_TAG}) to ${ACCOUNT_ID}/${AWS_REGION}"

# ECR auth goes into a throwaway Docker config instead of `docker login`. On Windows,
# `docker login` always hands the token to Credential Manager (even with an empty config),
# which rejects the large ECR token with "The stub received bad data". A config that
# already holds "auths" is used as-is. Builds keep the normal config; only pushes use this.
PUSH_CONFIG="$(mktemp -d)"
trap 'rm -rf "$PUSH_CONFIG"' EXIT
ECR_AUTH="$(printf 'AWS:%s' "$(aws ecr get-login-password --region "$AWS_REGION")" | base64 | tr -d '\n')"
printf '{"auths":{"%s":{"auth":"%s"}}}' "$REGISTRY" "$ECR_AUTH" > "${PUSH_CONFIG}/config.json"
echo "==> ECR credentials ready for ${REGISTRY}"

for svc in "${SERVICES[@]}"; do
  repo="trip-buddy-${svc}"
  if ! aws ecr describe-repositories --repository-names "$repo" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "==> Creating ECR repository ${repo}"
    aws ecr create-repository --repository-name "$repo" --region "$AWS_REGION" \
      --image-scanning-configuration scanOnPush=true >/dev/null
    aws ecr put-lifecycle-policy --repository-name "$repo" --region "$AWS_REGION" --lifecycle-policy-text \
      '{"rules":[{"rulePriority":1,"description":"keep last 10","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}' >/dev/null
  fi
  echo "==> Building ${svc}"
  docker build --platform linux/amd64 -f "services/${svc}/Dockerfile" -t "${PREFIX}-${svc}:${IMAGE_TAG}" .
  docker --config "$PUSH_CONFIG" push "${PREFIX}-${svc}:${IMAGE_TAG}"
done

ROLE_ARGS=()
[[ -n "${CFN_EXECUTION_ROLE_ARN:-}" ]] && ROLE_ARGS=(--role-arn "$CFN_EXECUTION_ROLE_ARN")

echo "==> CloudFormation deploy"
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name "$STACK" \
  --template-file infra/trip-buddy-stack.yaml \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  "${ROLE_ARGS[@]}" \
  --parameter-overrides \
    EnvName="$ENV_NAME" \
    ImageRepoPrefix="$PREFIX" \
    ImageTag="$IMAGE_TAG" \
    LlmProvider="${LLM_PROVIDER:-bedrock}" \
    OpenAIBaseUrl="${OPENAI_BASE_URL:-}" \
    OpenAIProjectId="${OPENAI_PROJECT_ID:-}" \
    OpenAIModel="${OPENAI_MODEL:-openai.gpt-oss-120b}" \
    EmbeddingsProvider="${EMBEDDINGS_PROVIDER:-}" \
    DesiredCount="${DESIRED_COUNT:-1}" \
    AlarmEmail="${ALARM_EMAIL:-}" \
  --tags Project=trip-buddy Env="$ENV_NAME"

URL="$(aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='AppUrl'].OutputValue" --output text)"
echo "==> App URL: ${URL}"
[[ -n "${GITHUB_OUTPUT:-}" ]] && echo "app_url=${URL}" >> "$GITHUB_OUTPUT"

echo "==> Smoke test"
for i in $(seq 1 30); do
  if body="$(curl -sf "${URL}/health/deep")" && echo "$body" | grep -q '"status":"ok"'; then
    echo "$body"; echo "==> Healthy"; exit 0
  fi
  sleep 10
done
echo "Smoke test failed: ${URL}/health/deep did not report ok" >&2
exit 1
