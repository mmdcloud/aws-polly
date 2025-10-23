# --------------------------------------------------------------------------
# Random ID Generation
# --------------------------------------------------------------------------
resource "random_id" "random" {
  byte_length = 8
}

# --------------------------------------------------------------------------
# S3 configuration
# --------------------------------------------------------------------------
module "lambda_function_code_bucket" {
  source      = "./modules/s3"
  bucket_name = "pollyfunctioncodebucket-${random_id.random.hex}"
  objects = [
    {
      key    = "lambda.zip"
      source = "./files/lambda.zip"
    }
  ]
  bucket_policy = ""
  cors = [
    {
      allowed_headers = ["*"]
      allowed_methods = ["GET"]
      allowed_origins = ["*"]
      max_age_seconds = 3000
    }
  ]
  versioning_enabled = "Enabled"
  force_destroy      = true
}

# Output bucket
module "dest_bucket" {
  source        = "./modules/s3"
  bucket_name   = "destpollybucket-${random_id.random.hex}"
  objects       = []
  bucket_policy = ""
  cors = [
    {
      allowed_headers = ["*"]
      allowed_methods = ["GET"]
      allowed_origins = ["*"]
      max_age_seconds = 3000
    }
  ]
  versioning_enabled = "Enabled"
  force_destroy      = true
}

# --------------------------------------------------------------------------
# Lambda configuration
# --------------------------------------------------------------------------

# IAM role for Lambda function
module "lambda_iam_role" {
  source             = "./modules/iam"
  role_name          = "polly-function-role"
  role_description   = "IAM role for Polly function"
  policy_name        = "polly-function-policy"
  policy_description = "IAM policy for Polly function"
  assume_role_policy = <<EOF
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Principal": {
                  "Service": "lambda.amazonaws.com"
                },
                "Effect": "Allow",
                "Sid": ""
            }
        ]
    }
    EOF
  policy             = <<EOF
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": [
                  "logs:CreateLogGroup",
                  "logs:CreateLogStream",
                  "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:*:*:*",
                "Effect": "Allow"
            },
            {
              "Effect": "Allow",
              "Action": ["polly:SynthesizeSpeech"],
              "Resource": "*"
            },
            {
              "Effect": "Allow",
              "Action": ["s3:PutObject"],
              "Resource": [
                "${module.dest_bucket.arn}",
                "${module.dest_bucket.arn}/*"
              ]
            }
        ]
    }
    EOF
}

# Lambda function
module "lambda_function" {
  source        = "./modules/lambda"
  function_name = "polly_function"
  role_arn      = module.lambda_iam_role.arn
  permissions   = []
  env_variables = {
    S3_BUCKET = module.dest_bucket.bucket
  }
  handler   = "index.lambda_handler"
  runtime   = "python3.12"
  s3_bucket = module.lambda_function_code_bucket.bucket
  s3_key    = "lambda.zip"
}

# --------------------------------------------------------------------------
# API Gateway configuration
# --------------------------------------------------------------------------
resource "aws_api_gateway_rest_api" "polly_api" {
  name = "polly-api"
  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "resource_api" {
  rest_api_id = aws_api_gateway_rest_api.polly_api.id
  parent_id   = aws_api_gateway_rest_api.polly_api.root_resource_id
  path_part   = "api"
}

resource "aws_api_gateway_method" "polly_method" {
  rest_api_id      = aws_api_gateway_rest_api.polly_api.id
  resource_id      = aws_api_gateway_resource.resource_api.id
  api_key_required = false
  http_method      = "POST"
  authorization    = "NONE"
}

resource "aws_api_gateway_integration" "polly_function_method_integration" {
  rest_api_id             = aws_api_gateway_rest_api.polly_api.id
  resource_id             = aws_api_gateway_resource.resource_api.id
  http_method             = aws_api_gateway_method.polly_method.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.lambda_function.invoke_arn
}

resource "aws_api_gateway_method_response" "polly_function_method_response_200" {
  rest_api_id = aws_api_gateway_rest_api.polly_api.id
  resource_id = aws_api_gateway_resource.resource_api.id
  http_method = aws_api_gateway_method.polly_method.http_method
  status_code = "200"
}

resource "aws_api_gateway_integration_response" "polly_function_integration_response_200" {
  rest_api_id = aws_api_gateway_rest_api.polly_api.id
  resource_id = aws_api_gateway_resource.resource_api.id
  http_method = aws_api_gateway_method.polly_method.http_method
  status_code = aws_api_gateway_method_response.polly_function_method_response_200.status_code
  depends_on = [
    aws_api_gateway_integration.polly_function_method_integration
  ]
}

resource "aws_api_gateway_deployment" "api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.polly_api.id
  lifecycle {
    create_before_destroy = true
  }
  depends_on = [aws_api_gateway_integration.polly_function_method_integration]
}

resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.polly_api.id
  stage_name    = "prod"
}