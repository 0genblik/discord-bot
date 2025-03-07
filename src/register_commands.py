
import os
import sys
import boto3
import requests
import json

# Set AWS region explicitly for UK (London) 
AWS_REGION = "eu-west-2" # London AWS region 

# Create an AWS Secrets Manager client with the specified region 
secrets_client = boto3.client("secretsmanager", region_name=AWS_REGION)
secrets = secrets_client.get_secret_value(SecretId="discord_keys")
BOT_TOKEN = json.loads(secrets["SecretString"])["BOT_TOKEN"]
APPLICATION_ID = json.loads(secrets["SecretString"])["APPLICATION_ID"]


COMMANDS = [
    {
        "name": "ping",
        "description": "Check if the bot is online."
    },
    {
        "name": "weather",
        "description": "Get the weather for a specific location.",
        "options": [
            {
                "name": "location",
                "description": "Enter the location.",
                "type": 3,  # Type 3 = string
                "required": True
            }
        ]
    }
]

# API URL for registering commands
URL = f"https://discord.com/api/v10/applications/{str(APPLICATION_ID)}/commands"


headers = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json"
}

for command in COMMANDS:
    response = requests.post(
        f"https://discord.com/api/v10/applications/{str(APPLICATION_ID)}/commands", 
        headers=headers, 
        json=command
    )
    if response.status_code in [200, 201]:  # Accept both HTTP 200 and 201 as success
        print(f"Command '{command['name']}' registered successfully! ID: {response.json().get('id')}")
    else:
        print(f"Error registering command '{command['name']}': {response.text}")
