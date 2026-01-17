#!/bin/bash

################################################################################
# Lambda Cleanup Script
# 
# This script safely removes Lambda function resources and associated artifacts.
# USE WITH CAUTION - This script deletes resources!
#
# Usage:
#   ./scripts/cleanup.sh [ENVIRONMENT] [REGION]
#
# Example:
#   ./scripts/cleanup.sh dev us-east-1
#
# Requirements:
#   - AWS CLI v2
#   - Valid AWS credentials with deletion permissions
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# ==================== CONFIGURATION ==================== #

ENVIRONMENT="${1:-dev}"
REGION="${2:-us-east-1}"
FUNCTION_NAME="alb-status-report-${ENVIRONMENT}"
LOG_GROUP_NAME="/aws/lambda/${FUNCTION_NAME}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ==================== FUNCTIONS ==================== #

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

confirm_deletion() {
    echo ""
    log_warn "=========================================="
    log_warn "  WARNING: RESOURCE DELETION"
    log_warn "=========================================="
    log_warn "This will delete the following resources:"
    log_warn "  - Lambda Function: $FUNCTION_NAME"
    log_warn "  - CloudWatch Logs: $LOG_GROUP_NAME"
    log_warn "  - Local build artifacts"
    echo ""

    if [ "$ENVIRONMENT" == "prod" ]; then
        log_error "You are attempting to delete PRODUCTION resources!"
        echo ""
    fi

    read -p "Type 'DELETE' to confirm: " -r
    if [[ ! $REPLY == "DELETE" ]]; then
        log_info "Cleanup cancelled"
        exit 0
    fi
}

delete_lambda_function() {
    log_info "Deleting Lambda function: $FUNCTION_NAME..."

    if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &> /dev/null; then
        aws lambda delete-function \
            --function-name "$FUNCTION_NAME" \
            --region "$REGION"
        
        log_info "✓ Lambda function deleted"
    else
        log_warn "Lambda function $FUNCTION_NAME not found (already deleted?)"
    fi
}

delete_cloudwatch_logs() {
    log_info "Deleting CloudWatch log group: $LOG_GROUP_NAME..."

    if aws logs describe-log-groups \
        --log-group-name-prefix "$LOG_GROUP_NAME" \
        --region "$REGION" \
        --query 'logGroups[0].logGroupName' \
        --output text | grep -q "$LOG_GROUP_NAME"; then
        
        aws logs delete-log-group \
            --log-group-name "$LOG_GROUP_NAME" \
            --region "$REGION"
        
        log_info "✓ CloudWatch log group deleted"
    else
        log_warn "CloudWatch log group $LOG_GROUP_NAME not found (already deleted?)"
    fi
}

clean_local_artifacts() {
    log_info "Cleaning local build artifacts..."

    # Remove package directories
    rm -rf lambda/alb_status_report/package
    rm -rf lambda/alb_status_report/__pycache__
    rm -f lambda/alb_status_report/function.zip
    rm -f lambda/alb_status_report/version.txt

    # Remove test artifacts
    rm -rf .pytest_cache
    rm -rf venv
    rm -f /tmp/lambda-response.json

    log_info "✓ Local artifacts cleaned"
}

list_remaining_resources() {
    log_info "Checking for remaining resources..."

    # Check for EventBridge rules
    RULES=$(aws events list-rules \
        --region "$REGION" \
        --query "Rules[?contains(Name, 'alb-status-report')].Name" \
        --output text)

    if [ -n "$RULES" ]; then
        log_warn "Found EventBridge rules that may need cleanup:"
        echo "$RULES"
    fi

    # Check for S3 buckets
    log_info "S3 buckets (not deleted by this script):"
    echo "  - ALB logs bucket"
    echo "  - Athena results bucket"
    echo "  - Report storage bucket"
    log_warn "These buckets must be deleted manually if needed"

    # Check for IAM roles
    ROLES=$(aws iam list-roles \
        --query "Roles[?contains(RoleName, 'alb-status-report')].RoleName" \
        --output text)

    if [ -n "$ROLES" ]; then
        log_warn "Found IAM roles that may need cleanup:"
        echo "$ROLES"
        log_warn "Delete IAM roles manually: aws iam delete-role --role-name <ROLE_NAME>"
    fi
}

# ==================== MAIN ==================== #

main() {
    echo "==========================================="
    echo "  ALB Status Report Lambda Cleanup"
    echo "==========================================="
    echo ""
    log_info "Environment: $ENVIRONMENT"
    log_info "Region: $REGION"
    log_info "Function Name: $FUNCTION_NAME"
    echo ""

    # Confirm deletion
    confirm_deletion

    echo ""
    log_info "Starting cleanup..."
    echo ""

    # Run cleanup steps
    delete_lambda_function
    delete_cloudwatch_logs
    clean_local_artifacts

    echo ""
    list_remaining_resources

    echo ""
    log_info "=========================================="
    log_info "  Cleanup Complete!"
    log_info "=========================================="
    echo ""
    log_info "Manual cleanup may be required for:"
    log_info "  - S3 buckets (data retention)"
    log_info "  - IAM roles (if not managed by IaC)"
    log_info "  - EventBridge schedules"
    log_info "  - SNS topics and subscriptions"
}

# Execute main function
main