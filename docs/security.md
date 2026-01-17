# Security Documentation

## Overview

This document outlines the security architecture, controls, and best practices implemented in the ALB Observability Automation system.

## Table of Contents

- [Security Principles](#security-principles)
- [IAM and Access Control](#iam-and-access-control)
- [Data Protection](#data-protection)
- [Network Security](#network-security)
- [Audit and Compliance](#audit-and-compliance)
- [Threat Model](#threat-model)
- [Security Checklist](#security-checklist)

---

## Security Principles

### Defense in Depth

Multiple layers of security controls:
1. **Identity**: IAM roles with least privilege
2. **Infrastructure**: VPC isolation (optional)
3. **Data**: Encryption at rest and in transit
4. **Application**: Input validation and error handling
5. **Monitoring**: CloudWatch logging and alerting

### Principle of Least Privilege

Every component has only the minimum permissions required:
- Lambda can only read from specific S3 buckets
- Lambda can only execute queries in specific Athena database
- SNS topic has limited publishing permissions

### Zero Trust

- No hard-coded credentials
- All access authenticated and authorized
- Continuous monitoring and logging

---

## IAM and Access Control

### Lambda Execution Role

**Role Name**: `alb-status-report-lambda-role`

**Trust Policy**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Permission Policy** (Least Privilege):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AthenaQueryExecution",
      "Effect": "Allow",
      "Action": [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults"
      ],
      "Resource": [
        "arn:aws:athena:*:*:workgroup/primary"
      ]
    },
    {
      "Sid": "GlueDataCatalogAccess",
      "Effect": "Allow",
      "Action": [
        "glue:GetDatabase",
        "glue:GetTable",
        "glue:GetPartitions"
      ],
      "Resource": [
        "arn:aws:glue:*:*:catalog",
        "arn:aws:glue:*:*:database/alb_logs_database",
        "arn:aws:glue:*:*:table/alb_logs_database/*"
      ]
    },
    {
      "Sid": "S3ReadALBLogs",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::alb-logs-bucket",
        "arn:aws:s3:::alb-logs-bucket/*"
      ]
    },
    {
      "Sid": "S3ReadWriteAthenaResults",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::athena-results-bucket/*"
      ]
    },
    {
      "Sid": "S3WriteReports",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl"
      ],
      "Resource": [
        "arn:aws:s3:::report-storage-bucket/alb-reports/*"
      ],
      "Condition": {
        "StringEquals": {
          "s3:x-amz-server-side-encryption": "AES256"
        }
      }
    },
    {
      "Sid": "SNSPublish",
      "Effect": "Allow",
      "Action": [
        "sns:Publish"
      ],
      "Resource": [
        "arn:aws:sns:*:*:alb-api-status-reports"
      ]
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": [
        "arn:aws:logs:*:*:log-group:/aws/lambda/alb-status-report:*"
      ]
    }
  ]
}
```

**Key Security Features**:
- ✅ No wildcard (`*`) resources where possible
- ✅ Specific actions only (no `s3:*` or `athena:*`)
- ✅ Condition keys enforce encryption
- ✅ Scoped to specific S3 prefixes

### S3 Bucket Policies

**ALB Logs Bucket**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ALBLogDelivery",
      "Effect": "Allow",
      "Principal": {
        "Service": "elasticloadbalancing.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::alb-logs-bucket/*"
    },
    {
      "Sid": "DenyUnencryptedObjectUploads",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::alb-logs-bucket/*",
      "Condition": {
        "StringNotEquals": {
          "s3:x-amz-server-side-encryption": "AES256"
        }
      }
    },
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": "arn:aws:s3:::alb-logs-bucket/*",
      "Condition": {
        "Bool": {
          "aws:SecureTransport": "false"
        }
      }
    }
  ]
}
```

**Report Storage Bucket**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyPublicAccess",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::report-storage-bucket/*",
      "Condition": {
        "StringNotEquals": {
          "aws:PrincipalAccount": "123456789012"
        }
      }
    }
  ]
}
```

---

## Data Protection

### Encryption at Rest

| Component | Encryption Method | Key Management |
|-----------|-------------------|----------------|
| **S3 Buckets** | SSE-S3 (AES-256) | AWS managed |
| **S3 Buckets (sensitive)** | SSE-KMS | Customer managed CMK |
| **Athena Query Results** | SSE-S3 | AWS managed |
| **Lambda Environment Variables** | KMS | AWS managed |
| **CloudWatch Logs** | AES-256 | AWS managed |

**S3 Encryption Configuration**:
```bash
# Enable default encryption
aws s3api put-bucket-encryption \
  --bucket report-storage-bucket \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'
```

**KMS Key Policy** (for sensitive data):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Enable IAM User Permissions",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::123456789012:root"
      },
      "Action": "kms:*",
      "Resource": "*"
    },
    {
      "Sid": "Allow Lambda to use the key",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::123456789012:role/alb-status-report-lambda-role"
      },
      "Action": [
        "kms:Decrypt",
        "kms:GenerateDataKey"
      ],
      "Resource": "*"
    }
  ]
}
```

### Encryption in Transit

- **ALB Logs to S3**: HTTPS (TLS 1.2+)
- **Athena Queries**: HTTPS (TLS 1.2+)
- **S3 API Calls**: HTTPS enforced via bucket policy
- **SNS Messages**: TLS 1.2+ (AWS managed)
- **Presigned URLs**: HTTPS only

**Enforce HTTPS** (S3 Bucket Policy):
```json
{
  "Sid": "DenyInsecureTransport",
  "Effect": "Deny",
  "Principal": "*",
  "Action": "s3:*",
  "Resource": [
    "arn:aws:s3:::report-storage-bucket",
    "arn:aws:s3:::report-storage-bucket/*"
  ],
  "Condition": {
    "Bool": {
      "aws:SecureTransport": "false"
    }
  }
}
```

### Data Classification

| Data Type | Classification | Retention | Encryption |
|-----------|---------------|-----------|------------|
| ALB Logs | Internal | 365 days | SSE-S3 |
| Athena Results | Internal | 7 days | SSE-S3 |
| PDF Reports | Internal | Indefinite | SSE-S3 |
| CloudWatch Logs | Internal | 30 days | AWS managed |
| Presigned URLs | Temporary | 24 hours | N/A (time-limited) |

**No PII/PHI** in this system. If logs contain sensitive data:
- Use SSE-KMS encryption
- Enable S3 Object Lock for compliance
- Implement VPC endpoints to avoid internet exposure

---

## Network Security

### VPC Deployment (Optional)

For enhanced security, deploy Lambda in a private VPC:

```
┌─────────────────────────────────────┐
│            AWS VPC                  │
│                                     │
│  ┌─────────────────────────────┐   │
│  │  Private Subnet (AZ-A)      │   │
│  │  └─ Lambda Function         │   │
│  └─────────────────────────────┘   │
│                                     │
│  ┌─────────────────────────────┐   │
│  │  Private Subnet (AZ-B)      │   │
│  │  └─ Lambda Function (HA)    │   │
│  └─────────────────────────────┘   │
│                                     │
│  ┌─────────────────────────────┐   │
│  │  VPC Endpoints              │   │
│  │  ├─ S3 Gateway Endpoint     │   │
│  │  ├─ Athena Interface EP     │   │
│  │  └─ SNS Interface EP        │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

**Benefits**:
- Traffic stays within AWS network (no internet exposure)
- Fine-grained security group controls
- Network flow logs for forensics

**Lambda VPC Configuration**:
```python
{
  "VpcConfig": {
    "SubnetIds": [
      "subnet-abc123",
      "subnet-def456"
    ],
    "SecurityGroupIds": [
      "sg-lambda-alb-reporter"
    ]
  }
}
```

**Security Group Rules**:
```bash
# Outbound (Lambda → AWS Services)
Type: HTTPS, Protocol: TCP, Port: 443, Destination: 0.0.0.0/0
# Required for S3, Athena, SNS via VPC endpoints

# Inbound: NONE (Lambda does not receive inbound traffic)
```

### VPC Endpoints

**S3 Gateway Endpoint** (no cost):
```json
{
  "ServiceName": "com.amazonaws.us-east-1.s3",
  "RouteTableIds": ["rtb-abc123"],
  "PolicyDocument": {
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": "*",
        "Action": [
          "s3:GetObject",
          "s3:PutObject"
        ],
        "Resource": "*"
      }
    ]
  }
}
```

**Athena Interface Endpoint** ($0.01/hour):
- Reduces latency
- Avoids data transfer charges

---

## Audit and Compliance

### CloudTrail Logging

**Enabled Events**:
- All IAM API calls
- S3 bucket-level operations (PutBucketPolicy, etc.)
- Lambda function updates
- Athena query executions
- SNS topic modifications

**CloudTrail Configuration**:
```json
{
  "Name": "management-events-trail",
  "S3BucketName": "cloudtrail-logs-bucket",
  "IncludeGlobalServiceEvents": true,
  "IsMultiRegionTrail": true,
  "EnableLogFileValidation": true
}
```

**Key Events to Monitor**:
- `AssumeRole` (Lambda execution role)
- `PutObject` (report uploads)
- `GetObject` (presigned URL access)
- `Publish` (SNS notifications)

### S3 Access Logging

**Enable Access Logs**:
```bash
aws s3api put-bucket-logging \
  --bucket report-storage-bucket \
  --bucket-logging-status '{
    "LoggingEnabled": {
      "TargetBucket": "s3-access-logs-bucket",
      "TargetPrefix": "report-storage-bucket/"
    }
  }'
```

**Log Format**:
```
bucket-owner canonical-user-id [time] remote-ip requester operation key 
"request-uri" http-status error-code bytes-sent object-size total-time 
turnaround-time "referrer" "user-agent" version-id
```

**Use Cases**:
- Audit presigned URL usage
- Detect unauthorized access attempts
- Compliance reporting

### Compliance Frameworks

| Framework | Requirement | Implementation |
|-----------|-------------|----------------|
| **GDPR** | Data retention policies | S3 lifecycle rules (delete after X days) |
| **HIPAA** | Encryption at rest and in transit | SSE-S3 + HTTPS enforced |
| **SOC 2** | Access logging and monitoring | CloudTrail + S3 access logs |
| **PCI DSS** | Least privilege access | IAM policies with minimal permissions |

---

## Threat Model

### Potential Threats and Mitigations

| Threat | Risk Level | Mitigation |
|--------|-----------|------------|
| **Unauthorized S3 access** | High | IAM policies + bucket policies + encryption |
| **Lambda code injection** | Medium | No user input in SQL queries (parameterized) |
| **Presigned URL leakage** | Medium | 24-hour expiry + CloudWatch monitoring |
| **SNS topic abuse** | Low | Topic policy restricts publishers |
| **Lambda timeout/DOS** | Low | Reserved concurrency = 1 |
| **Data exfiltration** | Medium | S3 VPC endpoint + CloudTrail monitoring |

### Attack Scenarios

#### Scenario 1: Malicious presigned URL sharing

**Attack**: Engineer shares presigned URL on public forum

**Impact**: Unauthorized users can download report for 24 hours

**Mitigation**:
- ✅ Presigned URLs expire after 24 hours
- ✅ S3 access logs track all downloads
- ✅ CloudWatch alarm on unusual download patterns
- ✅ Employee security training

#### Scenario 2: Compromised IAM credentials

**Attack**: Lambda execution role credentials stolen

**Impact**: Attacker can execute Athena queries and upload files

**Mitigation**:
- ✅ IAM role has least-privilege permissions
- ✅ CloudTrail logs all API calls
- ✅ GuardDuty detects anomalous API activity
- ✅ Lambda code signed (future enhancement)

#### Scenario 3: SQL injection in Athena query

**Attack**: Attacker modifies query to exfiltrate data

**Impact**: Low (query is hard-coded, no user input)

**Mitigation**:
- ✅ Query is static (no parameterization from user input)
- ✅ Lambda cannot modify queries dynamically
- ✅ Athena workgroup limits data scanned

---

## Security Checklist

### Pre-Deployment

- [ ] IAM role has least-privilege permissions
- [ ] S3 buckets have encryption enabled
- [ ] S3 bucket policies deny insecure transport
- [ ] CloudTrail logging enabled
- [ ] Lambda environment variables encrypted (KMS)
- [ ] SNS topic access policy configured
- [ ] VPC deployment considered (if required)

### Post-Deployment

- [ ] Test presigned URL expiry (should fail after 24 hours)
- [ ] Verify S3 access logs are being generated
- [ ] Confirm CloudWatch logs contain no sensitive data
- [ ] Run `aws iam simulate-policy` to verify least privilege
- [ ] Enable GuardDuty for threat detection
- [ ] Set up CloudWatch alarms for security events

### Ongoing

- [ ] Monthly IAM policy review
- [ ] Quarterly access log audits
- [ ] Annual penetration testing
- [ ] Rotate KMS keys (if using SSE-KMS)
- [ ] Update Lambda runtime (security patches)

---

## Security Incident Response

### Suspected Data Breach

**Steps**:
1. **Isolate**: Revoke IAM role permissions immediately
2. **Investigate**: Review CloudTrail and S3 access logs
3. **Notify**: Inform security team and stakeholders
4. **Remediate**: Rotate credentials, patch vulnerabilities
5. **Document**: Post-incident report

**Contact**: security@example.com

### Unauthorized Access Detected

**CloudWatch Alarm**:
```json
{
  "MetricName": "UnauthorizedS3Access",
  "Threshold": 5,
  "ComparisonOperator": "GreaterThanThreshold",
  "AlarmActions": ["arn:aws:sns:...:security-alerts"]
}
```

**Response**:
- Check S3 access logs for source IP
- Block IP at WAF/ALB level
- Invalidate presigned URLs (delete objects if needed)

---

## References

- [AWS Well-Architected Security Pillar](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html)
- [AWS IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [S3 Security Best Practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)

---

**Document Version**: 1.0  
**Last Updated**: January 2026  
**Maintained By**: Security Engineering Team
