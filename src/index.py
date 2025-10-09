import os
import logging
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cachetools import TTLCache
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

# Initialize cache (avoid re-synthesizing the same text)
audio_cache = TTLCache(maxsize=500, ttl=3600)  # 1-hour TTL

# Initialize Polly client
polly = boto3.client("polly", region_name=os.getenv("AWS_DEFAULT_REGION"))

# Optional: S3 client for storing audio files
s3 = boto3.client("s3")
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
            s3_url = f"s3://{S3_BUCKET}/{s3_key}"
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


if __name__ == "__main__":
    text_input = "Welcome to the production-grade Amazon Polly demo!"
    result = synthesize_speech(text_input, voice_id="Matthew", s3_key="demo/audio1.mp3")

    print(f"Generated file: {result['file']}")
    if result["s3_url"]:
        print(f"Stored in S3: {result['s3_url']}")