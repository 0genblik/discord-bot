import json
import os
import requests
import boto3
import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
secrets_client = boto3.client("secretsmanager")
secrets = secrets_client.get_secret_value(SecretId="discord_keys")
BOT_TOKEN = json.loads(secrets["SecretString"])["BOT_TOKEN"]

def send_followup_response(interaction_token, response_data):
    """Sends a followup message to a deferred interaction"""
    url = f"https://discord.com/api/v10/webhooks/{BOT_TOKEN}/{interaction_token}"
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=response_data, headers=headers)
        response.raise_for_status()
        logger.info("Successfully sent followup response")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending followup response: {e}")
        return False

def lambda_handler(event, _):
    """
    Handles deferred Discord commands and sends responses via webhook
    """
    logger.info("Processing deferred command")
    
    try:
        # Extract command information
        command = event["data"]["name"]
        interaction_token = event["token"]

        # Process commands
        if command == "ping":
            response_data = {
                "content": "Pong! (processed asynchronously)"
            }
        elif command == "weather":
            location = next((opt["value"] for opt in event["data"].get("options", []) 
                           if opt["name"] == "location"), None)
            response_data = {
                "content": f"Weather feature coming soon! You asked about: {location}"
            }
        else:
            response_data = {
                "content": f"Unknown command: {command}"
            }

        # Send the response via webhook
        if not send_followup_response(interaction_token, response_data):
            logger.error("Failed to send followup response")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Failed to send response"})
            }

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Command processed successfully"})
        }

    except Exception as e:
        logger.error(f"Error processing command: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }