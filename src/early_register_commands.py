"""
Discord Command Registration Script

This script registers slash commands with Discord's API. It must be run:
1. After initial bot deployment
2. Any time you add/modify/remove commands
3. Any time you want to update command descriptions or options

Architecture Note:
---------------
While verify_request.py and handle_command.py run in AWS Lambda,
this script runs locally during development/deployment.

Why Register Commands?
------------------
Discord requires explicit registration of slash commands to:
- Show command hints to users
- Enable command autocomplete
- Validate command options before sending to your bot
- Control command permissions

Security:
--------
Uses bot token from AWS Secrets Manager for authentication.
In production, you might want to use a dedicated registration token
with more limited permissions.
"""

import os
import sys
import boto3
import requests
import json

# Set AWS region explicitly for UK (London) 
AWS_REGION = "eu-west-2"  # London AWS region 

# Create an AWS Secrets Manager client with the specified region 
secrets_client = boto3.client("secretsmanager", region_name=AWS_REGION)
secrets = secrets_client.get_secret_value(SecretId="discord_keys")
BOT_TOKEN = json.loads(secrets["SecretString"])["BOT_TOKEN"]
APPLICATION_ID = json.loads(secrets["SecretString"])["APPLICATION_ID"]
print(APPLICATION_ID)

# Define all available commands
# Each command definition includes:
# - name: What users type after the /
# - description: What users see in the command picker
# - options: Additional parameters (optional)
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

# Discord API endpoint for global command registration
# Using v10 of the API for latest features
URL = f"https://discord.com/api/v10/applications/{str(APPLICATION_ID)}/commands"

# Headers required by Discord API:
# - Content-Type: Always application/json for command registration
# - Authorization: Bot token for authentication
headers = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json"
}

# Use PUT instead of POST to replace all commands at once
# This ensures removed commands are properly deleted
response = requests.put(URL, headers=headers, json=COMMANDS)
if response.status_code in [200, 201]:
    print("Successfully registered all commands!")
    for cmd in response.json():
        print(f"- {cmd['name']}: {cmd['id']}")
else:
    print(f"Error registering commands: {response.text}")
