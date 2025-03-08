import json
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
WEATHER_API_KEY = json.loads(secrets["SecretString"])["WEATHER_API_KEY"]

def lambda_handler(event, _):
    """
    Handles Discord commands and responds accordingly.
    """
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        event_body = json.loads(event["body"])
        
        # Verify request type
        if event_body.get("type") == 1:
            return {
                "statusCode": 200,
                "body": json.dumps({"type": 1})
            }

        command = event_body["data"]["name"]
        interaction_token = event_body["token"]
        application_id = event_body["application_id"]

        # Initial response for all commands
        initial_response = {
            "type": 4,  # CHANNEL_MESSAGE_WITH_SOURCE
            "data": {
                "content": "Processing your command..."
            }
        }

        # Send initial response
        send_discord_response(initial_response, application_id, interaction_token)

        # Handle commands
        if command == "ping":
            final_response = {"content": "Pong!"}
        
        elif command == "weather":
            try:
                location = event_body["data"]["options"][0]["value"]
                url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={WEATHER_API_KEY}&units=metric"
                response = requests.get(url)

                if response.status_code == 200:
                    data = response.json()
                    temperature = data["main"]["temp"]
                    final_response = {"content": f"The current temperature in {location} is {temperature}°C."}
                else:
                    final_response = {"content": "Error: Could not retrieve weather data."}
            except Exception as e:
                logger.error(f"Weather API error: {str(e)}")
                final_response = {"content": "Error: Could not process weather request."}
        
        else:
            final_response = {"content": f"Unknown command: {command}"}

        # Send the final response
        send_discord_response(final_response, application_id, interaction_token)
        
        return {
            "statusCode": 200,
            "body": json.dumps({"type": 4})
        }

    except Exception as e:
        logger.error(f"Error handling command: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }

def send_discord_response(response, application_id, interaction_token):
    """
    Sends a response to Discord using the interaction token.
    """
    try:
        url = f"https://discord.com/api/v10/webhooks/{application_id}/{interaction_token}"
        headers = {
            "Content-Type": "application/json"
        }
        result = requests.post(url, headers=headers, json=response)
        logger.info(f"Discord response status: {result.status_code}")
        if result.status_code not in [200, 204]:
            logger.error(f"Discord response error: {result.text}")
    except Exception as e:
        logger.error(f"Error sending Discord response: {str(e)}")