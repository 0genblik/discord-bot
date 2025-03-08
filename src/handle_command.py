import json
import requests
import boto3
import logging
import html
import random
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

def get_trivia_question(category=None):
    """Get a random trivia question from OpenTDB"""
    try:
        # Build the API URL with base64 encoding to avoid special character issues
        url = "https://opentdb.com/api.php?amount=1&encode=base64"
        if category:
            url += f"&category={category}"
        logger.info(f"Fetching trivia question from URL: {url}")
        
        response = requests.get(url, timeout=5)  # Add timeout
        response.raise_for_status()
        data = response.json()
        logger.info(f"Received trivia API response code: {data.get('response_code')}")
        
        if data["response_code"] != 0:
            logger.error(f"Error from trivia API, response code: {data['response_code']}")
            return None
            
        question_data = data["results"][0]
        
        # Decode base64 and unescape HTML
        try:
            import base64
            
            def decode_base64(text):
                return html.unescape(base64.b64decode(text).decode('utf-8'))
            
            question = decode_base64(question_data["question"])
            correct_answer = decode_base64(question_data["correct_answer"])
            incorrect_answers = [decode_base64(a) for a in question_data["incorrect_answers"]]
            category = decode_base64(question_data["category"])
            difficulty = decode_base64(question_data["difficulty"]).capitalize()
            
            logger.info("Successfully decoded trivia data")
        except Exception as e:
            logger.error(f"Error decoding trivia data: {e}", exc_info=True)
            return None
        
        # Combine and shuffle answers
        all_answers = [correct_answer] + incorrect_answers
        random.shuffle(all_answers)
        
        # Create a formatted response
        response_text = (
            f"🎯 **{category}** ({difficulty})\n\n"
            f"**Question:** {question}\n\n"
            "**Choose your answer:**\n"
        )
        
        # Add answers with numbers (no emojis)
        for i, answer in enumerate(all_answers, 1):
            response_text += f"{i}. {answer}\n"
            
        logger.info("Successfully formatted trivia question")
        return {
            "text": response_text,
            "correct_answer": correct_answer,
            "answers": all_answers
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching trivia: {e}", exc_info=True)
        return None

def get_number_emoji(number):
    """Convert a number to its emoji equivalent"""
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    return emojis[number - 1] if 1 <= number <= len(emojis) else str(number)

def get_weather(location):
    """Get weather information for a location using OpenWeather API"""
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
    """Sends a followup message to a deferred interaction"""
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
    Handles deferred Discord commands and sends responses via webhook
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
        elif command == "trivia":
            # Get optional category from command options
            options = event["data"].get("options", [])
            category = next((opt["value"] for opt in options if opt["name"] == "category"), None)
            logger.info(f"Fetching trivia question for category: {category}")
            
            # Get a random trivia question
            question_data = get_trivia_question(category)
            
            if question_data:
                # Find the index of the correct answer
                correct_index = question_data["answers"].index(question_data["correct_answer"])
                logger.info(f"Correct answer index: {correct_index}")
                
                # Simplify the button structure
                buttons = []
                for i in range(len(question_data["answers"])):
                    buttons.append({
                        "type": 2,  # BUTTON
                        "style": 1,  # PRIMARY
                        "custom_id": f"trivia_answer_{i}_{correct_index}",
                        "label": str(i + 1)
                    })
                
                response_data = {
                    "content": question_data["text"],
                    "components": [{
                        "type": 1,  # ACTION_ROW
                        "components": buttons
                    }]
                }
                
                logger.info(f"Prepared trivia response: {json.dumps(response_data)}")
            else:
                response_data = {
                    "content": "Sorry, I couldn't fetch a trivia question. Please try again!"
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