# CloudWatch Alarms

## Overview

This document defines the CloudWatch alarm strategy for the ALB Observability Automation system, including alarm configurations, escalation policies, and response procedures.

## Table of Contents

- [Alarm Philosophy](#alarm-philosophy)
- [Critical Alarms](#critical-alarms)
- [Warning Alarms](#warning-alarms)
- [Cost Alarms](#cost-alarms)
- [Alarm Actions](#alarm-actions)
- [SNS Topics](#sns-topics)
- [Alarm Creation Scripts](#alarm-creation-scripts)
- [Runbooks](#runbooks)

---

## Alarm Philosophy

### Principles

1. **Alert on Symptoms, Not Causes**: Focus on user-impactful failures
2. **Actionable Alarms Only**: Every alarm must have a clear response action
3. **Appropriate Severity**: Critical alarms page on-call, warnings send email
4. **Reduce False Positives**: Tune thresholds based on historical data
5. **Test Regularly**: Verify alarms trigger correctly

### Severity Levels

| Severity | Response Time | Notification | Example |
|----------|--------------|--------------|---------|
| **P0 (Critical)** | 15 minutes | PagerDuty + SMS | Lambda errors > 3 in 5 minutes |
| **P1 (High)** | 1 hour | PagerDuty + Email | Lambda duration > 240 seconds |
| **P2 (Medium)** | 4 hours | Email | Memory utilization > 90% |
| **P3 (Low)** | 24 hours | Email | Athena cost spike |

---

## Critical Alarms

### 1. Lambda Function Errors

**Description**: Lambda invocation fails with an unhandled exception

**Condition**: Errors > 1 in 5 minutes

**Rationale**: Any error indicates report generation failed (daily SLO violation)

**AWS CLI**:
```bash
aws cloudwatch put-metric-alarm \
  --alarm-name alb-status-report-errors-critical \
  --alarm-description \"ALB Lambda function errors\" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=alb-status-report \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:critical-alerts \
  --treat-missing-data notBreaching
```

**Response Action**: Page on-call engineer immediately

**Runbook**: [Lambda Failure Runbook](#lambda-failure-runbook)

---

### 2. Lambda Function Timeouts

**Description**: Lambda execution exceeds 300-second timeout

**Condition**: Duration > 240000 ms (240 seconds)

**Rationale**: Approaching timeout indicates Athena query slowness or code issue

**AWS CLI**:
```bash
aws cloudwatch put-metric-alarm \
  --alarm-name alb-status-report-timeout-warning \
  --alarm-description \"ALB Lambda approaching timeout\" \
  --metric-name Duration \
  --namespace AWS/Lambda \
  --statistic Maximum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 240000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=alb-status-report \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:high-priority-alerts \
  --treat-missing-data notBreaching
```

**Response Action**: Investigate Athena query performance

**Runbook**: [Timeout Investigation Runbook](#timeout-investigation-runbook)

---

### 3. Lambda Throttling

**Description**: Lambda invocation throttled due to concurrency limits

**Condition**: Throttles > 0

**Rationale**: Throttling prevents report generation

**AWS CLI**:
```bash
aws cloudwatch put-metric-alarm \
  --alarm-name alb-status-report-throttles \
  --alarm-description \"ALB Lambda function throttled\" \
  --metric-name Throttles \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 0 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=alb-status-report \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:critical-alerts
```

**Response Action**: Increase reserved concurrency or investigate concurrent executions

**Runbook**: [Throttling Runbook](#throttling-runbook)

---

### 4. No Invocations (Missing Report)

**Description**: Lambda not invoked when expected

**Condition**: Invocations = 0 in 25 hours (daily + buffer)

**Rationale**: Daily report generation expected; 0 invocations = missed execution

**AWS CLI**:
```bash
aws cloudwatch put-metric-alarm \
  --alarm-name alb-status-report-missing-invocation \
  --alarm-description \"ALB Lambda not invoked (daily report missing)\" \
  --metric-name Invocations \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 90000 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator LessThanThreshold \
  --dimensions Name=FunctionName,Value=alb-status-report \
  --alarm-actions arn:aws:sns:us-east-1:123456789012:critical-alerts \
  --treat-missing-data breaching
```

**Response Action**: Check EventBridge schedule and manually trigger Lambda

**Runbook**: [Missing Invocation Runbook](#missing-invocation-runbook)

---

## Warning Alarms

### 5. High Lambda Duration (p95)

**Description**: 95th percentile duration exceeds target

**Condition**: p95 Duration > 180000 ms (180 seconds)

**Rationale**: Performance degradation; not yet critical but needs investigation

**CloudFormation**:
```yaml
LambdaDurationP95Alarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    AlarmName: alb-status-report-duration-p95-warning
    AlarmDescription: ALB Lambda p95 duration exceeds target
    MetricName: Duration
    Namespace: AWS/Lambda
    Statistic: p95
    Period: 300
    EvaluationPeriods: 2
    Threshold: 180000
    ComparisonOperator: GreaterThanThreshold
    Dimensions:
      - Name: FunctionName
        Value: alb-status-report
    AlarmActions:
      - !Ref MediumPriorityAlertsTopic
    TreatMissingData: notBreaching
```

**Response Action**: Review recent changes, optimize Athena queries

---

### 6. High Memory Utilization

**Description**: Lambda memory usage consistently high

**Condition**: Memory utilization > 90%

**Rationale**: Risk of OOM errors; may need memory increase

**Log Metric Filter** (extract memory from logs):
```bash
# Create metric filter from REPORT log lines\naws logs put-metric-filter \\\n  --log-group-name /aws/lambda/alb-status-report \\\n  --filter-name MemoryUtilization \\\n  --filter-pattern '[report_type=\"REPORT\", request_id, duration_label=\"Duration:\", duration, duration_unit, billed_label=\"Billed\", billed_duration, billed_unit, memory_label=\"Memory\", memory_size, memory_unit, max_label=\"Max\", max_memory, max_unit]' \\\n  --metric-transformations \\\n    metricName=MemoryUtilization,\\\n    metricNamespace=ALB/ObservabilityAutomation,\\\n    metricValue='($max_memory/$memory_size)*100',\\\n    unit=Percent\n\n# Create alarm on metric\naws cloudwatch put-metric-alarm \\\n  --alarm-name alb-status-report-memory-warning \\\n  --alarm-description \"ALB Lambda high memory utilization\" \\\n  --metric-name MemoryUtilization \\\n  --namespace ALB/ObservabilityAutomation \\\n  --statistic Average \\\n  --period 300 \\\n  --evaluation-periods 2 \\\n  --threshold 90 \\\n  --comparison-operator GreaterThanThreshold \\\n  --alarm-actions arn:aws:sns:us-east-1:123456789012:medium-priority-alerts\n```

**Response Action**: Increase Lambda memory allocation

---

### 7. Empty Report Generated

**Description**: Report contains zero data points (all APIs = 0 requests)

**Condition**: Custom metric `EmptyReportGenerated` > 0

**Rationale**: Indicates data pipeline issue (ALB logs missing or Athena query failed)

**Custom Metric** (published from Lambda):
```python\n# In Lambda handler\nif total_requests == 0:\n    publish_custom_metric(\"EmptyReportGenerated\", 1)\n```\n\n**Alarm**:\n```bash\naws cloudwatch put-metric-alarm \\\n  --alarm-name alb-status-report-empty-data \\\n  --alarm-description \"ALB report generated with zero data\" \\\n  --metric-name EmptyReportGenerated \\\n  --namespace ALB/ObservabilityAutomation \\\n  --statistic Sum \\\n  --period 86400 \\\n  --evaluation-periods 1 \\\n  --threshold 0 \\\n  --comparison-operator GreaterThanThreshold \\\n  --alarm-actions arn:aws:sns:us-east-1:123456789012:medium-priority-alerts\n```

**Response Action**: Verify ALB logging enabled, check Glue table partitions

---

## Cost Alarms

### 8. Athena Data Scanned Spike

**Description**: Athena scans more data than expected

**Condition**: DataScannedInBytes > 50 GB in 1 day

**Rationale**: Cost control; unexpected data scan indicates query inefficiency

**Custom Metric** (published from Lambda):
```python\nquery_stats = athena.get_query_execution(QueryExecutionId=qid)\ndata_scanned_bytes = query_stats['Statistics']['DataScannedInBytes']\ndata_scanned_gb = data_scanned_bytes / (1024 ** 3)\npublish_custom_metric(\"AthenaDataScannedGB\", data_scanned_gb, \"Gigabytes\")\n```\n\n**Alarm**:\n```bash\naws cloudwatch put-metric-alarm \\\n  --alarm-name alb-status-report-athena-cost-spike \\\n  --alarm-description \"Athena data scanned exceeds budget\" \\\n  --metric-name AthenaDataScannedGB \\\n  --namespace ALB/ObservabilityAutomation \\\n  --statistic Sum \\\n  --period 86400 \\\n  --evaluation-periods 1 \\\n  --threshold 50 \\\n  --comparison-operator GreaterThanThreshold \\\n  --alarm-actions arn:aws:sns:us-east-1:123456789012:cost-alerts\n```\n\n**Response Action**: Review query, enable partition projection, convert to Parquet\n\n---\n\n### 9. Lambda Cost Budget Exceeded

**Description**: Monthly Lambda costs exceed budget\n\n**Condition**: Monthly Lambda costs > $10\n\n**AWS Budgets** (not CloudWatch Alarms):\n```bash\naws budgets create-budget \\\n  --account-id 123456789012 \\\n  --budget file://lambda-budget.json\n```\n\n**lambda-budget.json**:\n```json\n{\n  \"BudgetName\": \"alb-observability-lambda-budget\",\n  \"BudgetLimit\": {\n    \"Amount\": \"10\",\n    \"Unit\": \"USD\"\n  },\n  \"TimeUnit\": \"MONTHLY\",\n  \"BudgetType\": \"COST\",\n  \"CostFilters\": {\n    \"Service\": [\"AWS Lambda\"],\n    \"TagKeyValue\": [\"Project$ALBObservability\"]\n  }\n}\n```\n\n---\n\n## Alarm Actions\n\n### SNS Topics\n\nCreate SNS topics for different severity levels:\n\n**Critical Alerts** (pages on-call):\n```bash\naws sns create-topic --name critical-alerts\naws sns subscribe \\\n  --topic-arn arn:aws:sns:us-east-1:123456789012:critical-alerts \\\n  --protocol email \\\n  --notification-endpoint oncall@example.com\n\n# Integrate with PagerDuty\naws sns subscribe \\\n  --topic-arn arn:aws:sns:us-east-1:123456789012:critical-alerts \\\n  --protocol https \\\n  --notification-endpoint https://events.pagerduty.com/integration/...\n```\n\n**High Priority Alerts**:\n```bash\naws sns create-topic --name high-priority-alerts\naws sns subscribe \\\n  --topic-arn arn:aws:sns:us-east-1:123456789012:high-priority-alerts \\\n  --protocol email \\\n  --notification-endpoint devops-team@example.com\n```\n\n**Medium Priority Alerts**:\n```bash\naws sns create-topic --name medium-priority-alerts\naws sns subscribe \\\n  --topic-arn arn:aws:sns:us-east-1:123456789012:medium-priority-alerts \\\n  --protocol email \\\n  --notification-endpoint devops-alerts@example.com\n```\n\n---\n\n## Alarm Creation Scripts\n\n### Terraform Example\n\n```hcl\nresource \"aws_cloudwatch_metric_alarm\" \"lambda_errors\" {\n  alarm_name          = \"alb-status-report-errors-critical\"\n  alarm_description   = \"ALB Lambda function errors\"\n  comparison_operator = \"GreaterThanThreshold\"\n  evaluation_periods  = 1\n  metric_name         = \"Errors\"\n  namespace           = \"AWS/Lambda\"\n  period              = 300\n  statistic           = \"Sum\"\n  threshold           = 1\n  treat_missing_data  = \"notBreaching\"\n\n  dimensions = {\n    FunctionName = \"alb-status-report\"\n  }\n\n  alarm_actions = [\n    aws_sns_topic.critical_alerts.arn\n  ]\n\n  tags = {\n    Environment = \"production\"\n    ManagedBy   = \"terraform\"\n  }\n}\n```\n\n### Bash Script (All Alarms)\n\n```bash\n#!/bin/bash\n# create-alarms.sh\n\nFUNCTION_NAME=\"alb-status-report\"\nREGION=\"us-east-1\"\nCRITICAL_TOPIC=\"arn:aws:sns:us-east-1:123456789012:critical-alerts\"\nHIGH_TOPIC=\"arn:aws:sns:us-east-1:123456789012:high-priority-alerts\"\nMEDIUM_TOPIC=\"arn:aws:sns:us-east-1:123456789012:medium-priority-alerts\"\n\n# Critical: Lambda Errors\naws cloudwatch put-metric-alarm \\\n  --alarm-name ${FUNCTION_NAME}-errors-critical \\\n  --metric-name Errors \\\n  --namespace AWS/Lambda \\\n  --statistic Sum \\\n  --period 300 \\\n  --evaluation-periods 1 \\\n  --threshold 1 \\\n  --comparison-operator GreaterThanThreshold \\\n  --dimensions Name=FunctionName,Value=$FUNCTION_NAME \\\n  --alarm-actions $CRITICAL_TOPIC \\\n  --region $REGION\n\n# High: Lambda Timeout Warning\naws cloudwatch put-metric-alarm \\\n  --alarm-name ${FUNCTION_NAME}-timeout-warning \\\n  --metric-name Duration \\\n  --namespace AWS/Lambda \\\n  --statistic Maximum \\\n  --period 300 \\\n  --evaluation-periods 1 \\\n  --threshold 240000 \\\n  --comparison-operator GreaterThanThreshold \\\n  --dimensions Name=FunctionName,Value=$FUNCTION_NAME \\\n  --alarm-actions $HIGH_TOPIC \\\n  --region $REGION\n\n# Add remaining alarms...\n\necho \"Alarms created successfully\"\n```\n\n---\n\n## Runbooks\n\n### Lambda Failure Runbook\n\n**Alarm**: `alb-status-report-errors-critical`\n\n**Steps**:\n1. Check CloudWatch Logs for error details:\n   ```bash\n   aws logs tail /aws/lambda/alb-status-report --follow --filter-pattern \"ERROR\"\n   ```\n\n2. Identify error type:\n   - **Athena timeout**: Increase `MAX_WAIT_SECONDS` environment variable\n   - **S3 access denied**: Verify IAM permissions\n   - **SNS publish failed**: Check SNS topic exists and permissions\n   - **OOM**: Increase Lambda memory\n\n3. Manual retry:\n   ```bash\n   aws lambda invoke \\\n     --function-name alb-status-report \\\n     --payload '{}' \\\n     /tmp/response.json\n   ```\n\n4. If still failing, rollback to previous Lambda version:\n   ```bash\n   aws lambda update-function-code \\\n     --function-name alb-status-report \\\n     --s3-bucket lambda-deployments \\\n     --s3-key alb-status-report/previous-version.zip\n   ```\n\n---\n\n### Timeout Investigation Runbook\n\n**Alarm**: `alb-status-report-timeout-warning`\n\n**Steps**:\n1. Check Athena query execution time:\n   ```bash\n   aws athena get-query-execution --query-execution-id <qid> \\\n     --query 'QueryExecution.Statistics.EngineExecutionTimeInMillis'\n   ```\n\n2. Review data scanned:\n   ```bash\n   aws athena get-query-execution --query-execution-id <qid> \\\n     --query 'QueryExecution.Statistics.DataScannedInBytes'\n   ```\n\n3. If data scanned > 50 GB:\n   - Check if partition projection is enabled\n   - Convert ALB logs to Parquet format\n   - Review query for unnecessary columns\n\n4. If Athena query < 120s but Lambda still slow:\n   - Check PDF generation time in logs\n   - Review S3 upload duration\n   - Consider increasing Lambda memory\n\n---\n\n### Throttling Runbook\n\n**Alarm**: `alb-status-report-throttles`\n\n**Steps**:\n1. Check concurrent executions:\n   ```bash\n   aws cloudwatch get-metric-statistics \\\n     --namespace AWS/Lambda \\\n     --metric-name ConcurrentExecutions \\\n     --dimensions Name=FunctionName,Value=alb-status-report \\\n     --statistics Maximum \\\n     --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \\\n     --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \\\n     --period 300\n   ```\n\n2. Check reserved concurrency:\n   ```bash\n   aws lambda get-function-concurrency --function-name alb-status-report\n   ```\n\n3. If reserved concurrency = 1 and multiple invocations attempted:\n   - Investigate why Lambda invoked multiple times (duplicate EventBridge triggers?)\n   - Remove reserved concurrency if not needed\n\n4. If account-level concurrency limit reached:\n   - Request limit increase via AWS Support\n\n---\n\n### Missing Invocation Runbook\n\n**Alarm**: `alb-status-report-missing-invocation`\n\n**Steps**:\n1. Check EventBridge schedule:\n   ```bash\n   aws events describe-rule --name alb-status-report-daily-schedule\n   ```\n\n2. Verify schedule is enabled:\n   ```bash\n   aws events list-targets-by-rule --rule alb-status-report-daily-schedule\n   ```\n\n3. Check Lambda permissions for EventBridge:\n   ```bash\n   aws lambda get-policy --function-name alb-status-report\n   ```\n\n4. Manually trigger Lambda:\n   ```bash\n   aws lambda invoke \\\n     --function-name alb-status-report \\\n     --payload '{}' \\\n     /tmp/response.json\n   ```\n\n5. Re-create EventBridge rule if needed\n\n---\n\n## Testing Alarms\n\n### Alarm Testing Checklist\n\n- [ ] **Lambda Errors**: Temporarily introduce an exception in code, deploy, and verify alarm triggers\n- [ ] **Timeout**: Set `MAX_WAIT_SECONDS=1` to force timeout, verify alarm\n- [ ] **Memory**: Reduce Lambda memory to 128 MB, invoke, verify OOM alarm\n- [ ] **Missing Invocation**: Disable EventBridge rule for 25 hours, verify alarm\n- [ ] **SNS Delivery**: Verify emails/pages received for each alarm\n\n### Alarm Testing Script\n\n```bash\n#!/bin/bash\n# test-alarms.sh\n\necho \"Testing Lambda error alarm...\"\n# Temporarily add error to handler.py\n# Deploy, invoke, wait for alarm\n\necho \"Testing timeout alarm...\"\n# Set MAX_WAIT_SECONDS=1 in environment\n# Invoke, wait for alarm\n\n# Add tests for remaining alarms...\n```\n\n---\n\n## Alarm Maintenance\n\n### Monthly Tasks\n\n- [ ] Review alarm history (false positives?)\n- [ ] Update thresholds based on actual metrics\n- [ ] Test alarm notifications\n- [ ] Review and update runbooks\n\n### Quarterly Tasks\n\n- [ ] Conduct tabletop exercise (simulate failures)\n- [ ] Review alarm severity levels\n- [ ] Update on-call contacts\n\n---\n\n**Document Version**: 1.0  \n**Last Updated**: January 2026  \n**Maintained By**: SRE Team"
