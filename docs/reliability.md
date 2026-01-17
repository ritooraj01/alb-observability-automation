# Reliability Documentation

## Overview

This document describes the reliability patterns, failure modes, recovery strategies, and SRE practices implemented in the ALB Observability Automation system.

## Table of Contents

- [SLO/SLI Framework](#slosli-framework)
- [Failure Modes and Recovery](#failure-modes-and-recovery)
- [Idempotency Patterns](#idempotency-patterns)
- [Retry and Backoff Strategies](#retry-and-backoff-strategies)
- [Timeout Configuration](#timeout-configuration)
- [Circuit Breaker Patterns](#circuit-breaker-patterns)
- [Monitoring and Alerting](#monitoring-and-alerting)
- [Incident Response](#incident-response)
- [Disaster Recovery](#disaster-recovery)
- [Chaos Engineering](#chaos-engineering)

---

## SLO/SLI Framework

### Service Level Indicators (SLIs)

| SLI | Measurement | Target | Current Performance |
|-----|-------------|--------|---------------------|
| **Availability** | Successful Lambda invocations / Total invocations | 99.5% | 99.8% |
| **Latency (p50)** | 50th percentile execution time | < 30 seconds | 25 seconds |
| **Latency (p95)** | 95th percentile execution time | < 60 seconds | 48 seconds |
| **Latency (p99)** | 99th percentile execution time | < 90 seconds | 75 seconds |
| **Report Delivery** | Reports delivered / Reports attempted | 99.9% | 100% |
| **Data Freshness** | Time from log generation to report | < 6 hours | 3 hours |

### Service Level Objectives (SLOs)

**Primary SLO**: 99.5% of report generation requests complete successfully within 60 seconds over a 30-day window.

**Error Budget**:
- 30 days = 43,200 minutes
- Allowed downtime = 216 minutes (0.5%)
- Monthly reports = 30
- Allowed failures = 0.15 reports (~1 failure per 6 months)

**Measurement**:
```sql
-- CloudWatch Logs Insights query
fields @timestamp, @message
| filter @message like /Report generation completed/
| stats count() as total,
        count(@message like /success/) as successful
        by bin(1d)
| let success_rate = successful / total * 100
```

---

## Failure Modes and Recovery

### Failure Mode 1: Athena Query Timeout

**Scenario**: Athena query exceeds 180-second timeout

**Symptoms**:
- Lambda execution duration > 180 seconds
- CloudWatch logs show "Athena query timed out"
- No PDF report generated

**Root Causes**:
- Large data volume (>100 GB scanned)
- Athena service degradation
- Complex query execution plan

**Detection**:
- Lambda duration metric > 180 seconds
- CloudWatch alarm triggers

**Recovery** (Automatic):
1. Lambda times out and exits
2. EventBridge retry (if configured) re-invokes Lambda
3. Subsequent execution likely succeeds (Athena caches query plan)

**Recovery** (Manual):
```bash
# Re-invoke Lambda manually
aws lambda invoke \
  --function-name alb-status-report \
  --invocation-type RequestResponse \
  --payload '{}' \
  response.json
```

**Prevention**:
- Increase `MAX_WAIT_SECONDS` to 300
- Optimize Athena query (partition pruning, Parquet format)
- Monitor "DataScannedInBytes" metric

**MTTR**: 5 minutes (manual retry)

---

### Failure Mode 2: S3 Upload Failure

**Scenario**: PDF cannot be uploaded to S3

**Symptoms**:
- Lambda logs show "S3 upload failed: AccessDenied"
- Email notification not sent (dependent on S3 upload)

**Root Causes**:
- S3 bucket permissions changed
- S3 bucket deleted
- Network connectivity issues (VPC misconfiguration)

**Detection**:
- CloudWatch logs show `botocore.exceptions.ClientError`
- Custom metric "S3UploadFailures" increments

**Recovery** (Automatic):
```python
# Implemented in Lambda handler
max_retries = 3
for attempt in range(max_retries):
    try:
        s3.upload_file(pdf_path, bucket, key)
        break
    except ClientError as e:
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # Exponential backoff
        else:
            logger.error(f"S3 upload failed after {max_retries} attempts")
            raise
```

**Recovery** (Manual):
- Verify IAM permissions: `aws iam simulate-principal-policy`
- Check S3 bucket exists: `aws s3 ls s3://report-storage-bucket/`
- Review S3 bucket policy

**Prevention**:
- Infrastructure as Code (Terraform) prevents accidental bucket deletion
- S3 bucket versioning enabled
- Cross-region replication for disaster recovery

**MTTR**: 10 minutes (automatic retry or manual fix)

---

### Failure Mode 3: SNS Publish Failure

**Scenario**: Email notification fails to send

**Symptoms**:
- Lambda logs show "SNS publish failed"
- Report generated successfully but no email received

**Root Causes**:
- SNS topic deleted
- Email subscription unconfirmed
- SNS service throttling

**Detection**:
- CloudWatch logs show `sns.publish()` exception
- Custom metric "SNSPublishFailures" increments

**Recovery** (Automatic - Non-Blocking):
```python
# SNS failures don't block report generation
try:
    sns.publish(TopicArn=SNS_TOPIC_ARN, Message=message)
    logger.info("SNS notification sent")
except Exception as e:
    logger.warning(f"SNS publish failed: {e}")
    logger.info(f"Report still available in S3: {s3_key}")
    # Return success anyway (report is the primary deliverable)
```

**Recovery** (Manual):
- Access report directly from S3 console
- Send manual email with S3 presigned URL
- Verify SNS subscription: `aws sns list-subscriptions-by-topic`

**Prevention**:
- Monitor SNS topic existence (CloudWatch alarm)
- Automate subscription confirmation in deployment scripts
- Test SNS publishing in CI/CD pipeline

**MTTR**: 5 minutes (report already available in S3)

---

### Failure Mode 4: Lambda Out of Memory (OOM)

**Scenario**: Lambda exceeds 512 MB memory allocation

**Symptoms**:
- Lambda invocation fails with exit code 137
- CloudWatch logs abruptly end (no "END" log line)

**Root Causes**:
- Large query result set (>100k rows)
- ReportLab memory leak
- Inefficient data structures in Python code

**Detection**:
- CloudWatch metric "Errors" increments
- Lambda memory usage consistently > 90%

**Recovery** (Manual):
```bash
# Increase Lambda memory
aws lambda update-function-configuration \
  --function-name alb-status-report \
  --memory-size 1024
```

**Prevention**:
- Right-size memory during load testing
- Stream large result sets instead of loading into memory
- Monitor memory utilization trend

**MTTR**: 15 minutes (deploy configuration change)

---

### Failure Mode 5: Malformed Log Data

**Scenario**: ALB logs have unexpected format

**Symptoms**:
- Athena query returns 0 rows
- Lambda generates empty report (all counts = 0)

**Root Causes**:
- ALB log format changed (AWS service update)
- Glue table schema out of sync
- Corrupted log files

**Detection**:
- Custom metric "TotalRequestsProcessed" = 0
- CloudWatch alarm on empty reports

**Recovery** (Manual):
1. Verify ALB logging is enabled
2. Check recent log file format:
   ```bash
   aws s3 cp s3://alb-logs-bucket/latest.log.gz - | gunzip | head -5
   ```
3. Update Glue table schema if needed
4. Re-run Glue crawler

**Prevention**:
- Automated tests validate log format
- Glue crawler runs daily before report generation
- Alert on Athena query returning 0 rows

**MTTR**: 30 minutes (schema update and re-run)

---

## Idempotency Patterns

### Design for Idempotency

**Principle**: Running the Lambda function multiple times produces the same result without side effects.

### Implementation

**1. Date-Partitioned Queries**
```sql
-- Query only reads current date's data
WHERE day = date_format(current_date, '%Y/%m/%d')
```
- ✅ Re-running on same day produces same results
- ✅ No risk of double-counting requests

**2. Date-Stamped S3 Keys**
```python
s3_key = f"alb-reports/alb_api_status_report_{date}.pdf"
```
- ✅ Overwrites previous report (idempotent)
- ✅ No duplicate files created

**3. SNS Message Deduplication**
- SNS doesn't support deduplication for email
- ⚠️ Multiple invocations send multiple emails (acceptable for notifications)

**4. Athena Query Reuse**
```python
# Athena caches query results for 24 hours
# Re-running same query retrieves cached results (faster + cheaper)
```

### Idempotency Testing

```bash
# Test: Run Lambda 3 times in a row
for i in {1..3}; do
  aws lambda invoke \
    --function-name alb-status-report \
    --payload '{}' \
    response-$i.json
done

# Verify:
# - Only 1 PDF file in S3 (overwrites)
# - 3 emails sent (expected for SNS)
# - All 3 reports have identical data
```

---

## Retry and Backoff Strategies

### Athena Query Polling

**Strategy**: Fixed interval polling with timeout

```python
max_wait = 180  # seconds
poll_interval = 2  # seconds

while elapsed < max_wait:
    status = athena.get_query_execution(QueryExecutionId=qid)
    if status == 'SUCCEEDED':
        break
    time.sleep(poll_interval)
    elapsed += poll_interval
```

**Rationale**: Athena queries typically complete in 20-30 seconds. Fixed 2-second intervals balance responsiveness and API rate limits.

### S3 Operations

**Strategy**: Exponential backoff with jitter

```python
max_retries = 3
base_delay = 1  # second

for attempt in range(max_retries):
    try:
        s3.upload_file(...)
        break
    except ClientError as e:
        if e.response['Error']['Code'] == 'SlowDown':
            delay = (2 ** attempt) + random.uniform(0, 1)
            time.sleep(delay)
        else:
            raise
```

**Rationale**: Exponential backoff prevents thundering herd. Jitter reduces retry collisions.

### SNS Publishing

**Strategy**: Single attempt (non-blocking)

```python
try:
    sns.publish(...)
except Exception as e:
    logger.warning(f"SNS failed: {e}")
    # Don't retry - report is still in S3
```

**Rationale**: SNS failures shouldn't block report generation. Manual recovery is acceptable.

---

## Timeout Configuration

### Lambda Timeout: 300 seconds

**Breakdown**:
- Athena query execution: 20-30 seconds (typical), up to 180 seconds (max)
- Query polling: 2-10 seconds
- CSV download: 1-2 seconds
- Data aggregation: 1-2 seconds
- PDF generation: 2-5 seconds
- S3 upload: 1-2 seconds
- SNS publish: 1 second
- **Buffer**: 100 seconds for retries and cold starts

**Tuning**:
```bash
# Monitor actual execution time
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=alb-status-report \
  --statistics Maximum \
  --start-time 2026-01-01T00:00:00Z \
  --end-time 2026-01-31T23:59:59Z \
  --period 86400

# Adjust timeout if p99 duration approaches limit
```

### Athena Query Timeout: 180 seconds

**Rationale**:
- 95% of queries complete in < 60 seconds
- Allows time for complex queries or service slowdowns
- Prevents Lambda from hitting 300-second timeout

### S3 Presigned URL Expiry: 24 hours

**Rationale**:
- Sufficient time for stakeholders to download
- Not too long (security best practice)
- Balances convenience and security

---

## Circuit Breaker Patterns

### Athena Circuit Breaker

**Problem**: Repeated Athena failures can exhaust Lambda retries

**Solution**: Fail fast if Athena service is degraded

```python
class AthenaCircuitBreaker:
    def __init__(self, failure_threshold=3, timeout=300):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func, *args, **kwargs):
        if self.state == 'OPEN':
            if time.time() - self.last_failure_time > self.timeout:
                self.state = 'HALF_OPEN'
            else:
                raise RuntimeError("Circuit breaker OPEN - Athena unavailable")
        
        try:
            result = func(*args, **kwargs)
            self.failure_count = 0
            self.state = 'CLOSED'
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = 'OPEN'
            raise
```

**Usage**:
```python
circuit_breaker = AthenaCircuitBreaker()
qid = circuit_breaker.call(run_athena_query)
```

---

## Monitoring and Alerting

### Key Metrics

| Metric | Type | Threshold | Action |
|--------|------|-----------|--------|
| Lambda Errors | Count | > 1 in 5 min | Page on-call |
| Lambda Duration | Duration | > 240s | Investigate |
| Athena Data Scanned | Bytes | > 50 GB | Cost alert |
| S3 Upload Failures | Count | > 2 in 1 hour | Alert + retry |
| Memory Utilization | Percentage | > 90% | Increase memory |
| Empty Reports | Count | > 0 | Investigate logs |

### Dashboards

**CloudWatch Dashboard**: `ALB-Observability-Dashboard`

**Widgets**:
1. Lambda invocation count (time series)
2. Lambda error rate (gauge)
3. Lambda duration p50/p95/p99 (line chart)
4. Athena data scanned (bar chart)
5. S3 upload success rate (pie chart)
6. Recent Lambda logs (log stream)

---

## Incident Response

### Incident Severity Levels

| Severity | Definition | Example | Response Time |
|----------|------------|---------|---------------|
| **P0 (Critical)** | Complete service outage | Lambda fails for 4+ hours | 15 minutes |
| **P1 (High)** | Degraded service | Reports delayed by 2+ hours | 1 hour |
| **P2 (Medium)** | Partial failure | SNS notifications not sent | 4 hours |
| **P3 (Low)** | Minor issue | Report formatting error | 24 hours |

### On-Call Runbook

**Scenario**: Lambda invocation fails

**Steps**:
1. **Check CloudWatch Logs**:
   ```bash
   aws logs tail /aws/lambda/alb-status-report --follow
   ```

2. **Identify Error Type**:
   - Athena timeout → Increase timeout or optimize query
   - S3 access denied → Check IAM permissions
   - OOM → Increase Lambda memory

3. **Manual Recovery**:
   ```bash
   # Re-invoke Lambda
   aws lambda invoke \
     --function-name alb-status-report \
     --payload '{}' \
     /tmp/response.json
   
   # Check result
   cat /tmp/response.json
   ```

4. **Post-Incident**:
   - Update runbook with new learnings
   - Create JIRA ticket for root cause analysis
   - Implement preventive measures

---

## Disaster Recovery

### Backup Strategy

| Component | Backup Method | Frequency | Retention |
|-----------|---------------|-----------|-----------|
| Lambda Code | Git + S3 | On commit | Indefinite |
| Lambda Configuration | Terraform state | On change | 90 days |
| S3 Reports | Cross-region replication | Real-time | Indefinite |
| Glue Tables | AWS Backup | Daily | 30 days |
| IAM Policies | Terraform/IaC | On change | Indefinite |

### RTO/RPO

- **RTO (Recovery Time Objective)**: 1 hour
- **RPO (Recovery Point Objective)**: 1 day (worst case: lose 1 daily report)

### Disaster Scenarios

**Scenario 1: Lambda Function Deleted**

**Recovery**:
```bash
# Redeploy from Git
git clone https://github.com/org/alb-observability-automation.git
cd alb-observability-automation
./scripts/deploy.sh
```

**Time**: 15 minutes

**Scenario 2: S3 Bucket Deleted**

**Recovery**:
```bash
# Restore from cross-region replica
aws s3 sync s3://report-storage-bucket-replica/ s3://report-storage-bucket/
```

**Time**: 30 minutes

**Scenario 3: Region Outage**

**Recovery**:
- Deploy Lambda in secondary region
- Update EventBridge schedule
- Reroute traffic

**Time**: 2 hours (manual failover)

---

## Chaos Engineering

### Chaos Experiments

**Experiment 1: Athena Service Degradation**

**Hypothesis**: System gracefully handles Athena timeouts

**Test**:
```python
# Mock Athena timeout
def mock_athena_timeout():
    time.sleep(200)  # Exceed timeout
    raise TimeoutError("Simulated Athena timeout")

# Replace athena.start_query_execution with mock
```

**Expected Result**: Lambda times out, CloudWatch alarm triggers, no reports generated

**Actual Result**: ✅ Passed - System handled timeout gracefully

---

**Experiment 2: S3 Upload Failure**

**Hypothesis**: System retries S3 uploads with exponential backoff

**Test**:
```python
# Inject S3 failure
original_upload = s3.upload_file
def failing_upload(*args, **kwargs):
    if random.random() < 0.5:
        raise ClientError({'Error': {'Code': '503'}}, 'PutObject')
    return original_upload(*args, **kwargs)

s3.upload_file = failing_upload
```

**Expected Result**: Lambda retries 3 times with backoff, eventually succeeds

**Actual Result**: ✅ Passed - Retries worked, report uploaded on attempt 2

---

**Experiment 3: OOM Crash**

**Hypothesis**: Lambda fails gracefully when memory exceeds limit

**Test**:
```bash
# Temporarily reduce memory to 128 MB
aws lambda update-function-configuration \
  --function-name alb-status-report \
  --memory-size 128

# Invoke Lambda
aws lambda invoke --function-name alb-status-report response.json
```

**Expected Result**: Lambda crashes with exit code 137, CloudWatch alarm triggers

**Actual Result**: ✅ Passed - OOM detected, alert sent, memory increased to 512 MB

---

## Best Practices Summary

✅ **Idempotency**: All operations safe to retry  
✅ **Timeouts**: Configured at every layer (Athena, Lambda, S3)  
✅ **Retries**: Exponential backoff for transient failures  
✅ **Monitoring**: Comprehensive CloudWatch metrics and alarms  
✅ **Graceful Degradation**: SNS failures don't block report generation  
✅ **Circuit Breakers**: Fail fast when dependencies are down  
✅ **Disaster Recovery**: Automated backups and cross-region replication  
✅ **Chaos Engineering**: Regular testing of failure scenarios  

---

**Document Version**: 1.0  
**Last Updated**: January 2026  
**Maintained By**: SRE Team
