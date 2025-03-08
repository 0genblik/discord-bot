import json
import os
import requests
import boto3
import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Fetch bot token from AWS Secrets Manager
secrets_client = boto3.client("secretsmanager")
secrets = secrets_client.get_secret_value(SecretId="discord_keys")
BOT_TOKEN = json.loads(secrets["SecretString"])["BOT_TOKEN"]

def lambda_handler(event, _):
    """
    Handles Discord commands and responds accordingly.
    """
    logger.info(f"Handling received event: {json.dumps(event)}")

    event_body = json.loads(event["body"])
    
    # Verify request type
    if event_body.get("type") == 1:
        return {"statusCode": 200, "body": json.dumps({"type": 1})}

    command = event_body["data"]["name"]

    # Handle commands
    if command == "ping":
        response_data = {
            "type": 4,  # CHANNEL_MESSAGE_WITH_SOURCE
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
    

    logger.info(f"Attempting response: {json.dumps(response_data)}")
    return {
        "statusCode": 200,
        "body": json.dumps(response_data)
    }