#!/bin/bash

################################################################################
# Lambda Deployment Script
# 
# This script automates the deployment of the ALB Status Report Lambda function.
# It handles dependency installation, packaging, deployment, and verification.
#
# Usage:
#   ./scripts/deploy.sh [ENVIRONMENT] [REGION]
#
# Example:
#   ./scripts/deploy.sh prod us-east-1
#
# Requirements:
#   - AWS CLI v2
#   - Python 3.11+
#   - zip command
#   - Valid AWS credentials
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Exit on pipe failure

# ==================== CONFIGURATION ==================== #

ENVIRONMENT="${1:-dev}"
REGION="${2:-us-east-1}"
FUNCTION_NAME="alb-status-report-${ENVIRONMENT}"
LAMBDA_DIR="lambda/alb_status_report"
PACKAGE_DIR="${LAMBDA_DIR}/package"
DEPLOYMENT_PACKAGE="${LAMBDA_DIR}/function.zip"

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

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI not found. Please install AWS CLI v2."
        exit 1
    fi

    # Check Python
    if ! command -v python3.11 &> /dev/null; then
        log_error "Python 3.11 not found. Please install Python 3.11+."
        exit 1
    fi

    # Check zip
    if ! command -v zip &> /dev/null; then
        log_error "zip command not found. Please install zip."
        exit 1
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity --region "$REGION" &> /dev/null; then
        log_error "AWS credentials not configured or invalid."
        exit 1
    fi

    log_info "✓ All prerequisites satisfied"
}

clean_previous_builds() {
    log_info "Cleaning previous builds..."
    rm -rf "$PACKAGE_DIR"
    rm -f "$DEPLOYMENT_PACKAGE"
    log_info "✓ Cleaned up previous builds"
}

install_dependencies() {
    log_info "Installing Python dependencies..."
    mkdir -p "$PACKAGE_DIR"

    # Install dependencies
    pip3.11 install -r "${LAMBDA_DIR}/requirements.txt" -t "$PACKAGE_DIR" --quiet

    # Check package size
    PACKAGE_SIZE=$(du -sm "$PACKAGE_DIR" | cut -f1)
    log_info "Package size: ${PACKAGE_SIZE} MB"

    if [ "$PACKAGE_SIZE" -gt 200 ]; then
        log_warn "Package size exceeds 200 MB. Consider using Lambda layers."
    fi

    log_info "✓ Dependencies installed"
}

package_lambda() {
    log_info "Creating deployment package..."

    # Copy handler to package directory
    cp "${LAMBDA_DIR}/handler.py" "$PACKAGE_DIR/"

    # Create ZIP file
    cd "$PACKAGE_DIR"
    zip -r9 ../function.zip . -q
    cd - > /dev/null

    # Add version metadata
    GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    echo "$GIT_COMMIT" > /tmp/version.txt
    zip -j "$DEPLOYMENT_PACKAGE" /tmp/version.txt -q

    # Display package info
    PACKAGE_SIZE=$(du -h "$DEPLOYMENT_PACKAGE" | cut -f1)
    log_info "✓ Deployment package created: ${DEPLOYMENT_PACKAGE} (${PACKAGE_SIZE})"
}

deploy_lambda() {
    log_info "Deploying Lambda function to ${ENVIRONMENT} (${REGION})..."

    # Check if function exists
    if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &> /dev/null; then
        log_info "Function exists. Updating code..."
        
        aws lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --zip-file fileb://"$DEPLOYMENT_PACKAGE" \
            --region "$REGION" \
            --output table

        log_info "Waiting for function update to complete..."
        aws lambda wait function-updated \
            --function-name "$FUNCTION_NAME" \
            --region "$REGION"

    else
        log_error "Function ${FUNCTION_NAME} does not exist. Please create it first."
        log_error "Use: aws lambda create-function --function-name $FUNCTION_NAME ..."
        exit 1
    fi

    log_info "✓ Lambda function deployed successfully"
}

update_configuration() {
    log_info "Updating Lambda configuration..."

    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.11 \
        --timeout 300 \
        --memory-size 512 \
        --region "$REGION" \
        --output table > /dev/null

    log_info "✓ Configuration updated"
}

verify_deployment() {
    log_info "Verifying deployment..."

    # Get function details
    FUNCTION_INFO=$(aws lambda get-function \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --query 'Configuration.[State,LastUpdateStatus,CodeSize,Runtime,MemorySize,Timeout]' \
        --output text)

    log_info "Function details:"
    echo "$FUNCTION_INFO" | awk '{printf "  State: %s\n  Last Update: %s\n  Code Size: %s bytes\n  Runtime: %s\n  Memory: %s MB\n  Timeout: %s seconds\n", $1, $2, $3, $4, $5, $6}'

    # Check function state
    STATE=$(echo "$FUNCTION_INFO" | awk '{print $1}')
    if [ "$STATE" != "Active" ]; then
        log_error "Function is not in Active state: $STATE"
        exit 1
    fi

    log_info "✓ Deployment verified"
}

run_smoke_test() {
    log_info "Running smoke test..."

    # Invoke Lambda with test payload
    RESPONSE=$(aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --payload '{}' \
        --log-type Tail \
        /tmp/lambda-response.json 2>&1)

    # Check for errors
    if echo "$RESPONSE" | grep -q "FunctionError"; then
        log_error "Lambda invocation failed"
        cat /tmp/lambda-response.json
        exit 1
    fi

    # Check response
    if grep -q '"status": "success"' /tmp/lambda-response.json; then
        log_info "✓ Smoke test passed"
    else
        log_warn "Smoke test returned unexpected response:"
        cat /tmp/lambda-response.json
    fi
}

cleanup() {
    log_info "Cleaning up temporary files..."
    rm -rf "$PACKAGE_DIR"
    rm -f "$DEPLOYMENT_PACKAGE"
    rm -f /tmp/lambda-response.json /tmp/version.txt
    log_info "✓ Cleanup complete"
}

# ==================== MAIN ==================== #

main() {
    echo "==========================================="
    echo "  ALB Status Report Lambda Deployment"
    echo "==========================================="
    echo ""
    log_info "Environment: $ENVIRONMENT"
    log_info "Region: $REGION"
    log_info "Function Name: $FUNCTION_NAME"
    echo ""

    # Confirm production deployment
    if [ "$ENVIRONMENT" == "prod" ]; then
        log_warn "You are deploying to PRODUCTION"
        read -p "Continue? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
            log_info "Deployment cancelled"
            exit 0
        fi
    fi

    # Run deployment steps
    check_prerequisites
    clean_previous_builds
    install_dependencies
    package_lambda
    deploy_lambda
    update_configuration
    verify_deployment

    # Run smoke test (optional for prod)
    if [ "$ENVIRONMENT" != "prod" ]; then
        run_smoke_test
    fi

    cleanup

    echo ""
    log_info "=========================================="
    log_info "  Deployment Complete! 🚀"
    log_info "=========================================="
    echo ""
    log_info "Next steps:"
    log_info "  1. Check CloudWatch Logs: aws logs tail /aws/lambda/$FUNCTION_NAME --follow"
    log_info "  2. Invoke manually: aws lambda invoke --function-name $FUNCTION_NAME --payload '{}' /tmp/response.json"
    log_info "  3. Monitor metrics: CloudWatch Console > Lambda > $FUNCTION_NAME"
}

# Execute main function
main