pipeline {
    agent any

    environment {
        AWS_DEFAULT_REGION = 'us-east-1'
        LAMBDA_FUNCTION_NAME = 'alb-status-report'
        S3_DEPLOYMENT_BUCKET = 'lambda-deployment-artifacts'
        PYTHON_VERSION = '3.11'
    }

    parameters {
        choice(
            name: 'ENVIRONMENT',
            choices: ['dev', 'staging', 'prod'],
            description: 'Target deployment environment'
        )
        booleanParam(
            name: 'RUN_INTEGRATION_TESTS',
            defaultValue: true,
            description: 'Run integration tests after deployment'
        )
    }

    stages {
        stage('Checkout') {
            steps {
                echo '=== Checking out code ==='
                checkout scm
                sh 'git rev-parse HEAD > commit.txt'
                script {
                    env.GIT_COMMIT_SHORT = sh(
                        script: 'git rev-parse --short HEAD',
                        returnStdout: true
                    ).trim()
                }
                echo "Building commit: ${env.GIT_COMMIT_SHORT}"
            }
        }

        stage('Setup Python Environment') {
            steps {
                echo '=== Setting up Python environment ==='
                sh '''
                    python${PYTHON_VERSION} -m venv venv
                    . venv/bin/activate
                    pip install --upgrade pip
                    pip install -r lambda/alb_status_report/requirements.txt
                    pip install pylint black pytest boto3-stubs
                '''
            }
        }

        stage('Code Quality') {
            parallel {
                stage('Lint') {
                    steps {
                        echo '=== Running pylint ==='
                        sh '''
                            . venv/bin/activate
                            pylint lambda/alb_status_report/handler.py \
                                --disable=C0111,R0913 \
                                --max-line-length=120 || true
                        '''
                    }
                }
                stage('Format Check') {
                    steps {
                        echo '=== Checking code formatting ==='
                        sh '''
                            . venv/bin/activate
                            black --check lambda/alb_status_report/handler.py --line-length 120 || true
                        '''
                    }
                }
            }
        }

        stage('Unit Tests') {
            steps {
                echo '=== Running unit tests ==='
                sh '''
                    . venv/bin/activate
                    # Add unit tests when available
                    echo "Unit tests would run here"
                    # pytest tests/unit/ --cov=lambda --cov-report=xml
                '''
            }
        }

        stage('Package Lambda') {
            steps {
                echo '=== Creating Lambda deployment package ==='
                sh '''
                    cd lambda/alb_status_report
                    
                    # Clean previous builds
                    rm -rf package function.zip
                    
                    # Install dependencies to package directory
                    pip install -r requirements.txt -t package/
                    
                    # Copy handler to package
                    cp handler.py package/
                    
                    # Create ZIP file
                    cd package
                    zip -r ../function.zip .
                    cd ..
                    
                    # Verify package size
                    ls -lh function.zip
                    
                    # Add metadata
                    echo "${GIT_COMMIT_SHORT}" > version.txt
                    zip -u function.zip version.txt
                '''
            }
        }

        stage('Upload to S3') {
            steps {
                echo '=== Uploading deployment package to S3 ==='
                sh '''
                    aws s3 cp lambda/alb_status_report/function.zip \
                        s3://${S3_DEPLOYMENT_BUCKET}/lambda/${LAMBDA_FUNCTION_NAME}/${GIT_COMMIT_SHORT}/function.zip \
                        --region ${AWS_DEFAULT_REGION}
                    
                    echo "Package uploaded: s3://${S3_DEPLOYMENT_BUCKET}/lambda/${LAMBDA_FUNCTION_NAME}/${GIT_COMMIT_SHORT}/function.zip"
                '''
            }
        }

        stage('Deploy to Dev') {
            when {
                expression { params.ENVIRONMENT == 'dev' || params.ENVIRONMENT == 'staging' || params.ENVIRONMENT == 'prod' }
            }
            steps {
                echo "=== Deploying to ${params.ENVIRONMENT} environment ==="
                sh '''
                    aws lambda update-function-code \
                        --function-name ${LAMBDA_FUNCTION_NAME}-${ENVIRONMENT} \
                        --s3-bucket ${S3_DEPLOYMENT_BUCKET} \
                        --s3-key lambda/${LAMBDA_FUNCTION_NAME}/${GIT_COMMIT_SHORT}/function.zip \
                        --region ${AWS_DEFAULT_REGION}
                    
                    # Wait for update to complete
                    aws lambda wait function-updated \
                        --function-name ${LAMBDA_FUNCTION_NAME}-${ENVIRONMENT} \
                        --region ${AWS_DEFAULT_REGION}
                    
                    echo "Deployment complete"
                '''
            }
        }

        stage('Smoke Test') {
            when {
                expression { params.ENVIRONMENT == 'dev' }
            }
            steps {
                echo '=== Running smoke tests ==='
                sh '''
                    # Invoke Lambda with test event
                    aws lambda invoke \
                        --function-name ${LAMBDA_FUNCTION_NAME}-${ENVIRONMENT} \
                        --payload '{}' \
                        --region ${AWS_DEFAULT_REGION} \
                        /tmp/response.json
                    
                    # Check response
                    cat /tmp/response.json
                    
                    # Verify success
                    if grep -q '"status": "success"' /tmp/response.json; then
                        echo "✓ Smoke test passed"
                    else
                        echo "✗ Smoke test failed"
                        exit 1
                    fi
                '''
            }
        }

        stage('Integration Tests') {
            when {
                expression { params.RUN_INTEGRATION_TESTS == true && params.ENVIRONMENT == 'dev' }
            }
            steps {
                echo '=== Running integration tests ==='
                sh '''
                    . venv/bin/activate
                    # Add integration tests when available
                    echo "Integration tests would run here"
                    # pytest tests/integration/
                '''
            }
        }

        stage('Deploy to Staging') {
            when {
                expression { params.ENVIRONMENT == 'staging' || params.ENVIRONMENT == 'prod' }
            }
            steps {
                echo '=== Deploying to Staging ==="
                sh '''
                    aws lambda update-function-code \
                        --function-name ${LAMBDA_FUNCTION_NAME}-staging \
                        --s3-bucket ${S3_DEPLOYMENT_BUCKET} \
                        --s3-key lambda/${LAMBDA_FUNCTION_NAME}/${GIT_COMMIT_SHORT}/function.zip \
                        --region ${AWS_DEFAULT_REGION}
                    
                    aws lambda wait function-updated \
                        --function-name ${LAMBDA_FUNCTION_NAME}-staging \
                        --region ${AWS_DEFAULT_REGION}
                '''
            }
        }

        stage('Approve Production Deployment') {
            when {
                expression { params.ENVIRONMENT == 'prod' }
            }
            steps {
                script {
                    input message: 'Deploy to Production?',
                          ok: 'Deploy',
                          submitter: 'admin,release-manager'
                }
            }
        }

        stage('Deploy to Production') {
            when {
                expression { params.ENVIRONMENT == 'prod' }
            }
            steps {
                echo '=== Deploying to Production ==='
                sh '''
                    # Publish new Lambda version
                    VERSION=$(aws lambda publish-version \
                        --function-name ${LAMBDA_FUNCTION_NAME}-prod \
                        --description "Deploy ${GIT_COMMIT_SHORT}" \
                        --region ${AWS_DEFAULT_REGION} \
                        --query 'Version' --output text)
                    
                    echo "Published Lambda version: $VERSION"
                    
                    # Update function code
                    aws lambda update-function-code \
                        --function-name ${LAMBDA_FUNCTION_NAME}-prod \
                        --s3-bucket ${S3_DEPLOYMENT_BUCKET} \
                        --s3-key lambda/${LAMBDA_FUNCTION_NAME}/${GIT_COMMIT_SHORT}/function.zip \
                        --region ${AWS_DEFAULT_REGION}
                    
                    # Wait for update
                    aws lambda wait function-updated \
                        --function-name ${LAMBDA_FUNCTION_NAME}-prod \
                        --region ${AWS_DEFAULT_REGION}
                    
                    # Tag production version
                    aws lambda tag-resource \
                        --resource arn:aws:lambda:${AWS_DEFAULT_REGION}:*:function:${LAMBDA_FUNCTION_NAME}-prod:$VERSION \
                        --tags "GitCommit=${GIT_COMMIT_SHORT},DeployedBy=Jenkins,Environment=prod"
                '''
            }
        }

        stage('Post-Deployment Verification') {
            when {
                expression { params.ENVIRONMENT == 'prod' }
            }
            steps {
                echo '=== Verifying production deployment ==='
                sh '''
                    # Check Lambda function status
                    aws lambda get-function \
                        --function-name ${LAMBDA_FUNCTION_NAME}-prod \
                        --region ${AWS_DEFAULT_REGION} \
                        --query 'Configuration.[State,LastUpdateStatus]'
                    
                    # Check recent executions
                    aws logs tail /aws/lambda/${LAMBDA_FUNCTION_NAME}-prod \
                        --since 5m \
                        --format short
                '''
            }
        }
    }

    post {
        success {
            echo '=== Pipeline completed successfully ==='
            script {
                if (params.ENVIRONMENT == 'prod') {
                    // Send success notification
                    sh '''
                        echo "Production deployment successful: ${GIT_COMMIT_SHORT}"
                        # aws sns publish --topic-arn arn:aws:sns:...:deployments \
                        #   --message "ALB Observability Lambda deployed to production: ${GIT_COMMIT_SHORT}"
                    '''
                }
            }
        }
        failure {
            echo '=== Pipeline failed ==='
            sh '''
                echo "Deployment failed at stage: ${STAGE_NAME}"
                # aws sns publish --topic-arn arn:aws:sns:...:deployment-failures \
                #   --message "ALB Observability Lambda deployment failed: ${GIT_COMMIT_SHORT}"
            '''
        }
        always {
            echo '=== Cleaning up ==='
            sh '''
                # Clean up build artifacts
                rm -rf lambda/alb_status_report/package
                rm -rf lambda/alb_status_report/function.zip
                rm -rf venv
            '''
        }
    }
}