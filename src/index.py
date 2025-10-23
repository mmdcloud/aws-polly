import os
import json
import logging
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cachetools import TTLCache

# Configure Logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize cache (persists across warm Lambda invocations)
audio_cache = TTLCache(maxsize=500, ttl=3600)  # 1-hour TTL

# Initialize AWS clients (reused across invocations)
polly = boto3.client("polly")
s3 = boto3.client("s3")

# Environment variables
S3_BUCKET = os.getenv("S3_BUCKET")

def synthesize_speech(text, voice_id="Joanna", output_format="mp3", s3_key=None):
    """
    Synthesizes speech from text using Amazon Polly and optionally stores it to S3.
    Includes caching, error handling, and logging.
    """
    cache_key = f"{voice_id}:{output_format}:{text[:100]}"

    # 1. Return cached version if exists
    if cache_key in audio_cache:
        logger.info("Cache hit for text snippet: %s...", text[:50])
        return audio_cache[cache_key]

    try:
        logger.info("Synthesizing speech for text snippet: %s...", text[:50])

        # 2. Call Amazon Polly
        response = polly.synthesize_speech(
            Text=text,
            OutputFormat=output_format,
            VoiceId=voice_id,
            Engine="neural",  # 'neural' for high-quality voice
        )

        audio_stream = response.get("AudioStream")
        if not audio_stream:
            raise RuntimeError("No audio stream returned from Polly")

        # 3. Save to temp file
        local_path = f"/tmp/{voice_id}_{hash(text)}.{output_format}"
        with open(local_path, "wb") as file:
            file.write(audio_stream.read())

        # 4. Optionally upload to S3
        if s3_key:
            s3.upload_file(local_path, S3_BUCKET, s3_key)
            s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
            logger.info("Audio uploaded to S3: %s", s3_url)
        else:
            s3_url = None

        # 5. Cache the result
        audio_cache[cache_key] = {"file": local_path, "s3_url": s3_url}

        return audio_cache[cache_key]

    except (BotoCoreError, ClientError) as e:
        logger.error("AWS Polly error: %s", e, exc_info=True)
        raise
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        raise


def lambda_handler(event, context):
    """
    AWS Lambda handler function.
    
    Expected event structure:
    {
        "text": "Text to synthesize",
        "voice_id": "Joanna",
        "output_format": "mp3",
        "s3_key": "texttospeech.mp3"
    }
    """
    try:
        # Parse input from event
        if isinstance(event.get("body"), str):
            # API Gateway format
            body = json.loads(event["body"])
        else:
            # Direct invocation
            body = event

        # Extract parameters
        text = body.get("text")
        if not text:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Missing required parameter: text"})
            }

        voice_id = body.get("voice_id", "Joanna")
        output_format = body.get("output_format", "mp3")
        s3_key = body.get("s3_key")

        # Validate parameters
        if len(text) > 3000:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Text exceeds maximum length of 3000 characters"})
            }

        # Synthesize speech
        result = synthesize_speech(
            text=text,
            voice_id=voice_id,
            output_format=output_format,
            s3_key=s3_key
        )

        # Return success response
        response_body = {
            "message": "Speech synthesis completed successfully",
            "voice_id": voice_id,
            "output_format": output_format,
            "local_path": result["file"]
        }

        if result.get("s3_url"):
            response_body["s3_url"] = result["s3_url"]

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_body)
        }

    except ValueError as e:
        logger.error("Validation error: %s", e)
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)})
        }

    except (BotoCoreError, ClientError) as e:
        logger.error("AWS service error: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "AWS service error occurred"})
        }

    except Exception as e:
        logger.error("Unexpected error in lambda_handler: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Internal server error"})
        }