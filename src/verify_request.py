import json
import os
import boto3
import logging
from base64 import b64decode
from discord_interactions import verify_key

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS Secrets Manager client
secrets_client = boto3.client("secretsmanager")

def get_discord_public_key():
    """
    Retrieves the Discord public key from AWS Secrets Manager.
    """
    secret_value = secrets_client.get_secret_value(SecretId="discord_keys")
    return json.loads(secret_value["SecretString"])["DISCORD_PUBLIC_KEY"]

DISCORD_PUBLIC_KEY = get_discord_public_key()

def lambda_handler(event, context):
    """
    Verifies incoming requests from Discord using cryptographic signatures.
    If verification fails, returns a 401 Unauthorized response.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    headers = event.get("headers", {})
    raw_body = event.get("body", "")

    signature = headers.get("x-signature-ed25519")
    timestamp = headers.get("x-signature-timestamp")

    if not signature or not timestamp:
        logger.error("Missing required headers")
        return {"statusCode": 400, "body": json.dumps({"error": "Missing required headers"})}

    # Verify the request authenticity
    is_verified = verify_key(raw_body.encode(), signature, timestamp, DISCORD_PUBLIC_KEY)

    if not is_verified:
        logger.error("Unauthorized request")
        return {"statusCode": 401, "body": json.dumps({"error": "Unauthorized request"})}

    # Respond with type 1 to indicate successful verification
    return {"statusCode": 200, "body": json.dumps({"type": 1})}