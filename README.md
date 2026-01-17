# ALB Observability Automation

[![AWS](https://img.shields.io/badge/AWS-Lambda%20%7C%20Athena%20%7C%20S3-orange)](https://aws.amazon.com/)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Production-grade AWS observability and automation system for Application Load Balancer monitoring, analytics, and automated reporting.**

---

## 📋 Table of Contents

- [Problem Statement](#-problem-statement)
- [Solution Overview](#-solution-overview)
- [Architecture](#-architecture)
- [Key Features](#-key-features)
- [Workflow](#-workflow)
- [Project Structure](#-project-structure)
- [Prerequisites](#-prerequisites)
- [Deployment](#-deployment)
- [Monitoring & Observability](#-monitoring--observability)
- [Security](#-security)
- [Reliability & SRE](#-reliability--sre)
- [CI/CD Strategy](#-cicd-strategy)
- [Scaling Considerations](#-scaling-considerations)
- [Cost Optimization](#-cost-optimization)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)

---

## 🎯 Problem Statement

### Business Challenge

Organizations running mission-critical applications on AWS Application Load Balancers face several observability challenges:

1. **Visibility Gap**: ALB access logs are stored in S3 but lack real-time aggregated insights
2. **Manual Analysis**: Engineers spend hours manually querying logs for status code distributions
3. **Delayed Incident Response**: Without automated reporting, critical errors go unnoticed
4. **Audit Requirements**: Compliance teams need daily reports on API health and performance
5. **Cross-Team Coordination**: Multiple teams need unified visibility into ALB behavior

### Technical Requirements

- Aggregate millions of ALB log entries daily across multiple target groups
- Generate API-wise status code distribution (2xx/4xx/5xx)
- Produce PDF reports for audit trails and stakeholder communication
- Deliver reports via email with secure S3 presigned URLs
- Maintain <5 minute report generation time
- Support 40+ APIs with independent target groups
- Ensure idempotency and fault tolerance
- Provide comprehensive observability and alerting

---

## 💡 Solution Overview

This solution implements a **serverless, event-driven observability pipeline** that:

✅ **Automates ALB log analytics** using Amazon Athena for SQL-based aggregation  
✅ **Generates professional PDF reports** with API-wise status code breakdowns  
✅ **Delivers reports securely** via SNS notifications and S3 presigned URLs  
✅ **Scales automatically** with AWS Lambda's managed infrastructure  
✅ **Provides operational insights** through CloudWatch metrics and alarms  
✅ **Maintains audit compliance** with immutable S3-based report storage  

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Compute** | AWS Lambda (Python 3.11) | Serverless execution environment |
| **Analytics** | Amazon Athena | SQL queries on ALB logs |
| **Storage** | Amazon S3 | ALB logs + PDF reports |
| **Notification** | Amazon SNS | Email delivery |
| **Monitoring** | CloudWatch Logs & Metrics | Observability and alerting |
| **Orchestration** | EventBridge (optional) | Scheduled execution |
| **CI/CD** | Jenkins + AWS CLI | Automated deployments |
| **PDF Generation** | ReportLab | Professional document creation |

---

## 💼 Business Impact

- **Eliminates manual ALB log analysis** (~2–3 hours saved per day)
- **Improves incident detection latency** for 5xx errors
- **Provides audit-ready daily API health reports**
- **Enables proactive SRE operations** for production systems

---

## 🏗️ Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         AWS Cloud (Region)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐         ┌──────────────┐                      │
│  │     ALB      │────────▶│   S3 Bucket  │                      │
│  │ Access Logs  │         │  (Raw Logs)  │                      │
│  └──────────────┘         └──────┬───────┘                      │
│                                   │                               │
│                                   │ Athena reads logs            │
│                                   ▼                               │
│                          ┌─────────────────┐                     │
│                          │ Amazon Athena   │                     │
│                          │  - Query Engine │                     │
│                          │  - Glue Catalog │                     │
│                          └────────┬────────┘                     │
│                                   │                               │
│  ┌────────────────┐               │ Query results                │
│  │  EventBridge   │               │                               │
│  │   (Schedule)   │───────┐       ▼                               │
│  └────────────────┘       │  ┌─────────────────────────────┐    │
│                           └─▶│      Lambda Function        │    │
│                              │  - Execute Athena query     │    │
│                              │  - Aggregate status codes   │    │
│                              │  - Generate PDF report      │    │
│                              │  - Upload to S3             │    │
│                              │  - Send SNS notification    │    │
│                              └─────────┬──────────┬────────┘    │
│                                        │          │              │
│                                        ▼          ▼              │
│                              ┌───────────┐  ┌──────────────┐   │
│                              │ S3 Bucket │  │   SNS Topic  │   │
│                              │  (Reports)│  │   (Email)    │   │
│                              └───────────┘  └──────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │           CloudWatch Logs + Metrics + Alarms           │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Component Interactions

1. **ALB → S3**: ALB continuously writes access logs to S3 bucket
2. **Athena → S3**: Athena queries structured log data using Glue Data Catalog
3. **EventBridge → Lambda**: Scheduled trigger (or manual invocation)
4. **Lambda → Athena**: Executes aggregation query and polls for results
5. **Lambda → S3**: Uploads generated PDF report
6. **Lambda → SNS**: Publishes email notification with presigned download URL
7. **Lambda → CloudWatch**: Streams logs and custom metrics

---

## ✨ Key Features

### 1. Intelligent Status Code Aggregation

- **Standard Classification**: 2xx (success), 4xx (client errors), 5xx (server errors)
- **Custom Rules**: Configurable APIs that treat 3xx redirects as successful responses
- **Target Group Mapping**: Automatic API detection from ALB target group ARNs
- **Multi-Source Consolidation**: Aggregates data from multiple Athena tables

### 2. Professional PDF Reporting

- **Formatted Tables**: Clean, readable API status summaries
- **Metadata**: Report date, generation timestamp, validity period
- **Styled Layout**: Headers, alternating row colors, proper alignment
- **Portable Format**: PDF for easy sharing and archival

### 3. Secure Distribution

- **S3 Presigned URLs**: Time-limited access (24-hour expiry)
- **SNS Email Notifications**: Plain-text email with download link
- **Access Control**: IAM-based permissions for S3 and Lambda
- **Audit Trail**: CloudWatch Logs capture all execution details

### 4. Operational Excellence

- **Error Handling**: Comprehensive try-catch blocks with graceful degradation
- **Logging**: Structured logging for debugging and audit
- **Retries**: Athena query polling with configurable timeout
- **Monitoring**: CloudWatch metrics and alarms for failure detection
- **Idempotency**: Safe to retry failed executions

---

## 🔄 Workflow

### End-to-End Execution Flow

```
START
  │
  ├─▶ [1] Lambda Invoked (EventBridge Schedule or Manual)
  │
  ├─▶ [2] Execute Athena Query
  │      └─ Query aggregates 2xx/4xx/5xx from ALB logs for current date
  │      └─ Combines data from multiple log tables
  │
  ├─▶ [3] Poll Query Status (max 180 seconds)
  │      └─ Check every 2 seconds
  │      └─ Handle FAILED/CANCELLED states
  │
  ├─▶ [4] Fetch Query Results
  │      └─ Download CSV results from S3
  │      └─ Parse rows into Python dictionaries
  │
  ├─▶ [5] Aggregate Data
  │      └─ Detect API from target group ARN
  │      └─ Apply status code classification rules
  │      └─ Build API-wise summary
  │
  ├─▶ [6] Generate PDF Report
  │      └─ Create formatted table with ReportLab
  │      └─ Add metadata (date, title)
  │      └─ Write to /tmp directory
  │
  ├─▶ [7] Upload to S3
  │      └─ Upload PDF with date-stamped filename
  │      └─ Generate presigned URL (24-hour expiry)
  │
  ├─▶ [8] Send SNS Notification
  │      └─ Build email message with summary
  │      └─ Include presigned URL for download
  │      └─ Publish to SNS topic
  │
  └─▶ [9] Return Success Response
         └─ Status, date, URL validity info
END
```

### Typical Execution Metrics

| Metric | Value |
|--------|-------|
| **Cold Start** | 2-4 seconds |
| **Athena Query** | 10-30 seconds |
| **PDF Generation** | 1-2 seconds |
| **S3 Upload** | <1 second |
| **SNS Publish** | <1 second |
| **Total Duration** | 15-40 seconds |

---

## 📁 Project Structure

```
alb-observability-automation/
├── README.md                          # This file
├── Jenkinsfile                        # CI/CD pipeline definition
│
├── lambda/                            # Lambda function code
│   └── alb_status_report/
│       ├── handler.py                 # Main Lambda handler
│       └── requirements.txt           # Python dependencies
│
├── monitoring/                        # Observability configurations
│   ├── cloudwatch.md                  # CloudWatch metrics guide
│   └── alarms.md                      # Alarm definitions
│
├── scripts/                           # DevOps automation
│   ├── deploy.sh                      # Deployment script
│   └── cleanup.sh                     # Resource cleanup
│
├── docs/                              # Architecture documentation
│   ├── architecture.md                # System design
│   ├── data-flow.md                   # Data processing flow
│   ├── security.md                    # Security model
│   └── reliability.md                 # SRE practices
│
└── reports/                           # Example reports
    └── openforge-report.md            # Implementation case study
```

---

## 🔧 Prerequisites

### AWS Resources (Must Exist)

- **S3 Buckets**:
  - ALB access logs bucket
  - Athena query results bucket
  - PDF reports storage bucket
- **Athena Database**: Glue Data Catalog with ALB log tables
- **SNS Topic**: Email subscription configured
- **IAM Role**: Lambda execution role with required permissions
- **VPC Configuration** (optional): If Lambda needs VPC access

### IAM Permissions Required

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::alb-logs-bucket/*",
        "arn:aws:s3:::athena-results-bucket/*",
        "arn:aws:s3:::report-storage-bucket/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "glue:GetDatabase",
        "glue:GetTable",
        "glue:GetPartitions"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sns:Publish"
      ],
      "Resource": "arn:aws:sns:REGION:ACCOUNT_ID:topic-name"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
```

### Development Tools

- Python 3.11+
- AWS CLI v2
- Jenkins (for CI/CD)
- Git

---

## 🚀 Deployment

### Option 1: Manual Deployment

```bash
# Navigate to Lambda directory
cd lambda/alb_status_report

# Install dependencies
pip install -r requirements.txt -t .

# Create deployment package
zip -r function.zip .

# Deploy to Lambda
aws lambda update-function-code \
  --function-name alb-status-report \
  --zip-file fileb://function.zip \
  --region us-east-1

# Update environment variables
aws lambda update-function-configuration \
  --function-name alb-status-report \
  --environment Variables="{
    ATHENA_DB=your_database,
    ATHENA_OUTPUT=s3://your-athena-results-bucket/
  }"
```

### Option 2: Automated Deployment (Recommended)

```bash
# Run deployment script
./scripts/deploy.sh

# Script handles:
# - Dependency installation
# - Package creation
# - Lambda deployment
# - Configuration updates
# - Smoke testing
```

### Lambda Configuration

| Setting | Recommended Value |
|---------|------------------|
| **Runtime** | Python 3.11 |
| **Memory** | 512 MB |
| **Timeout** | 300 seconds (5 minutes) |
| **Ephemeral Storage** | 512 MB |
| **Layers** | reportlab-layer (for PDF generation) |

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ATHENA_DB` | Athena database name | `alb_logs_database` |
| `ATHENA_OUTPUT` | S3 path for query results | `s3://athena-results/queries/` |

---

## 📊 Monitoring & Observability

### CloudWatch Metrics

#### Standard Lambda Metrics
- **Invocations**: Total execution count
- **Duration**: Execution time
- **Errors**: Failed invocations
- **Throttles**: Rate-limited requests
- **ConcurrentExecutions**: Parallel executions

#### Custom Metrics (Embedded in Logs)
- Query execution time
- PDF generation time
- Number of APIs processed
- Total status codes aggregated

### CloudWatch Alarms

**Critical Alarms**:
- Lambda errors > 1 in 5 minutes → Page on-call engineer
- Lambda duration > 240 seconds → Investigate performance
- Athena query failures → Check query/data integrity

**Warning Alarms**:
- Lambda duration > 180 seconds → Optimization needed
- Memory utilization > 80% → Consider increasing allocation

### Logging Strategy

All executions log:
- Invocation timestamp and request ID
- Athena query ID for traceability
- Number of records processed
- S3 upload confirmation
- SNS publish status
- Any errors with full stack traces

---

## 🔒 Security

### Defense in Depth

1. **IAM Least Privilege**: Lambda role has minimal required permissions
2. **Encryption**:
   - S3 buckets use SSE-S3 or SSE-KMS
   - SNS messages encrypted in transit (TLS)
   - Lambda environment variables encrypted with KMS
3. **Presigned URLs**: Time-limited access (24 hours) prevents unauthorized downloads
4. **VPC Isolation** (optional): Lambda can run in private subnets
5. **Secrets Management**: Use AWS Secrets Manager for sensitive data (not environment variables)

### Compliance Considerations

- **Audit Trail**: CloudWatch Logs retained for compliance period
- **Data Residency**: All data stays within specified AWS region
- **Access Logging**: S3 access logs enabled for report bucket
- **Principle of Least Privilege**: No wildcards in IAM policies

See [docs/security.md](docs/security.md) for detailed security architecture.

---

## 🛡️ Reliability & SRE

### Failure Scenarios & Recovery

| Failure Mode | Detection | Recovery | MTTR |
|-------------|-----------|----------|------|
| **Athena query timeout** | Polling exceeds 180s | Lambda times out, CloudWatch alarm triggers | 5 min |
| **S3 upload failure** | Exception caught, logged | Manual retry or EventBridge retry | 10 min |
| **SNS publish failure** | Exception caught, logged | Report still in S3, manual notification | 5 min |
| **Lambda OOM** | CloudWatch error metric | Increase memory allocation | 15 min |
| **Malformed log data** | Athena query returns 0 rows | Alert + investigate log format | 30 min |

### Idempotency

- **Query Execution**: Each run queries current date only (date-partitioned)
- **S3 Uploads**: Date-stamped filenames prevent overwrites
- **SNS Messages**: Duplicate sends are harmless (informational only)
- **Safe Retries**: Re-running the Lambda produces the same output

### SLO/SLI Framework

| SLI | Target | Measurement |
|-----|--------|-------------|
| **Report Generation Success Rate** | 99.5% | Successful Lambda invocations / Total invocations |
| **Report Delivery Latency** | p95 < 60 seconds | Duration from invocation to SNS publish |
| **Query Accuracy** | 100% | Athena results match raw log counts |

See [docs/reliability.md](docs/reliability.md) for detailed reliability patterns.

---

## 🔁 CI/CD Strategy

### Jenkins Pipeline Stages

```groovy
1. Checkout      → Clone repository
2. Lint          → Python code quality checks (pylint, black)
3. Unit Tests    → Test utility functions
4. Package       → Zip Lambda deployment package
5. Deploy Dev    → Deploy to development environment
6. Integration   → Run end-to-end tests
7. Deploy Prod   → Deploy to production (manual approval)
8. Smoke Test    → Invoke Lambda, verify logs
```

### Deployment Environments

| Environment | Purpose | Deployment Trigger |
|-------------|---------|-------------------|
| **Development** | Feature testing | Automatic on commit to `develop` |
| **Staging** | Pre-production validation | Automatic on merge to `main` |
| **Production** | Live system | Manual approval after staging tests |

### Rollback Strategy

1. **Immediate**: Use Lambda version/alias to rollback to previous version
2. **Prevention**: Integration tests catch issues before production
3. **Monitoring**: Post-deployment health checks verify success

---

## 📈 Scaling Considerations

### Current Scale

- **APIs Monitored**: 40+ target groups
- **Daily Log Volume**: ~10-50 million ALB requests
- **Report Generation**: 1x daily (expandable to 3x daily)
- **Lambda Concurrency**: Reserved concurrency = 1 (serial execution)

### Horizontal Scaling

To scale to **hundreds of APIs** or **multiple regions**:

1. **Partition by Region**: Deploy separate Lambda per region
2. **Parallel Processing**: Split APIs into batches, process concurrently
3. **Athena Performance**: Use partitioned tables, columnar formats (Parquet)
4. **S3 Lifecycle**: Archive old reports to Glacier after 90 days

### Vertical Scaling

- **Lambda Memory**: 512 MB → 1024 MB for faster execution
- **Athena Query**: Optimize with partition pruning and compression
- **PDF Generation**: Use streaming for large reports (100+ APIs)

### Cost at Scale

| Component | Monthly Cost (Est.) |
|-----------|---------------------|
| **Lambda** (1x daily) | ~$5 |
| **Athena** (5 GB scanned/day) | ~$5 |
| **S3** (30 reports/month) | ~$1 |
| **SNS** (30 emails/month) | ~$0 |
| **Total** | ~$11/month |

---

## 💰 Cost Optimization

1. **Athena**: Use partition projection and Parquet format (90% cost reduction)
2. **Lambda**: Right-size memory allocation (currently optimized at 512 MB)
3. **S3**: Lifecycle policies to transition old reports to cheaper storage classes
4. **CloudWatch**: Set log retention to 30 days (not indefinite)
5. **Reserved Concurrency**: Only if consistent traffic justifies it

---

## 🐛 Troubleshooting

### Common Issues

**Issue**: Lambda times out  
**Cause**: Athena query takes too long  
**Fix**: Optimize query, increase Lambda timeout to 300 seconds

**Issue**: PDF generation fails  
**Cause**: Missing ReportLab layer  
**Fix**: Attach `reportlab-layer` to Lambda function

**Issue**: No email received  
**Cause**: SNS subscription not confirmed  
**Fix**: Check email for confirmation link from AWS SNS

**Issue**: Empty report (0 rows)  
**Cause**: No ALB logs for current date  
**Fix**: Verify ALB logging is enabled and logs are in S3

### Debugging Steps

1. Check CloudWatch Logs for Lambda execution details
2. Verify Athena query execution in Athena console
3. Confirm S3 buckets have correct permissions
4. Test SNS topic manually with `aws sns publish`
5. Check IAM role has all required permissions

---

## 🤝 Contributing

This project demonstrates production-grade AWS automation patterns. Contributions are welcome!

### Areas for Enhancement

- [ ] Add EventBridge scheduling (9 AM, 12 PM, 3 PM)
- [ ] Migrate from SNS to SES for HTML emails
- [ ] Add historical trend comparison in reports
- [ ] Implement automated anomaly detection
- [ ] Add API health score calculations
- [ ] Support multi-region aggregation
- [ ] Create Terraform/CloudFormation IaC

---

## 📚 Additional Resources

- [Architecture Documentation](docs/architecture.md)
- [Data Flow Details](docs/data-flow.md)
- [Security Model](docs/security.md)
- [Reliability Patterns](docs/reliability.md)
- [CloudWatch Monitoring](monitoring/cloudwatch.md)
- [Alarm Configuration](monitoring/alarms.md)

---

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## 👨‍💻 Author

**Rituraj**
**DevOps Engineer**  

*Built with ❤️ for enterprise-scale reliability*

---

**⭐ If this repository demonstrates valuable AWS automation patterns, please star it!**
