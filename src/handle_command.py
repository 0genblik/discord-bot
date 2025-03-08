import json
import os
import requests
import boto3
import logging
from datetime import datetime

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
secrets_client = boto3.client("secretsmanager")
secrets = secrets_client.get_secret_value(SecretId="discord_keys")
secrets_dict = json.loads(secrets["SecretString"])
BOT_TOKEN = secrets_dict["BOT_TOKEN"]
APPLICATION_ID = secrets_dict["APPLICATION_ID"]
WEATHER_API_KEY = secrets_dict["WEATHER_API_KEY"]

def get_weather(location):
    """Get weather information for a location using OpenWeather API"""
    try:
        # First get coordinates
        geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={location}&limit=1&appid={WEATHER_API_KEY}"
        geo_response = requests.get(geo_url)
        geo_response.raise_for_status()
        geo_data = geo_response.json()
        
        if not geo_data:
            return f"Could not find location: {location}"
            
        lat = geo_data[0]["lat"]
        lon = geo_data[0]["lon"]
        
        # Get weather data
        weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric"
        weather_response = requests.get(weather_url)
        weather_response.raise_for_status()
        weather_data = weather_response.json()
        
        # Format weather information
        temp = round(weather_data["main"]["temp"])
        feels_like = round(weather_data["main"]["feels_like"])
        description = weather_data["weather"][0]["description"].capitalize()
        humidity = weather_data["main"]["humidity"]
        wind_speed = round(weather_data["wind"]["speed"] * 3.6)  # Convert m/s to km/h
        location_name = geo_data[0]["name"]
        country = geo_data[0]["country"]
        
        return (
            f"🌍 Weather in {location_name}, {country}:\n"
            f"🌡️ Temperature: {temp}°C (Feels like {feels_like}°C)\n"
            f"☁️ Conditions: {description}\n"
            f"💧 Humidity: {humidity}%\n"
            f"💨 Wind Speed: {wind_speed} km/h"
        )
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weather data: {e}")
        return "Sorry, I couldn't fetch the weather information at this time."

def send_followup_response(interaction_token, response_data):
    """Sends a followup message to a deferred interaction"""
    # Use the application ID and interaction token for the webhook URL
    url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{interaction_token}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bot {BOT_TOKEN}"  # Add Authorization header
    }
    
    try:
        logger.info("Sending followup response")
        response = requests.post(url, json=response_data, headers=headers)
        response.raise_for_status()
        logger.info(f"Response status code: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error status code: {e.response.status_code if hasattr(e, 'response') else 'N/A'}")
        if hasattr(e.response, 'text'):
            logger.error(f"Error details: {e.response.text}")
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
        logger.error(f"Error processing command: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }