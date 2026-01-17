# ALB API Status Report Automation

---

## 📋 Overview

This document describes the **ALB API Status Report** solution implemented in AWS.

### Solution Capabilities

The solution performs the following operations:

- ✅ Executes an Athena query on ALB logs
- ✅ Aggregates 2xx / 4xx / 5xx counts per API
- ✅ Generates a PDF report
- ✅ Uploads the PDF to Amazon S3
- ✅ Sends a plain-text notification via Amazon SNS with a summary and download link

> **Note:** Amazon SNS supports plain-text emails only (no HTML tables or attachments).

---

## 🎯 Scope

| Parameter | Value |
|-----------|-------|
| **Account** | Production AWS Account |
| **Region** | Your AWS Region |
| **Execution** | Manual / Lambda test invocation |
| **Notification** | Amazon SNS (Email – plain text) |

> ⚠️ **EventBridge scheduling is intentionally excluded for now.**

---

## 📊 Data Sources

The report aggregates ALB access data from the following Athena tables:

1. `alb_log_partition_projection`
2. `alb_access_logs_internal`

Both tables are queried for the current date and combined to produce a consolidated view.

---

## 🔍 Athena Query Used

```sql
SELECT 
    target_group_arn,
    elb_status_code,
    SUM(error_count) AS error_count
FROM (
    SELECT 
        target_group_arn,
        elb_status_code,
        COUNT(elb_status_code) AS error_count
    FROM alb_log_partition_projection
    WHERE day = date_format(current_date, '%Y/%m/%d')
    GROUP BY target_group_arn, elb_status_code

    UNION ALL

    SELECT 
        target_group_arn,
        elb_status_code,
        COUNT(elb_status_code) AS error_count
    FROM alb_access_logs_internal
    WHERE day = date_format(current_date, '%Y/%m/%d')
    GROUP BY target_group_arn, elb_status_code
) combined
GROUP BY target_group_arn, elb_status_code
ORDER BY target_group_arn, elb_status_code;
```

---

## 📈 Status Code Classification

| Category | Status Codes | Description |
|----------|-------------|-------------|
| **2xx** | 200–214 | Success responses |
| **4xx** | 400–415 | Client errors |
| **5xx** | 500–515 | Server errors |

> **Special Case:** Certain OAuth and view APIs optionally include 3xx (300–314) counts within the 2xx bucket, as per reporting requirements.

---

## ⚙️ Processing Flow

```
1. Lambda function is invoked manually (or via test trigger)
   ↓
2. Athena query runs on ALB log tables
   ↓
3. Results are parsed and aggregated API-wise
   ↓
4. A PDF report is generated in the Lambda /tmp directory
   ↓
5. PDF is uploaded to Amazon S3
   ↓
6. SNS email is sent with:
   • Subject line
   • Plain-text summary
   • S3 download link for the PDF
```

---

## 🏗️ Architecture

```
┌──────────────────────┐
│     AWS ALB          │
│   Access Logs        │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   Amazon S3          │
│   (ALB Logs)         │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   Amazon Athena      │
│   SQL Aggregation    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────┐
│   AWS Lambda Function        │
│   • Parse Athena output      │
│   • Compute 2xx/4xx/5xx      │
│   • Generate PDF report      │
└──────────┬───────────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌──────────┐  ┌───────────────────┐
│ S3 Bucket│  │  Amazon SNS       │
│  (PDF)   │  │  Plain-text Email │
└──────────┘  └───────────────────┘
```

---

## 📧 SNS Email Format

### Subject

```
ALB API Status Report – <YYYY-MM-DD>
```

### Body (Plain Text)

```
ALB API STATUS REPORT
Date: <YYYY-MM-DD>

API-wise Summary (2xx / 4xx / 5xx):

api-service-1
  2xx: 1866
  4xx: 630
  5xx: 0

api-service-2
  2xx: 1676
  4xx: 65
  5xx: 0

Download full PDF report:
https://<your-bucket>.s3.amazonaws.com/<key>

Regards
DevOps Team
```

---

## 🗂️ S3 Artifacts

| Property | Value |
|----------|-------|
| **Bucket** | `<your-bucket-name>` |
| **Prefix** | `alb-reports/` |
| **File Type** | PDF |
| **Naming Convention** | `alb_api_report_<YYYY-MM-DD>.pdf` |

---

## 🔐 IAM Permissions (Summary)

The Lambda execution role includes permissions for:

| Service | Permissions |
|---------|-------------|
| **Amazon Athena** | Query execution and result retrieval |
| **AWS Glue** | Metadata access for Athena |
| **Amazon S3** | Read query output, upload PDF |
| **Amazon SNS** | Publish plain-text notifications |

---

## ⚠️ Known Limitations

| Limitation | Description |
|------------|-------------|
| **SNS emails are plain text only** | No inline tables or attachments supported |
| **PDF access** | Depends on S3 permissions |
| **Manual execution** | No automated scheduling currently |

---

## 🚀 Future Enhancements

- [ ] Add EventBridge scheduling (9 AM / 12 PM / 3 PM IST)
- [ ] Switch to Amazon SES for HTML emails and inline tables
- [ ] Attach PDF directly via SES
- [ ] Add historical trend comparison
- [ ] Implement automated alerting for anomalies
- [ ] Add API health score metrics

---

## 👥 Ownership

| Property | Value |
|----------|-------|
| **Environment** | Production |
| **Maintained By** | DevOps Team |
| **Purpose** | Operational visibility and audit reference |

---

**Document Version:** 1.0  
**Last Updated:** January 2026  
**Status:** ✅ Active
