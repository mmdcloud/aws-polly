output "api_gateway_url" {
  value = aws_api_gateway_stage.api_stage.invoke_url
}

output "lambda_function_name" {
  value = module.lambda_function.function_name
}