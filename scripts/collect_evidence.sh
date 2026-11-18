#!/usr/bin/env bash
# Snapshot of the live AWS deployment as markdown (account id redacted).
#   ENV_NAME=dev ./scripts/collect_evidence.sh > docs/evidence/aws-deployment.md
set -euo pipefail
export MSYS_NO_PATHCONV=1
ENV_NAME="${ENV_NAME:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STACK="trip-buddy-${ENV_NAME}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
redact() { sed "s/${ACCOUNT_ID}/<account-id>/g"; }
section() { printf '\n## %s\n\n```text\n' "$1"; }
end() { printf '```\n'; }
aws_() { aws --region "$AWS_REGION" "$@"; }

URL="$(aws_ cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='AppUrl'].OutputValue" --output text)"

printf '# Live AWS deployment: %s\n\nCaptured %s UTC from the AWS CLI by `scripts/collect_evidence.sh`.\n' \
  "$STACK" "$(date -u +'%Y-%m-%d %H:%M')"

section "CloudFormation stack"
aws_ cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].{Status:StackStatus,Updated:LastUpdatedTime,Outputs:Outputs[].[OutputKey,OutputValue]}" --output yaml | redact
end

section "Resources created by the stack ($(aws_ cloudformation describe-stack-resources --stack-name "$STACK" --query 'length(StackResources)' --output text) total)"
aws_ cloudformation describe-stack-resources --stack-name "$STACK" \
  --query "StackResources[].[ResourceType,LogicalResourceId,ResourceStatus]" --output text | sort | column -t
end

section "ECS Fargate services"
aws_ ecs describe-services --cluster "$STACK" --services trip-buddy mcp guide \
  --query "services[].[serviceName,status,runningCount,desiredCount,launchType,deployments[0].rolloutState]" --output table
end

section "Cloud Map private DNS (service discovery)"
NS_ID="$(aws_ servicediscovery list-namespaces --query "Namespaces[?Name=='${STACK}.local'].Id" --output text)"
echo "namespace: ${STACK}.local"
aws_ servicediscovery list-services --filters "Name=NAMESPACE_ID,Values=${NS_ID},Condition=EQ" \
  --query "Services[].[Name,InstanceCount]" --output text | awk '{print "  " $1 ".'"${STACK}"'.local  instances=" $2}'
end

section "DynamoDB tables"
for t in destinations sessions; do
  aws_ dynamodb describe-table --table-name "${STACK}-${t}" \
    --query "Table.[TableName,TableStatus,BillingModeSummary.BillingMode,ItemCount]" --output text
done
aws_ dynamodb describe-time-to-live --table-name "${STACK}-sessions" \
  --query "TimeToLiveDescription.[AttributeName,TimeToLiveStatus]" --output text | sed 's/^/sessions TTL: /'
end

section "Secret storage (SSM Parameter Store, value never printed)"
aws_ ssm describe-parameters --parameter-filters "Key=Name,Values=/trip-buddy/openai-api-key" \
  --query "Parameters[].[Name,Type]" --output text
end

section "GET ${URL}/health/deep"
curl -s "${URL}/health/deep"; echo
end

section "CloudWatch alarms"
aws_ cloudwatch describe-alarms --alarm-name-prefix "$STACK" \
  --query "MetricAlarms[].[AlarmName,StateValue,MetricName,Threshold]" --output table
end

section "Custom metric TripBuddy/AgentLatencyMs (from JSON logs, last 3 hours)"
aws_ cloudwatch get-metric-statistics --namespace TripBuddy --metric-name AgentLatencyMs \
  --dimensions Name=Service,Value=trip_buddy --start-time "$(date -u -d '-3 hours' +%FT%TZ)" \
  --end-time "$(date -u +%FT%TZ)" --period 10800 --statistics SampleCount Average Maximum \
  --query "Datapoints[].{requests:SampleCount,avg_ms:Average,max_ms:Maximum}" --output table
end

section "Structured logs: one agent turn (API) and the MCP tool calls it made"
aws_ logs filter-log-events --log-group-name "/ecs/${STACK}/trip_buddy" --filter-pattern '{ $.msg = "chat" }' \
  --start-time "$(( ($(date +%s) - 10800) * 1000 ))" --query "events[-2:].message" --output text | tr '\t' '\n'
aws_ logs filter-log-events --log-group-name "/ecs/${STACK}/mcp_server" --filter-pattern '{ $.msg = "tool_call" }' \
  --start-time "$(( ($(date +%s) - 10800) * 1000 ))" --query "events[-4:].message" --output text | tr '\t' '\n'
end
