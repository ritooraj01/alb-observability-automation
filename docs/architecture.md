# Architecture Documentation

## Table of Contents

- [System Overview](#system-overview)
- [Architecture Diagram](#architecture-diagram)
- [Component Details](#component-details)
- [Data Sources](#data-sources)
- [Compute Layer](#compute-layer)
- [Storage Architecture](#storage-architecture)
- [Notification System](#notification-system)
- [Monitoring and Observability](#monitoring-and-observability)
- [Design Decisions](#design-decisions)
- [Scalability Considerations](#scalability-considerations)

---

## System Overview

The ALB Observability Automation system is a **serverless, event-driven architecture** designed to provide automated monitoring and reporting for Application Load Balancer (ALB) access patterns.

### High-Level Goals

1. **Automated Analytics**: Transform raw ALB logs into actionable insights
2. **Operational Visibility**: Provide daily API health summaries
3. **Audit Compliance**: Generate immutable PDF reports for compliance teams
4. **Cost Efficiency**: Leverage serverless components to minimize operational costs
5. **Reliability**: Built-in retries, error handling, and monitoring

### Architecture Principles

- **Serverless-First**: No infrastructure to manage
- **Event-Driven**: Decoupled components communicating via events
- **Immutable Infrastructure**: Lambda code and layers versioned
- **Observability by Design**: Comprehensive logging and metrics
- **Security by Default**: Least-privilege IAM, encryption at rest and in transit

---

## Architecture Diagram

### Logical Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                         AWS ACCOUNT (REGION)                          │
└───────────────────────────────────────────────────────────────────────┘

┌─────────────────────┐
│   Application       │
│   Load Balancer     │◀────── HTTPS Traffic
│   (ALB)             │
└─────────┬───────────┘
          │ Access Logs (every 5 min)
          ▼
┌─────────────────────────────────────┐
│  S3 Bucket: ALB Access Logs         │
│  - Prefix: AWSLogs/<account-id>/    │
│  - Format: GZIP compressed          │
│  - Partition: yyyy/mm/dd/region/    │
└─────────┬───────────────────────────┘
          │
          │ Data Catalog (Glue)
          ▼
┌─────────────────────────────────────┐
│     AWS Glue Data Catalog           │
│  - Database: alb_logs_database      │
│  - Tables: alb_log_*, alb_access_*  │
│  - Partitions: Auto-projected       │
└─────────┬───────────────────────────┘
          │
          │ SQL Queries
          ▼
┌─────────────────────────────────────────────────┐
│            Amazon Athena                        │
│  Query Engine:                                  │
│    - Presto SQL                                 │
│    - Serverless                                 │
│    - Pay-per-query (GB scanned)                 │
│                                                  │
│  Optimizations:                                 │
│    - Partition pruning                          │
│    - Columnar format (Parquet recommended)      │
│    - Compression (GZIP/Snappy)                  │
└─────────┬───────────────────────────────────────┘
          │ Query results → S3
          │
┌─────────────────────┐               ┌──────────────────────┐
│  EventBridge        │   Trigger     │   AWS Lambda         │
│  (Optional)         │──────────────▶│   Function           │
│                     │               │                      │
│  Schedule:          │               │  Runtime: Python 3.11│
│  - cron(0 9 * * ?)  │               │  Memory: 512 MB      │
│  - 9 AM daily       │               │  Timeout: 300s       │
└─────────────────────┘               │                      │
                                      │  Layers:             │
                                      │  - reportlab-layer   │
                                      └──────────┬───────────┘
                                                 │
                            ┌────────────────────┼────────────────────┐
                            │                    │                    │
                            ▼                    ▼                    ▼
                    ┌───────────────┐    ┌──────────────┐    ┌──────────────┐
                    │  S3: Reports  │    │  SNS Topic   │    │  CloudWatch  │
                    │  - PDF files  │    │  - Email     │    │  Logs        │
                    │  - Presigned  │    │  - Plain text│    │  - Metrics   │
                    │    URLs       │    └──────────────┘    └──────────────┘
                    └───────────────┘
```

### Data Flow Sequence

```
[1] ALB logs requests → S3 (continuous)
       ↓
[2] Glue crawler catalogs log structure (on-demand or scheduled)
       ↓
[3] EventBridge triggers Lambda at scheduled time
       ↓
[4] Lambda executes Athena query
       ↓
[5] Athena scans S3 logs via Glue catalog
       ↓
[6] Query results written to S3 (CSV format)
       ↓
[7] Lambda polls Athena until query completes
       ↓
[8] Lambda fetches CSV results from S3
       ↓
[9] Lambda aggregates data (2xx/4xx/5xx per API)
       ↓
[10] Lambda generates PDF report (ReportLab)
       ↓
[11] Lambda uploads PDF to S3 (reports bucket)
       ↓
[12] Lambda generates presigned URL (24h expiry)
       ↓
[13] Lambda publishes SNS notification
       ↓
[14] Subscribers receive email with download link
```

---

## Component Details

### 1. Application Load Balancer (ALB)

**Purpose**: Entry point for HTTP/HTTPS traffic  
**Configuration**:
- Access logs enabled
- Log destination: `s3://<bucket-name>/AWSLogs/<account-id>/elasticloadbalancing/<region>/`
- Log interval: 5 minutes

**Log Format** (ELB Access Log Format):
```
type time elb client:port target:port request_processing_time target_processing_time 
response_processing_time elb_status_code target_status_code received_bytes sent_bytes 
"request" "user_agent" ssl_cipher ssl_protocol target_group_arn "trace_id" 
"domain_name" "chosen_cert_arn" matched_rule_priority request_creation_time 
"actions_executed" "redirect_url" "error_reason" "target:port_list" 
"target_status_code_list" "classification" "classification_reason"
```

### 2. AWS Glue Data Catalog

**Purpose**: Metadata repository for ALB logs  
**Components**:
- **Database**: `alb_logs_database`
- **Tables**:
  - `alb_log_partition_projection`: Uses partition projection for performance
  - `alb_access_logs_internal`: Standard partitioned table

**Partition Strategy**:
```
s3://bucket/prefix/
  └── year=2026/
      └── month=01/
          └── day=17/
              └── region=us-east-1/
                  └── *.log.gz
```

**Table Schema** (Key Columns):
- `time` (timestamp)
- `elb_status_code` (int)
- `target_group_arn` (string)
- `request` (string)
- `user_agent` (string)

### 3. Amazon Athena

**Purpose**: Serverless SQL query engine  
**Query Pattern**:
```sql
-- Aggregate status codes per target group
SELECT target_group_arn, elb_status_code, COUNT(*) as count
FROM alb_logs
WHERE partition_date = CURRENT_DATE
GROUP BY target_group_arn, elb_status_code
```

**Performance Optimizations**:
- **Partition Pruning**: Only scan current day's data
- **Columnar Format**: Use Parquet instead of JSON/text (10x faster)
- **Compression**: GZIP or Snappy reduces data scanned
- **Query Result Reuse**: Cache enabled for 24 hours

**Cost Model**:
- $5 per TB scanned
- Typical daily scan: 1-10 GB
- Estimated cost: $0.05-$0.50 per report

### 4. AWS Lambda

**Purpose**: Orchestrates report generation workflow  
**Configuration**:
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Runtime | Python 3.11 | Latest stable Python with performance improvements |
| Memory | 512 MB | Balanced for PDF generation (tested: 256MB = OOM) |
| Timeout | 300 seconds | Athena queries can take 30-60 seconds |
| Ephemeral Storage | 512 MB | Default (PDF files < 10 MB) |
| Reserved Concurrency | 1 | Serial execution prevents duplicate reports |

**Lambda Layers**:
- **reportlab-layer** (50 MB): PDF generation library
  - Avoids bundling large dependencies in deployment package
  - Shared across multiple functions
  - Versioned for rollback capability

**Environment Variables**:
```bash
ATHENA_DB=alb_logs_database
ATHENA_OUTPUT=s3://athena-results-bucket/queries/
PDF_BUCKET=report-storage-bucket
PDF_PREFIX=alb-reports
SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:alb-reports
AWS_REGION=us-east-1
MAX_WAIT_SECONDS=180
```

**Error Handling**:
- Athena query failures: Logged + CloudWatch alarm
- S3 upload failures: Retry with exponential backoff
- SNS publish failures: Non-blocking (report still available in S3)
- Lambda timeouts: Increase timeout or optimize query

### 5. Amazon S3

**Purpose**: Storage for logs, query results, and reports  
**Buckets**:

| Bucket | Purpose | Lifecycle Policy |
|--------|---------|------------------|
| `alb-logs-bucket` | ALB access logs | Transition to Glacier after 90 days, delete after 365 days |
| `athena-results-bucket` | Query output | Delete after 7 days |
| `report-storage-bucket` | PDF reports | Transition to IA after 30 days, keep indefinitely |

**Security**:
- Bucket encryption: SSE-S3 or SSE-KMS
- Public access: Blocked
- Access logging: Enabled for audit
- Versioning: Enabled for reports bucket

### 6. Amazon SNS

**Purpose**: Email notification delivery  
**Configuration**:
- Topic name: `alb-api-status-reports`
- Protocol: Email
- Message format: Plain text (SNS limitation)
- Retry policy: 3 attempts over 1 hour

**Email Template**:
```
Subject: Daily ALB API Status Report | 2026-01-17

Body:
Daily ALB API Status Report
Date: 2026-01-17

=== SUMMARY ===
Total 2xx (Success): 1,234,567
Total 4xx (Client Errors): 12,345
Total 5xx (Server Errors): 123

Download PDF Report (valid for 24 hours):
https://report-storage-bucket.s3.amazonaws.com/...?X-Amz-Signature=...

Regards,
DevOps Automation Team
```

### 7. Amazon CloudWatch

**Purpose**: Centralized logging and monitoring  
**Components**:
- **Logs**: `/aws/lambda/alb-status-report`
- **Metrics**: Lambda standard metrics + custom metrics
- **Alarms**: Error rates, duration, throttles
- **Dashboards**: Real-time execution visibility

---

## Data Sources

### ALB Log Format

ALB writes logs in space-delimited format:

```
https 2026-01-17T09:15:23.456789Z app/my-alb/abc123 192.168.1.10:54321 
10.0.1.5:8080 0.001 0.023 0.000 200 200 1234 5678 
"GET https://api.example.com:443/v1/users HTTP/1.1" 
"Mozilla/5.0 ..." ECDHE-RSA-AES128-GCM-SHA256 TLSv1.2 
arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/api-service-1-tg/xyz789
"Root=1-abc-123" "api.example.com" "arn:aws:acm:..." 0 
2026-01-17T09:15:23.433000Z "forward" "-" "-" 
"10.0.1.5:8080" "200" "-" "-"
```

### Key Fields Extracted

| Field | Description | Usage |
|-------|-------------|-------|
| `elb_status_code` | HTTP status from ALB | Classification (2xx/4xx/5xx) |
| `target_group_arn` | Target group identifier | API name detection |
| `request_processing_time` | Time waiting for request | Performance analysis (future) |
| `target_processing_time` | Backend processing time | Performance analysis (future) |
| `time` | Request timestamp | Partitioning and filtering |

---

## Design Decisions

### Why Serverless?

| Traditional (EC2) | Serverless (Lambda) | Winner |
|-------------------|---------------------|--------|
| Always running ($$) | Pay per execution | ✅ Serverless |
| Manual scaling | Auto-scales | ✅ Serverless |
| Patch management | Managed by AWS | ✅ Serverless |
| Fixed capacity | Unlimited concurrency | ✅ Serverless |

### Why Athena over Other Options?

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **Athena** | Serverless, SQL, pay-per-query | Query latency (10-30s) | ✅ **Chosen** |
| **EMR** | Faster for large datasets | High cost, complex setup | ❌ Overkill |
| **Glue ETL** | Managed Spark jobs | More expensive than Athena | ❌ Not needed |
| **Lambda + S3 Select** | Low latency | No aggregations, manual coding | ❌ Too limited |

### Why PDF Reports?

- **Portability**: Universal format, works offline
- **Immutability**: Can't be easily altered (audit compliance)
- **Professional**: Formatted tables, headers, metadata
- **Archival**: Long-term storage without dependency on systems

### Why SNS instead of SES?

| Feature | SNS | SES |
|---------|-----|-----|
| Setup Complexity | Simple (1 topic) | Moderate (verify domains, templates) |
| Email Format | Plain text only | HTML + attachments |
| Cost | $0 for first 1000 emails | $0.10 per 1000 emails |
| Use Case | Operational notifications | Marketing, transactional emails |

**Current**: SNS (simple, good enough)  
**Future**: SES (HTML tables, inline charts, PDF attachments)

---

## Scalability Considerations

### Current Scale

- **APIs**: 40+ target groups
- **Daily Requests**: 10-50 million
- **Log Volume**: 5-20 GB/day compressed
- **Report Generation**: 15-40 seconds

### Scaling to 1000+ APIs

**Challenge**: Single Lambda execution may timeout  
**Solution**: Fan-out pattern

```
EventBridge Schedule
       ↓
Lambda Orchestrator (splits APIs into batches)
       ├───▶ Lambda Worker 1 (APIs 1-100)
       ├───▶ Lambda Worker 2 (APIs 101-200)
       ├───▶ Lambda Worker 3 (APIs 201-300)
       └───▶ ...
             ↓
        S3 (partial reports)
             ↓
Lambda Aggregator (combines PDFs)
             ↓
        Final Report
```

### Multi-Region Architecture

**Current**: Single-region deployment  
**Future**: Multi-region aggregation

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   us-east-1     │    │   eu-west-1     │    │   ap-south-1    │
│   Lambda        │    │   Lambda        │    │   Lambda        │
│   (Regional)    │    │   (Regional)    │    │   (Regional)    │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                       │
         └──────────────────────┼───────────────────────┘
                                ▼
                    ┌───────────────────────┐
                    │  Global Aggregator    │
                    │  (Lambda in us-east-1)│
                    └───────────┬───────────┘
                                ▼
                        Combined Global Report
```

---

## Monitoring and Observability

### CloudWatch Logs Structure

```
/aws/lambda/alb-status-report
  └── 2026/01/17/
      └── [$LATEST]abc123...
          ├── START RequestId: abc-123
          ├── [INFO] Lambda invocation started
          ├── [INFO] Athena query started: qid-xyz
          ├── [INFO] Query completed after 23s
          ├── [INFO] Aggregated 45,678,901 requests
          ├── [INFO] PDF generated: 2.3 MB
          ├── [INFO] Uploaded to s3://...
          ├── [INFO] SNS notification sent
          ├── [INFO] Report generation completed
          └── END RequestId: abc-123
              REPORT Duration: 35678 ms  Memory: 412 MB / 512 MB
```

### Key Metrics to Track

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Invocation Count | 1/day | < 1 (missing execution) |
| Error Rate | 0% | > 1% |
| Duration | 30-60s | > 240s |
| Athena Data Scanned | 5-10 GB | > 50 GB (cost spike) |
| Memory Utilization | 60-80% | > 90% |

---

## Security Architecture

See [security.md](security.md) for detailed security documentation.

**Key Points**:
- IAM roles with least-privilege
- S3 encryption at rest (SSE-S3 or SSE-KMS)
- Presigned URLs with time-based expiry
- VPC deployment (optional) for network isolation
- CloudWatch Logs for audit trail

---

## Cost Analysis

### Monthly Cost Breakdown (30 reports/month)

| Service | Usage | Cost |
|---------|-------|------|
| **Lambda** | 30 invocations × 40s × 512 MB | $0.02 |
| **Athena** | 30 queries × 10 GB scanned | $1.50 |
| **S3 Storage** | 30 PDFs × 2 MB + logs | $0.50 |
| **SNS** | 30 email notifications | $0.00 |
| **CloudWatch Logs** | 100 MB logs/month | $0.50 |
| **Data Transfer** | Minimal (same region) | $0.10 |
| **Total** | | **~$2.62/month** |

### Cost Optimization Strategies

1. **Use Parquet format** for ALB logs: 90% reduction in Athena costs
2. **Partition pruning**: Only scan necessary date partitions
3. **S3 lifecycle policies**: Move old logs to Glacier ($0.004/GB vs $0.023/GB)
4. **Lambda right-sizing**: 512 MB is optimal (tested 256 MB → OOM, 1024 MB → same duration)

---

## Disaster Recovery

### Failure Scenarios

| Scenario | Impact | Recovery Time | Mitigation |
|----------|--------|---------------|------------|
| Lambda failure | No report generated | 5 min (manual retry) | CloudWatch alarm + on-call |
| Athena timeout | Lambda times out | 10 min (increase timeout) | Set MAX_WAIT_SECONDS=300 |
| S3 outage | Cannot upload PDF | Auto-retry | Use S3 cross-region replication |
| SNS failure | Email not sent | 5 min (manual send) | Non-blocking error (report in S3) |

### Backup Strategy

- **Lambda Code**: Versioned in Git + S3
- **IAM Policies**: Infrastructure as Code (Terraform/CloudFormation)
- **Reports**: S3 versioning enabled
- **Configuration**: Environment variables backed up in Parameter Store

---

## Future Enhancements

1. **Real-Time Alerting**: Use Kinesis Firehose → Lambda for sub-minute alerts
2. **Anomaly Detection**: ML-based detection of unusual error rates
3. **Historical Trends**: 7-day/30-day comparison charts in PDF
4. **Multi-Account**: Aggregate ALB logs from multiple AWS accounts
5. **Cost Attribution**: Break down costs per API/team

---

## References

- [AWS ALB Access Log Format](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-access-logs.html)
- [Amazon Athena Best Practices](https://docs.aws.amazon.com/athena/latest/ug/performance-tuning.html)
- [AWS Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)

---

**Document Version**: 2.0  
**Last Updated**: January 2026  
**Maintained By**: DevOps Engineering Team
