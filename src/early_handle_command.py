"""
Command Processing Lambda Function for Discord Bot

This Lambda function handles the actual processing of Discord commands.
It is triggered asynchronously by verify_request.py after the initial
interaction acknowledgment.

Architecture Flow:
---------------
1. verify_request.py receives Discord command
2. verify_request.py sends "thinking..." response
3. This Lambda is triggered asynchronously
4. This Lambda processes command and sends final response

Why a Separate Lambda?
-------------------
Discord requires responses within 3 seconds, but commands like weather
need to make external API calls that might take longer.
By splitting the bot into two Lambdas, we can:
1. Acknowledge quickly (verify_request.py)
2. Take our time processing (this file)
3. Send final response when ready

External Service Integration:
-------------------------
- OpenWeather API for weather data
- AWS Secrets Manager for API keys
- Discord API for sending responses
"""

import json
import requests
import boto3
import logging
from datetime import datetime

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
secrets_client = boto3.client("secretsmanager")
logger.info("Fetching secrets from AWS Secrets Manager")
secrets = secrets_client.get_secret_value(SecretId="discord_keys")
secrets_dict = json.loads(secrets["SecretString"])
BOT_TOKEN = secrets_dict["BOT_TOKEN"]
APPLICATION_ID = secrets_dict["APPLICATION_ID"]
WEATHER_API_KEY = secrets_dict["WEATHER_API_KEY"]

def get_weather(location):
    """
    Get weather information using OpenWeather API.
    
    Technical Flow:
    -------------
    1. Geocoding API call to convert location name to coordinates
    2. Weather API call to get current conditions
    3. Format response with emojis and clear structure
    
    Why Two API Calls?
    ----------------
    OpenWeather requires coordinates for accurate data. The geocoding
    step also validates location names and provides country information.
    
    Error Handling:
    -------------
    - Invalid locations return a user-friendly error
    - API errors are caught and logged
    - Network timeouts are handled gracefully
    """
    try:
        # First get coordinates
        logger.info(f"Fetching coordinates for location: {location}")
        geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={location}&limit=1&appid={WEATHER_API_KEY}"
        geo_response = requests.get(geo_url)
        geo_response.raise_for_status()
        geo_data = geo_response.json()
        logger.info(f"Geocoding API response: {json.dumps(geo_data)}")
        
        if not geo_data:
            logger.info(f"Location not found: {location}")
            return f"❌ I couldn't find the location: {location}\nPlease check the spelling and try again!"
            
        lat = geo_data[0]["lat"]
        lon = geo_data[0]["lon"]
        
        # Get weather data
        logger.info(f"Fetching weather data for coordinates: {lat}, {lon}")
        weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric"
        weather_response = requests.get(weather_url)
        weather_response.raise_for_status()
        weather_data = weather_response.json()
        logger.info(f"Weather API response: {json.dumps(weather_data)}")
        
        # Format weather information
        temp = round(weather_data["main"]["temp"])
        feels_like = round(weather_data["main"]["feels_like"])
        description = weather_data["weather"][0]["description"].capitalize()
        humidity = weather_data["main"]["humidity"]
        wind_speed = round(weather_data["wind"]["speed"] * 3.6)  # Convert m/s to km/h
        location_name = geo_data[0]["name"]
        country = geo_data[0]["country"]
        
        logger.info(f"Successfully formatted weather data for {location_name}, {country}")
        return (
            f"🌍 Weather in {location_name}, {country}:\n"
            f"🌡️ Temperature: {temp}°C (Feels like {feels_like}°C)\n"
            f"☁️ Conditions: {description}\n"
            f"💧 Humidity: {humidity}%\n"
            f"💨 Wind Speed: {wind_speed} km/h"
        )
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weather: {e}", exc_info=True)
        return "❌ Sorry, I couldn't fetch the weather information at this time. Please try again later!"

def send_followup_response(interaction_token, response_data):
    """
    Send a followup message to Discord after processing is complete.
    
    Architecture Note:
    ----------------
    This is the second half of our "deferred response" pattern:
    1. verify_request.py sends "thinking..."
    2. This function sends the actual response
    
    Discord API Details:
    ------------------
    - Uses webhook URL format for followup messages
    - Requires bot token for authentication
    - Supports rich message formatting
    """
    url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{interaction_token}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bot {BOT_TOKEN}"
    }
    
    try:
        logger.info(f"Sending followup response to URL: {url}")
        logger.info(f"Response data: {json.dumps(response_data)}")
        response = requests.post(url, json=response_data, headers=headers)
        response.raise_for_status()
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response body: {response.text}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending followup response: {e}", exc_info=True)
        if hasattr(e.response, 'text'):
            logger.error(f"Error response body: {e.response.text}")
        return False

def lambda_handler(event, _):
    """
    Process Discord commands and send responses.
    
    This is the main command processor that:
    1. Routes commands to appropriate handlers
    2. Formats responses for Discord
    3. Handles errors gracefully
    
    Available Commands:
    ----------------
    /ping   - Simple bot health check
    /weather <location> - Get current weather
    
    Architecture Note:
    ----------------
    This Lambda is triggered asynchronously by verify_request.py,
    so we don't have the 3-second Discord timeout to worry about.
    """
    logger.info(f"Processing deferred command with event: {json.dumps(event)}")
    
    try:
        # Extract command information
        command = event["data"]["name"]
        interaction_token = event["token"]
        logger.info(f"Processing command: {command}")

        # Process commands
        if command == "ping":
            response_data = {
                "content": "Pong!"
            }
        elif command == "weather":
            location = next((opt["value"] for opt in event["data"].get("options", []) 
                           if opt["name"] == "location"), None)
            if not location:
                response_data = {
                    "content": "Please provide a location!"
                }
            else:
                weather_info = get_weather(location)
                response_data = {
                    "content": weather_info
                }
        else:
            response_data = {
                "content": f"Unknown command: {command}"
            }

        # Send the response via webhook
        logger.info("Attempting to send response")
        if not send_followup_response(interaction_token, response_data):
            logger.error("Failed to send followup response")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Failed to send response"})
            }

        logger.info("Command processed successfully")
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Command processed successfully"})
        }

    except Exception as e:
        logger.error(f"Error processing command: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }