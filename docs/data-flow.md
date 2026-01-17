# Data Flow Documentation

## Overview

This document provides a detailed walkthrough of how data flows through the ALB Observability Automation system, from raw ALB access logs to delivered PDF reports.

---

## Table of Contents

- [End-to-End Flow](#end-to-end-flow)
- [Phase 1: Log Collection](#phase-1-log-collection)
- [Phase 2: Cataloging and Indexing](#phase-2-cataloging-and-indexing)
- [Phase 3: Query Execution](#phase-3-query-execution)
- [Phase 4: Data Processing](#phase-4-data-processing)
- [Phase 5: Report Generation](#phase-5-report-generation)
- [Phase 6: Distribution](#phase-6-distribution)
- [Data Transformations](#data-transformations)
- [Error Handling Flow](#error-handling-flow)

---

## End-to-End Flow

### Visual Timeline

```
T+0min     │ ALB handles HTTP requests
           │ ↓
T+5min     │ ALB writes logs to S3
           │ ↓
T+10min    │ Glue crawler catalogs new partitions (optional/scheduled)
           │ ↓
9:00 AM    │ EventBridge triggers Lambda
           │ ↓
T+0s       │ Lambda starts execution
           │ ├─ [1] Submit Athena query
           │ │
T+2s       │ │  Athena starts query execution
           │ │  ├─ Parse SQL
           │ │  ├─ Plan query (partition pruning)
           │ │  └─ Execute across S3 data
           │ │
T+30s      │ │  Athena query completes
           │ │  └─ Write results to S3 (CSV format)
           │ │
           │ ├─ [2] Poll query status (every 2s)
           │ ├─ [3] Fetch CSV results from S3
           │ ├─ [4] Parse and aggregate data
           │ ├─ [5] Generate PDF (ReportLab)
           │ ├─ [6] Upload PDF to S3
           │ ├─ [7] Generate presigned URL
           │ └─ [8] Publish SNS notification
           │
T+40s      │ Lambda execution completes
           │ ↓
T+42s      │ Email delivered to subscribers
```

---

## Phase 1: Log Collection

### ALB to S3

**Trigger**: Every HTTP/HTTPS request handled by ALB

**Process**:
1. ALB processes request and generates log entry
2. Logs buffered in memory (up to 5 minutes or 5 MB)
3. ALB writes compressed log file to S3

**S3 Path Structure**:
```
s3://alb-logs-bucket/
  └── AWSLogs/
      └── <account-id>/
          └── elasticloadbalancing/
              └── <region>/
                  └── <year>/
                      └── <month>/
                          └── <day>/
                              └── <account-id>_elasticloadbalancing_<region>_<alb-id>_<timestamp>_<ip>.log.gz
```

**Log File Format**:
- **Compression**: GZIP
- **Size**: 1-100 KB compressed (10-1000 KB uncompressed)
- **Frequency**: Every 5 minutes
- **Encoding**: UTF-8

**Sample Log Entry**:
```
http 2026-01-17T09:15:23.456789Z app/my-alb/abc123 192.168.1.10:54321 
10.0.1.5:8080 0.001 0.023 0.000 200 200 1234 5678 
"GET https://api.example.com:443/v1/users HTTP/1.1" 
"Mozilla/5.0 (Windows NT 10.0; Win64; x64)" 
ECDHE-RSA-AES128-GCM-SHA256 TLSv1.2 
arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/api-service-1-tg/xyz789 
"Root=1-abc-123" "api.example.com" "arn:aws:acm:..." 
0 2026-01-17T09:15:23.433000Z "forward" "-" "-" "10.0.1.5:8080" "200" "-" "-"
```

---

## Phase 2: Cataloging and Indexing

### AWS Glue Data Catalog

**Purpose**: Create queryable metadata layer over S3 logs

**Cataloging Methods**:

#### Option A: Glue Crawler (Automated)
```
Glue Crawler (scheduled or on-demand)
  ↓
Scan S3 prefix: s3://alb-logs-bucket/AWSLogs/
  ↓
Infer schema from log files
  ↓
Create/update table in Glue Data Catalog
  ↓
Add partitions: year, month, day, region
```

**Crawler Schedule**: Daily at 6 AM (before report generation)

#### Option B: Partition Projection (Performance Optimized)
```sql
-- Table with partition projection enabled
CREATE EXTERNAL TABLE alb_log_partition_projection (
  type string,
  time string,
  elb string,
  client_ip string,
  target_ip string,
  request_processing_time double,
  target_processing_time double,
  response_processing_time double,
  elb_status_code int,
  target_status_code int,
  received_bytes bigint,
  sent_bytes bigint,
  request string,
  user_agent string,
  ssl_cipher string,
  ssl_protocol string,
  target_group_arn string,
  trace_id string
)
PARTITIONED BY (day string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.RegexSerDe'
LOCATION 's3://alb-logs-bucket/AWSLogs/<account-id>/elasticloadbalancing/<region>/'
TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.day.type' = 'date',
  'projection.day.format' = 'yyyy/MM/dd',
  'projection.day.range' = '2024/01/01,NOW',
  'storage.location.template' = 's3://alb-logs-bucket/AWSLogs/<account-id>/elasticloadbalancing/<region>/${day}'
);
```

**Benefit**: Athena automatically discovers partitions without crawlers

---

## Phase 3: Query Execution

### Athena Query Processing

**Step 1: Query Submission**
```python
response = athena.start_query_execution(
    QueryString=QUERY,
    QueryExecutionContext={'Database': 'alb_logs_database'},
    ResultConfiguration={'OutputLocation': 's3://athena-results/'}
)
query_execution_id = response['QueryExecutionId']
```

**Step 2: Query Planning** (Athena internal)
```
1. Parse SQL query
2. Validate table schema from Glue
3. Apply partition pruning:
   WHERE day = date_format(current_date, '%Y/%m/%d')
   → Only scan files in today's partition
4. Estimate data to scan: ~5-10 GB
5. Generate execution plan (Presto DAG)
```

**Step 3: Distributed Execution**
```
Athena Query Coordinator
  ↓
┌─────────────┬─────────────┬─────────────┐
│  Worker 1   │  Worker 2   │  Worker 3   │
│  (Scan S3)  │  (Scan S3)  │  (Scan S3)  │
│  Partition  │  Partition  │  Partition  │
│  00:00-08:00│  08:00-16:00│  16:00-23:59│
└──────┬──────┴──────┬──────┴──────┬──────┘
       │             │             │
       └─────────────┼─────────────┘
                     ↓
          Aggregation (GROUP BY)
                     ↓
             Sort (ORDER BY)
                     ↓
      Write to S3 (CSV format)
```

**Query Output Location**:
```
s3://athena-results-bucket/queries/<query-execution-id>.csv
s3://athena-results-bucket/queries/<query-execution-id>.csv.metadata
```

**Query Result Format** (CSV):
```csv
target_group_arn,elb_status_code,error_count
arn:aws:...targetgroup/api-service-1-tg/xyz,200,125430
arn:aws:...targetgroup/api-service-1-tg/xyz,400,234
arn:aws:...targetgroup/api-service-1-tg/xyz,500,12
arn:aws:...targetgroup/api-service-2-tg/abc,200,98765
...
```

**Performance Metrics**:
- Data scanned: 8.5 GB
- Execution time: 23.4 seconds
- Result size: 15 KB

---

## Phase 4: Data Processing

### Lambda Processing Logic

**Step 1: Poll Query Status**
```python
while waited < MAX_WAIT_SECONDS:
    status = athena.get_query_execution(QueryExecutionId=qid)
    state = status['QueryExecution']['Status']['State']
    
    if state == 'SUCCEEDED':
        break
    elif state in ('FAILED', 'CANCELLED'):
        raise RuntimeError(f"Query {state}")
    
    time.sleep(2)
    waited += 2
```

**Step 2: Fetch Results from S3**
```python
# Get S3 location from Athena metadata
output_location = athena.get_query_execution(...)['ResultConfiguration']['OutputLocation']
# Example: s3://athena-results/queries/abc-123-xyz.csv

# Download CSV
bucket, key = parse_s3_url(output_location)
csv_data = s3.get_object(Bucket=bucket, Key=key)['Body'].read()

# Parse CSV
rows = csv.DictReader(io.StringIO(csv_data.decode('utf-8')))
```

**Step 3: Aggregate Data**

**Input** (CSV rows):
```python
[
  {'target_group_arn': '...api-service-1-tg/...', 'elb_status_code': '200', 'error_count': '125430'},
  {'target_group_arn': '...api-service-1-tg/...', 'elb_status_code': '400', 'error_count': '234'},
  {'target_group_arn': '...api-service-1-tg/...', 'elb_status_code': '500', 'error_count': '12'},
  ...
]
```

**Processing**:
```python
report = {api: {'2xx': 0, '4xx': 0, '5xx': 0} for api in ALLOWED_APIS}

for row in rows:
    api = detect_api(row['target_group_arn'])  # Extract API name
    status = int(row['elb_status_code'])
    count = int(row['error_count'])
    
    if 200 <= status <= 214:
        report[api]['2xx'] += count
    elif 400 <= status <= 415:
        report[api]['4xx'] += count
    elif 500 <= status <= 515:
        report[api]['5xx'] += count
```

**Output** (aggregated):
```python
{
  'api-service-1': {'2xx': 125430, '4xx': 234, '5xx': 12},
  'api-service-2': {'2xx': 98765, '4xx': 123, '5xx': 0},
  'api-service-3': {'2xx': 234567, '4xx': 456, '5xx': 3},
  ...
}
```

---

## Phase 5: Report Generation

### PDF Creation with ReportLab

**Step 1: Initialize Document**
```python
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph

doc = SimpleDocTemplate(
    '/tmp/alb_api_status_report.pdf',
    pagesize=A4,
    rightMargin=30, leftMargin=30,
    topMargin=30, bottomMargin=30
)
```

**Step 2: Build Content**
```python
elements = []

# Header
elements.append(Paragraph("ALB API Status Report", title_style))
elements.append(Paragraph(f"Date: {date}", normal_style))

# Table
table_data = [['API Name', '2xx', '4xx', '5xx']]
for api, counts in report.items():
    table_data.append([
        api,
        f"{counts['2xx']:,}",
        f"{counts['4xx']:,}",
        f"{counts['5xx']:,}"
    ])

table = Table(table_data, colWidths=[230, 90, 110, 110])
table.setStyle(TableStyle([...]))
elements.append(table)
```

**Step 3: Generate PDF**
```python
doc.build(elements)  # Writes to /tmp/alb_api_status_report.pdf
```

**PDF File Details**:
- Size: 1-5 MB (depends on number of APIs)
- Pages: 1-3 pages for 40 APIs
- Format: PDF 1.4 (compatible with all readers)

---

## Phase 6: Distribution

### S3 Upload

**Upload PDF**:
```python
s3_key = f"alb-reports/alb_api_status_report_{date}.pdf"
s3.upload_file(
    '/tmp/alb_api_status_report.pdf',
    'report-storage-bucket',
    s3_key
)
```

**Generate Presigned URL**:
```python
presigned_url = s3.generate_presigned_url(
    ClientMethod='get_object',
    Params={'Bucket': 'report-storage-bucket', 'Key': s3_key},
    ExpiresIn=86400  # 24 hours
)
# Result: https://report-storage-bucket.s3.amazonaws.com/alb-reports/...
#         ?X-Amz-Algorithm=AWS4-HMAC-SHA256
#         &X-Amz-Credential=...
#         &X-Amz-Date=20260117T090000Z
#         &X-Amz-Expires=86400
#         &X-Amz-SignedHeaders=host
#         &X-Amz-Signature=...
```

### SNS Notification

**Build Message**:
```python
message = f"""
Daily ALB API Status Report
Date: {date}

=== SUMMARY ===
Total 2xx: {total_2xx:,}
Total 4xx: {total_4xx:,}
Total 5xx: {total_5xx:,}

Download PDF: {presigned_url}

Regards,
DevOps Team
"""
```

**Publish to SNS**:
```python
sns.publish(
    TopicArn='arn:aws:sns:us-east-1:123456789012:alb-reports',
    Subject=f'Daily ALB API Status Report | {date}',
    Message=message
)
```

**Email Delivery**:
```
SNS Topic
  ↓
SNS → SES (Email delivery service)
  ↓
┌─────────────────┐
│ Email Recipient │
│ engineer@ex.com │
└─────────────────┘
```

**Email Receipt Time**: 1-5 seconds after SNS publish

---

## Data Transformations

### Transformation Pipeline

```
Raw ALB Log (Space-delimited)
  ↓ [Athena SerDe: RegexSerDe]
Structured Row (Columns)
  ↓ [SQL: GROUP BY, SUM]
Aggregated Counts per Target Group
  ↓ [Lambda: detect_api()]
Aggregated Counts per API
  ↓ [Lambda: classify status codes]
Categorized Counts (2xx/4xx/5xx)
  ↓ [ReportLab: Table formatting]
Formatted PDF Table
```

### Data Volume at Each Stage

| Stage | Data Volume | Format |
|-------|-------------|--------|
| Raw logs (24h) | 20 GB compressed | GZIP text |
| Athena scan | 20 GB | Text (decompressed) |
| Query result | 15 KB | CSV |
| In-memory (Lambda) | 15 KB | Python dict |
| PDF report | 2 MB | PDF |

---

## Error Handling Flow

### Athena Query Failure

```
Athena Query Submitted
  ↓
Query Status: FAILED
  ↓
Lambda catches RuntimeError
  ↓
Log error to CloudWatch:
  "Athena query FAILED: Syntax error at line 5"
  ↓
Return error response:
  {"status": "error", "error_type": "QueryFailed"}
  ↓
CloudWatch Alarm triggered
  ↓
PagerDuty/Email notification to on-call engineer
```

### S3 Upload Failure

```
PDF Generated Successfully
  ↓
S3 Upload Attempted
  ↓
Exception: AccessDenied / NetworkError
  ↓
Lambda catches exception
  ↓
Log error + retry (exponential backoff)
  ↓
┌─ Retry 1: Wait 1s  → Success ✓
├─ Retry 2: Wait 2s
└─ Retry 3: Wait 4s  → Fail → Alert
```

### SNS Publish Failure

```
SNS Publish Attempted
  ↓
Exception: InvalidParameter / Throttling
  ↓
Lambda catches exception (non-blocking)
  ↓
Log warning:
  "SNS publish failed, but report available in S3"
  ↓
Return partial success:
  {"status": "success", "sns_status": "failed"}
  ↓
Manual notification sent (operator can share S3 link)
```

---

## Performance Optimization

### Bottleneck Analysis

| Phase | Duration | % of Total | Optimization Potential |
|-------|----------|------------|------------------------|
| Athena query | 20-30s | 60-70% | ✅ Use Parquet format |
| Query polling | 2-10s | 5-15% | ⚠️ Increase poll interval |
| CSV download | 1-2s | 3-5% | ✅ Use smaller result set |
| Data aggregation | 1-2s | 3-5% | ✅ Optimize Python loops |
| PDF generation | 2-5s | 5-10% | ⚠️ Acceptable |
| S3 upload | 1s | 2-3% | ✅ Use S3 Transfer Acceleration |
| SNS publish | 1s | 2-3% | ✅ No optimization needed |

### Optimization Strategies

1. **Convert logs to Parquet**: 10x faster Athena queries
2. **Partition pruning**: Only scan necessary dates
3. **Query result caching**: Reuse results for 1 hour (Athena feature)
4. **Lambda memory**: 512 MB is optimal (tested)

---

## Monitoring Data Flow

### CloudWatch Logs

**Structured Log Example**:
```json
{
  "timestamp": "2026-01-17T09:00:35.123Z",
  "request_id": "abc-123-xyz",
  "phase": "athena_query",
  "query_execution_id": "qid-456",
  "data_scanned_gb": 8.5,
  "duration_seconds": 23.4,
  "status": "success"
}
```

**Log Insights Queries**:
```sql
-- Average Athena query time
fields @timestamp, duration_seconds
| filter phase = "athena_query"
| stats avg(duration_seconds) as avg_duration by bin(5m)

-- Error rate
fields @timestamp
| filter status = "error"
| stats count() as errors by bin(1h)
```

---

## Data Retention Policies

| Data Type | Retention | Storage Class | Cost/Month |
|-----------|-----------|---------------|------------|
| Raw ALB logs | 365 days | S3 Standard → Glacier | $50 |
| Athena results | 7 days | S3 Standard | $1 |
| PDF reports | Indefinite | S3 Standard → IA (30d) | $10 |
| CloudWatch Logs | 30 days | CloudWatch | $5 |

---

**Document Version**: 1.0  
**Last Updated**: January 2026  
**Maintained By**: DevOps Engineering Team