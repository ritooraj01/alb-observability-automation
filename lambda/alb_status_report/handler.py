"""
ALB Status Report Lambda Function

This Lambda function automates the generation of daily Application Load Balancer (ALB)
status reports by:
1. Querying ALB access logs via Amazon Athena
2. Aggregating status codes (2xx/4xx/5xx) per API
3. Generating a professional PDF report
4. Uploading the report to S3
5. Sending email notifications via SNS

Author: DevOps Team
Version: 2.0
Python: 3.11+
"""

import boto3
import csv
import io
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ================= LOGGING CONFIGURATION ================= #

# Configure structured logging for CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create formatter for structured logs
formatter = logging.Formatter(
    '%(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s'
)

# Configure handler
if logger.handlers:
    for handler in logger.handlers:
        handler.setFormatter(formatter)
else:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ================= CONFIGURATION ================= #

# Athena configuration from environment variables
DATABASE = os.environ.get("ATHENA_DB", "alb_logs_database")
OUTPUT_S3 = os.environ.get("ATHENA_OUTPUT", "s3://athena-results-bucket/queries/")

# AWS configuration
REGION = os.environ.get("AWS_REGION", "us-east-1")
MAX_WAIT_SECONDS = int(os.environ.get("MAX_WAIT_SECONDS", "180"))

# S3 configuration for PDF reports
PDF_BUCKET = os.environ.get("PDF_BUCKET", "report-storage-bucket")
PDF_PREFIX = os.environ.get("PDF_PREFIX", "alb-reports")

# SNS configuration
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")

# ---------------- API CONFIGURATION ---------------- #

# List of APIs to monitor (configurable via environment variable)
ALLOWED_APIS = os.environ.get(
    "ALLOWED_APIS",
    "api-service-1,api-service-2,api-service-3,api-gateway-prod,api-gateway-staging"
).split(",")

# APIs that should include 3xx status codes in the 2xx bucket
# (e.g., OAuth redirects, SSO flows)
INCLUDE_3XX_APIS = set(
    os.environ.get("INCLUDE_3XX_APIS", "").split(",")
) if os.environ.get("INCLUDE_3XX_APIS") else set()

# Mapping of API names to target group identifiers
# Format: {api_name: target_group_identifier}
API_TG_MAP = {api.strip(): f"{api.strip()}-tg" for api in ALLOWED_APIS}

# ---------------- AWS CLIENT INITIALIZATION ---------------- #

try:
    athena = boto3.client("athena", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)
    sns = boto3.client("sns", region_name=REGION)
    logger.info("AWS clients initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize AWS clients: {str(e)}")
    raise

# ---------------- ATHENA SQL QUERY ---------------- #

# This query aggregates ALB status codes from multiple log tables
# It combines data from partition-projected and standard ALB log tables
QUERY = """
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
"""

# ================= HELPER FUNCTIONS ================= #

def run_athena_query() -> str:
    """
    Execute Athena query to aggregate ALB status codes.
    
    Returns:
        str: Query execution ID for tracking
        
    Raises:
        Exception: If query submission fails
    """
    try:
        logger.info(f"Starting Athena query execution in database: {DATABASE}")
        response = athena.start_query_execution(
            QueryString=QUERY,
            QueryExecutionContext={"Database": DATABASE},
            ResultConfiguration={"OutputLocation": OUTPUT_S3}
        )
        query_execution_id = response["QueryExecutionId"]
        logger.info(f"Athena query started successfully. Execution ID: {query_execution_id}")
        return query_execution_id
    except Exception as e:
        logger.error(f"Failed to start Athena query: {str(e)}")
        raise


def wait_for_query(query_execution_id: str) -> None:
    """
    Poll Athena query status until completion or timeout.
    
    Args:
        query_execution_id: The Athena query execution ID
        
    Raises:
        RuntimeError: If query fails or is cancelled
        TimeoutError: If query exceeds MAX_WAIT_SECONDS
    """
    waited = 0
    poll_interval = 2  # seconds
    
    logger.info(f"Waiting for query {query_execution_id} to complete (max {MAX_WAIT_SECONDS}s)")
    
    while waited < MAX_WAIT_SECONDS:
        try:
            status_response = athena.get_query_execution(QueryExecutionId=query_execution_id)
            state = status_response["QueryExecution"]["Status"]["State"]
            
            logger.debug(f"Query state: {state}, waited: {waited}s")

            if state == "SUCCEEDED":
                logger.info(f"Query completed successfully after {waited}s")
                return

            if state in ("FAILED", "CANCELLED"):
                reason = status_response["QueryExecution"]["Status"].get(
                    "StateChangeReason", "Unknown reason"
                )
                error_msg = f"Athena query {state}: {reason}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            time.sleep(poll_interval)
            waited += poll_interval
            
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Error checking query status: {str(e)}")
            raise

    error_msg = f"Athena query timed out after {MAX_WAIT_SECONDS} seconds"
    logger.error(error_msg)
    raise TimeoutError(error_msg)


def fetch_csv(query_execution_id: str) -> csv.DictReader:
    """
    Download and parse Athena query results from S3.
    
    Args:
        query_execution_id: The Athena query execution ID
        
    Returns:
        csv.DictReader: Iterator over query result rows
        
    Raises:
        Exception: If results cannot be fetched or parsed
    """
    try:
        # Get the S3 location of query results
        meta = athena.get_query_execution(QueryExecutionId=query_execution_id)
        output_location = meta["QueryExecution"]["ResultConfiguration"]["OutputLocation"]
        
        logger.info(f"Fetching query results from: {output_location}")
        
        # Parse S3 URL
        bucket, key = output_location.replace("s3://", "").split("/", 1)
        
        # Download results from S3
        response = s3.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()
        
        # Parse CSV data
        csv_reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
        
        logger.info("Query results fetched and parsed successfully")
        return csv_reader
        
    except Exception as e:
        logger.error(f"Failed to fetch or parse query results: {str(e)}")
        raise


def detect_api(target_group_arn: str) -> Optional[str]:
    """
    Extract API name from ALB target group ARN.
    
    Args:
        target_group_arn: Full ARN of the target group
        
    Returns:
        str: API name if matched, None otherwise
        
    Example:
        Input: "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/api-service-1-tg/abc123"
        Output: "api-service-1"
    """
    for api, tg_identifier in API_TG_MAP.items():
        if f"/{tg_identifier}/" in target_group_arn:
            return api
    return None


def aggregate(rows: csv.DictReader) -> Dict[str, Dict[str, int]]:
    """
    Aggregate status codes per API from Athena query results.
    
    Args:
        rows: CSV reader with columns: target_group_arn, elb_status_code, error_count
        
    Returns:
        dict: Nested dictionary with structure:
              {api_name: {"2xx": count, "4xx": count, "5xx": count}}
              
    Notes:
        - Status codes 200-214 are classified as 2xx
        - Status codes 400-415 are classified as 4xx
        - Status codes 500-515 are classified as 5xx
        - Some APIs optionally include 3xx (300-314) in the 2xx bucket
    """
    # Initialize report structure for all APIs
    report = {api: {"2xx": 0, "4xx": 0, "5xx": 0} for api in ALLOWED_APIS}
    
    processed_rows = 0
    skipped_rows = 0

    for row in rows:
        try:
            # Extract and validate data
            api = detect_api(row["target_group_arn"])
            status = int(row["elb_status_code"])
            count = int(row["error_count"])
            
            if not api:
                skipped_rows += 1
                continue
            
            # Classify status code into bucket
            if 200 <= status <= 214:
                report[api]["2xx"] += count
            elif 300 <= status <= 314 and api in INCLUDE_3XX_APIS:
                # Special case: some APIs treat redirects as success
                report[api]["2xx"] += count
            elif 400 <= status <= 415:
                report[api]["4xx"] += count
            elif 500 <= status <= 515:
                report[api]["5xx"] += count
            
            processed_rows += 1
            
        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping malformed row: {row} - Error: {str(e)}")
            skipped_rows += 1
            continue
        except Exception as e:
            logger.error(f"Unexpected error processing row: {row} - Error: {str(e)}")
            skipped_rows += 1
            continue

    logger.info(f"Aggregation complete. Processed: {processed_rows}, Skipped: {skipped_rows}")
    
    return report


def build_sns_message(report: Dict[str, Dict[str, int]], date: str, pdf_url: str) -> str:
    """
    Build plain-text email message for SNS notification.
    
    Args:
        report: Aggregated status code data per API
        date: Report date (YYYY-MM-DD)
        pdf_url: S3 presigned URL for PDF download
        
    Returns:
        str: Formatted email message body
    """
    # Calculate summary statistics
    total_2xx = sum(api_data["2xx"] for api_data in report.values())
    total_4xx = sum(api_data["4xx"] for api_data in report.values())
    total_5xx = sum(api_data["5xx"] for api_data in report.values())
    
    message = f"""
Daily ALB API Status Report

Date: {date}

=== SUMMARY ===
Total 2xx (Success): {total_2xx:,}
Total 4xx (Client Errors): {total_4xx:,}
Total 5xx (Server Errors): {total_5xx:,}

The consolidated API status report has been generated successfully.

Download PDF Report (valid for 24 hours):
{pdf_url}

NOTE: This link expires in 24 hours. Download the report for your records.

Regards,
DevOps Automation Team
""".strip()
    
    return message


def generate_pdf(report: Dict[str, Dict[str, int]], date: str) -> str:
    """
    Generate professional PDF report with status code summary.
    
    Args:
        report: Aggregated status code data per API
        date: Report date (YYYY-MM-DD)
        
    Returns:
        str: Path to generated PDF file in /tmp
        
    Raises:
        Exception: If PDF generation fails
    """
    try:
        pdf_path = "/tmp/alb_api_status_report.pdf"
        
        logger.info(f"Generating PDF report for date: {date}")

        # Create PDF document
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            rightMargin=30,
            leftMargin=30,
            topMargin=30,
            bottomMargin=30
        )

        # Get ReportLab styles
        styles = getSampleStyleSheet()
        title_style = styles["Title"]
        normal_style = styles["Normal"]

        elements = []

        # ---- Header Section ----
        elements.append(Paragraph("ALB API Status Report", title_style))
        elements.append(Paragraph(f"<b>Report Date:</b> {date}", normal_style))
        elements.append(Paragraph(f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", normal_style))
        elements.append(Paragraph("<br/>", normal_style))

        # ---- Table Data ----
        table_data = [["API Name", "2xx (Success)", "4xx (Client Error)", "5xx (Server Error)"]]

        for api in sorted(ALLOWED_APIS):
            v = report[api]
            table_data.append([
                api,
                f"{v['2xx']:,}",
                f"{v['4xx']:,}",
                f"{v['5xx']:,}"
            ])

        # Create table with specified column widths
        table = Table(
            table_data,
            colWidths=[230, 90, 110, 110],
            repeatRows=1  # Repeat header on each page
        )

        # Apply professional styling
        table.setStyle(TableStyle([
            # Header row styling
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 11),
            ("ALIGN", (1, 0), (-1, 0), "CENTER"),

            # Body styling
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            # Grid and borders
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("LINEABOVE", (0, 0), (-1, 0), 2, colors.HexColor("#2C3E50")),

            # Padding
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),

            # Alternate row colors
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F8F9FA")]),
        ]))

        elements.append(table)
        
        # Build PDF
        doc.build(elements)
        
        logger.info(f"PDF generated successfully at: {pdf_path}")
        return pdf_path
        
    except Exception as e:
        logger.error(f"Failed to generate PDF: {str(e)}")
        raise


# ================= MAIN LAMBDA HANDLER ================= #

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler function.
    
    Args:
        event: Lambda event object (from EventBridge or manual invocation)
        context: Lambda context object
        
    Returns:
        dict: Response with status, date, and presigned URL validity
        
    Raises:
        Exception: Logs error and returns error response
    """
    # Log invocation details
    request_id = context.request_id if context else "local-test"
    logger.info(f"Lambda invocation started. Request ID: {request_id}")
    logger.info(f"Event: {json.dumps(event)}")
    
    try:
        # Get current date for report
        date = datetime.utcnow().strftime("%Y-%m-%d")
        logger.info(f"Generating report for date: {date}")

        # Step 1: Execute Athena query
        query_execution_id = run_athena_query()
        
        # Step 2: Wait for query completion
        wait_for_query(query_execution_id)

        # Step 3: Fetch and parse results
        rows = fetch_csv(query_execution_id)
        
        # Step 4: Aggregate data by API
        report = aggregate(rows)
        
        # Log summary statistics
        total_requests = sum(
            api_data["2xx"] + api_data["4xx"] + api_data["5xx"] 
            for api_data in report.values()
        )
        logger.info(f"Total requests processed: {total_requests:,}")

        # Step 5: Generate PDF report
        pdf_path = generate_pdf(report, date)

        # Step 6: Upload PDF to S3
        s3_key = f"{PDF_PREFIX}/alb_api_status_report_{date}.pdf"
        logger.info(f"Uploading PDF to s3://{PDF_BUCKET}/{s3_key}")
        
        s3.upload_file(pdf_path, PDF_BUCKET, s3_key)
        logger.info("PDF uploaded successfully")

        # Step 7: Generate presigned URL (24-hour expiry)
        presigned_url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": PDF_BUCKET, "Key": s3_key},
            ExpiresIn=24 * 60 * 60  # 24 hours
        )
        logger.info("Presigned URL generated")

        # Step 8: Build email message
        message = build_sns_message(report, date, presigned_url)

        # Step 9: Send SNS notification
        if SNS_TOPIC_ARN:
            logger.info(f"Publishing notification to SNS topic: {SNS_TOPIC_ARN}")
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"Daily ALB API Status Report | {date}",
                Message=message
            )
            logger.info("SNS notification sent successfully")
        else:
            logger.warning("SNS_TOPIC_ARN not configured. Skipping notification.")

        # Step 10: Return success response
        response = {
            "status": "success",
            "date": date,
            "query_execution_id": query_execution_id,
            "total_requests_processed": total_requests,
            "report_s3_key": s3_key,
            "presigned_url_validity_hours": 24,
            "execution_time_seconds": context.get_remaining_time_in_millis() / 1000 if context else None
        }
        
        logger.info(f"Report generation completed successfully: {json.dumps(response)}")
        return response

    except TimeoutError as e:
        logger.error(f"Timeout error: {str(e)}")
        return {
            "status": "error",
            "error_type": "TimeoutError",
            "message": str(e),
            "request_id": request_id
        }
    
    except Exception as e:
        logger.error(f"Unexpected error in lambda_handler: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e),
            "request_id": request_id
        }
