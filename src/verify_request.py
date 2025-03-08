import json
import boto3
import logging
from discord_interactions import verify_key

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS Secrets Manager client
secrets_client = boto3.client("secretsmanager")
secret_value = secrets_client.get_secret_value(SecretId="discord_keys")
secrets = json.loads(secret_value["SecretString"])
DISCORD_PUBLIC_KEY = secrets["DISCORD_PUBLIC_KEY"]

def lambda_handler(event, _):
    """
    Unified handler that verifies requests and responds to commands
    """
    headers = event.get("headers", {})
    raw_body = event.get("body", "")

    signature = headers.get("x-signature-ed25519")
    timestamp = headers.get("x-signature-timestamp")

    if not signature or not timestamp:
        return {"statusCode": 400, "body": json.dumps({"error": "Missing required headers"})}

    # Verify the request authenticity
    is_verified = verify_key(raw_body.encode(), signature, timestamp, DISCORD_PUBLIC_KEY)

    if not is_verified:
        return {"statusCode": 401, "body": json.dumps({"error": "Unauthorized request"})}

    # Parse the request body
    event_body = json.loads(raw_body)
    
    # If this is a ping (type 1), respond immediately
    if event_body.get("type") == 1:
        return {"statusCode": 200, "body": json.dumps({"type": 1})}

    # Handle commands
    command = event_body["data"]["name"]

    if command == "ping":
        response_data = {
            "type": 4,
            "data": {
                "content": "Pong!"
            }
        }
    elif command == "weather":
        location = next((opt["value"] for opt in event_body["data"].get("options", []) if opt["name"] == "location"), None)
        response_data = {
            "type": 4,
            "data": {
                "content": f"Weather feature coming soon! You asked about: {location}"
            }
        }
    else:
        response_data = {
            "type": 4,
            "data": {
                "content": f"Unknown command: {command}"
            }
        }

    return {
        "statusCode": 200,
        "body": json.dumps(response_data)
    }