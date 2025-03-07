import json
import os
import requests
import boto3
import logging
import asyncio

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
    logger.info(f"Received event: {json.dumps(event)}")

    event_body = json.loads(event["body"])
    
    # Verify request type
    if event_body.get("type") == 1:
        return {"statusCode": 200, "body": json.dumps({"type": 1})}

    command = event_body["data"]["name"]
    interaction_token = event_body["token"]
    application_id = event_body["application_id"]

    # Handle commands
    if command == "ping":
        response_message = {"content": "Pong!"}

    elif command == "weather":
        # Extract location parameter
        location = event_body["data"]["options"][0]["value"]
        response_message = {"content": f"Fetching weather for {location}..."}
        send_discord_response(response_message, application_id, interaction_token)

        # Run async task
        asyncio.run(process_weather(location, application_id, interaction_token))

    else:
        response_message = {"content": f"Unknown command: {command}"}

    send_discord_response(response_message, application_id, interaction_token)
    
    return {"statusCode": 200}

async def process_weather(location, application_id, interaction_token):
    """
    Fetches the current weather for a given location using OpenWeather API.
    """
    url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={WEATHER_API_KEY}&units=metric"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        temperature = data["main"]["temp"]
        message = {"content": f"The current temperature in {location} is {temperature}°C."}
    else:
        message = {"content": "Error: Could not retrieve weather data."}

    send_discord_response(message, application_id, interaction_token)

def send_discord_response(response, application_id, interaction_token):
    """
    Sends a response to Discord using the interaction token.
    """
    url = f"https://discord.com/api/v10/webhooks/{application_id}/{interaction_token}"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}

    requests.post(url, headers=headers, json=response)