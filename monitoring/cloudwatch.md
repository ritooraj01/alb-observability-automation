# CloudWatch Monitoring

## Overview

This document describes the CloudWatch monitoring strategy for the ALB Observability Automation system, including metrics, dashboards, log queries, and performance analysis.

## Table of Contents

- [Lambda Metrics](#lambda-metrics)
- [Custom Metrics](#custom-metrics)
- [CloudWatch Dashboards](#cloudwatch-dashboards)
- [Log Insights Queries](#log-insights-queries)
- [Performance Monitoring](#performance-monitoring)
- [Cost Monitoring](#cost-monitoring)

---

## Lambda Metrics

### Standard Lambda Metrics

AWS Lambda automatically publishes metrics to CloudWatch:

| Metric | Description | Unit | Typical Value |
|--------|-------------|------|---------------|
| **Invocations** | Number of times function is invoked | Count | 1/day |
| **Errors** | Number of invocations that result in a function error | Count | 0 |
| **Throttles** | Number of invocation attempts that were throttled | Count | 0 |
| **Duration** | Elapsed time from invocation to completion | Milliseconds | 30000-60000 |
| **ConcurrentExecutions** | Number of function instances processing events | Count | 1 |
| **IteratorAge** | (For stream-based invocations) | Milliseconds | N/A |

### Lambda Metric Queries

**Average Duration (Last 7 Days)**:
```
SELECT AVG(Duration)
FROM "AWS/Lambda"
WHERE FunctionName = 'alb-status-report'
GROUP BY FunctionName
```

**Error Rate (%)**:
```
SELECT (SUM(Errors) / SUM(Invocations)) * 100 AS ErrorRate
FROM "AWS/Lambda"
WHERE FunctionName = 'alb-status-report'
```

**p95 Duration**:
```
SELECT PERCENTILE(Duration, 95) AS p95_duration
FROM "AWS/Lambda"
WHERE FunctionName = 'alb-status-report'
```

---

## Custom Metrics

### Publishing Custom Metrics

Publish custom metrics from Lambda using CloudWatch Logs embedded metric format:

```python
import json
import logging

logger = logging.getLogger()

def publish_custom_metric(metric_name, value, unit='None'):
    """Publish custom metric using EMF (Embedded Metric Format)"""
    metric_data = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "ALB/ObservabilityAutomation",
                    "Dimensions": [["FunctionName"]],
                    "Metrics": [
                        {
                            "Name": metric_name,
                            "Unit": unit
                        }
                    ]
                }
            ]
        },
        "FunctionName": "alb-status-report",
        metric_name: value
    }
    
    # Log in EMF format
    logger.info(json.dumps(metric_data))

# Usage in Lambda handler
publish_custom_metric("AthenaQueryDuration", 23.4, "Seconds")
publish_custom_metric("TotalRequestsProcessed", 1234567, "Count")
publish_custom_metric("PDFSizeBytes", 2456789, "Bytes")
```

### Recommended Custom Metrics

| Metric | Description | Unit | Purpose |
|--------|-------------|------|--------|
| **AthenaQueryDuration** | Time taken for Athena query | Seconds | Performance tracking |
| **AthenaDataScannedGB** | Amount of data scanned by Athena | Gigabytes | Cost monitoring |
| **TotalRequestsProcessed** | Total ALB requests in report | Count | Data volume tracking |
| **PDFSizeBytes** | Size of generated PDF | Bytes | Storage monitoring |
| **S3UploadDuration** | Time to upload PDF to S3 | Seconds | Performance tracking |
| **SNSPublishSuccess** | Success/failure of SNS publish | Count | Reliability tracking |
| **EmptyReportGenerated** | Report with 0 data points | Count | Data quality monitoring |

---

## CloudWatch Dashboards

### Main Dashboard: `ALB-Observability-Overview`

Create a comprehensive dashboard using AWS CLI or Console:

```bash
aws cloudwatch put-dashboard \
  --dashboard-name ALB-Observability-Overview \
  --dashboard-body file://dashboard.json
```

**dashboard.json**:
```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "title": "Lambda Invocations",
        "metrics": [
          [ "AWS/Lambda", "Invocations", { "stat": "Sum", "label": "Total" } ],
          [ ".", "Errors", { "stat": "Sum", "label": "Errors", "color": "#d62728" } ]
        ],
        "period": 300,
        "stat": "Sum",
        "region": "us-east-1",
        "yAxis": { "left": { "min": 0 } }
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Lambda Duration (p50, p95, p99)",
        "metrics": [
          [ "AWS/Lambda", "Duration", { "stat": "p50" } ],
          [ "...", { "stat": "p95", "color": "#ff7f0e" } ],
          [ "...", { "stat": "p99", "color": "#d62728" } ]
        ],
        "period": 300,
        "region": "us-east-1",
        "yAxis": { "left": { "label": "Milliseconds" } }
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Athena Query Performance",
        "metrics": [
          [ "ALB/ObservabilityAutomation", "AthenaQueryDuration", { "stat": "Average" } ],
          [ ".", "AthenaDataScannedGB", { "stat": "Sum", "yAxis": "right" } ]
        ],
        "period": 86400,
        "region": "us-east-1",
        "yAxis": {
          "left": { "label": "Seconds" },
          "right": { "label": "GB Scanned" }
        }
      }
    },
    {
      "type": "log",
      "properties": {
        "title": "Recent Lambda Executions",
        "query": "SOURCE '/aws/lambda/alb-status-report'\n| fields @timestamp, @message\n| filter @message like /Report generation/\n| sort @timestamp desc\n| limit 20",
        "region": "us-east-1"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Request Volume Processed",
        "metrics": [
          [ "ALB/ObservabilityAutomation", "TotalRequestsProcessed", { "stat": "Sum" } ]
        ],
        "period": 86400,
        "stat": "Sum",
        "region": "us-east-1",
        "yAxis": { "left": { "label": "Requests" } }
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Memory Utilization",
        "metrics": [
          [ "AWS/Lambda", "MemoryUtilization", { "stat": "Average" } ]
        ],
        "annotations": {
          "horizontal": [
            {
              "value": 90,
              "label": "High Memory Warning",
              "color": "#d62728"
            }
          ]
        },
        "period": 300,
        "region": "us-east-1",
        "yAxis": { "left": { "min": 0, "max": 100, "label": "Percent" } }
      }
    }
  ]
}
```

### Dashboard Best Practices

✅ **Include both metrics and logs** for complete visibility  
✅ **Use annotations** to mark thresholds and SLO targets  
✅ **Group related metrics** together in rows  
✅ **Set appropriate time ranges** (last 3 hours for real-time, last 7 days for trends)  
✅ **Add text widgets** with runbook links and troubleshooting steps  

---

## Log Insights Queries

### Useful Queries

**1. Average Execution Time by Phase**
```sql
fields @timestamp, @message
| filter @message like /duration/
| parse @message /(?<phase>\w+) completed in (?<duration>[\d.]+)s/
| stats avg(duration) as avg_duration by phase
| sort avg_duration desc
```

**2. Error Analysis**
```sql
fields @timestamp, @message
| filter @message like /ERROR/ or @message like /Exception/
| stats count() as error_count by bin(1h)
| sort @timestamp desc
```

**3. Athena Query Statistics**
```sql
fields @timestamp, @message
| filter @message like /Athena query/
| parse @message /Data scanned: (?<data_gb>[\d.]+) GB/
| parse @message /Duration: (?<duration>[\d.]+)s/
| stats avg(data_gb) as avg_data_gb, avg(duration) as avg_duration, max(duration) as max_duration
```

**4. Daily Report Summary**
```sql
fields @timestamp, @message
| filter @message like /Report generation completed/
| parse @message /Total requests: (?<requests>\d+)/
| stats sum(requests) as total_requests by bin(1d)
| sort @timestamp desc
```

**5. Cold Start Analysis**
```sql
fields @timestamp, @duration
| filter @type = "REPORT"
| stats avg(@duration) as avg_duration, count() as invocations by @initDuration
| sort invocations desc
```

**6. Memory Usage Trends**
```sql
fields @timestamp, @maxMemoryUsed, @memorySize
| filter @type = "REPORT"
| stats avg(@maxMemoryUsed / @memorySize * 100) as memory_pct by bin(1h)
| sort @timestamp desc
```

### Scheduled Queries

Schedule Log Insights queries to run daily and export results:

```bash
aws logs start-query \
  --log-group-name /aws/lambda/alb-status-report \
  --start-time $(date -d '24 hours ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields @timestamp, @message | filter @message like /ERROR/' \
  --limit 1000
```

---

## Performance Monitoring

### Key Performance Indicators

| KPI | Target | Alert Threshold |
|-----|--------|-----------------|
| **Lambda Duration (p95)** | < 60 seconds | > 240 seconds |
| **Lambda Duration (p99)** | < 90 seconds | > 270 seconds |
| **Athena Query Duration** | < 30 seconds | > 120 seconds |
| **Cold Start Duration** | < 5 seconds | > 10 seconds |
| **Error Rate** | 0% | > 1% |
| **Memory Utilization** | 60-80% | > 90% |

### Performance Optimization Checklist

- [ ] Monitor Lambda duration trends (identify spikes)
- [ ] Review Athena data scanned (optimize queries to reduce cost)
- [ ] Check cold start frequency (consider provisioned concurrency)
- [ ] Analyze memory utilization (right-size Lambda memory)
- [ ] Review error logs (fix recurring issues)

---

## Cost Monitoring

### Cost Metrics

**Lambda Costs**:
```
Cost = (Invocations × Duration × Memory) × Price

Example:
- Invocations: 30/month
- Duration: 40 seconds average
- Memory: 512 MB
- Cost: ~$0.02/month
```

**Athena Costs**:
```
Cost = Data Scanned (GB) × $5/TB

Example:
- Data Scanned: 10 GB/day
- Monthly: 300 GB
- Cost: 300 GB × $0.005/GB = $1.50/month
```

### Cost Optimization Strategies

1. **Reduce Athena Data Scanned**:
   - Use Parquet format (90% reduction)
   - Partition pruning (only scan needed dates)
   - Column selection (SELECT only required columns)

2. **Optimize Lambda Duration**:
   - Increase memory (faster CPU = shorter duration)
   - Cache Athena query results
   - Optimize PDF generation

3. **Right-Size Resources**:
   - Monitor memory utilization
   - Adjust Lambda memory allocation
   - Use Lambda layers for dependencies

---

## Monitoring Best Practices

✅ **Set up alarms for critical metrics** (errors, duration, throttles)  
✅ **Review CloudWatch dashboards weekly** for trends  
✅ **Analyze Log Insights queries monthly** for performance optimization  
✅ **Monitor costs** to prevent budget overruns  
✅ **Test alerting** to ensure notifications reach on-call engineers  
✅ **Document runbooks** for common issues  

---

## References

- [AWS Lambda Metrics and Dimensions](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics.html)
- [CloudWatch Logs Insights Query Syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)
- [Embedded Metric Format](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format.html)

---

**Document Version**: 1.0  
**Last Updated**: January 2026  
**Maintained By**: DevOps Engineering Team