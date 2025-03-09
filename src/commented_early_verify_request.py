"""
Entry Point Lambda Function for Discord Bot

This Lambda function serves as the primary entry point for all Discord interactions.
It implements Discord's Interactions architecture requirements:
1. Responds to PING requests (interaction_type 1) for endpoint validation
2. Handles command requests (interaction_type 2) by deferring to a second Lambda

Architecture Flow:
---------------
1. Discord -> API Gateway -> This Lambda
2. This Lambda validates the request signature
3. For commands: Triggers handle_command Lambda asynchronously

Why This Design?
--------------
Discord requires responses within 3 seconds. Some commands (like weather)
might take longer. We solve this by:
1. Immediately acknowledging receipt ("bot is thinking...")
2. Asynchronously triggering another Lambda for actual processing
This pattern is called "deferred response" in Discord terminology.

Security:
--------
Every Discord request includes:
- Request body
- Timestamp
- Ed25519 signature
We verify these using discord-interactions library to prevent forgery.
"""

import json
import boto3
import logging
import requests
from discord_interactions import verify_key
from botocore.exceptions import ClientError
import os

# Set up logging for debugging and operational insights.
# logger will capture messages at or above INFO level.
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients at the top-level for reuse across function invocations.
# This helps avoid overhead from re-initializing them each time Lambda is invoked.
secrets_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")
logger.info("AWS clients initialized")

# Retrieve secrets from AWS Secrets Manager once at module load time (outside lambda_handler).
# This is a performance optimization—fetch secrets only once instead of on every invocation.
secrets = secrets_client.get_secret_value(SecretId="discord_keys")
secrets_dict = json.loads(secrets["SecretString"])
BOT_TOKEN = secrets_dict["BOT_TOKEN"]            # Discord bot token (used in other places if needed).
APPLICATION_ID = secrets_dict["APPLICATION_ID"]  # Discord application ID (useful for specific interactions).

def send_interaction_response(interaction_id, interaction_token, response_data):
    """
    Send an immediate response to a Discord interaction.
    
    Discord expects responses within 3 seconds. This function handles the immediate
    response requirement, while longer operations are deferred to handle_command Lambda.
    
    Parameters:
    -----------
    interaction_id : str
        The unique ID of the Discord interaction
    interaction_token : str
        Discord's temporary token for responding to this interaction
    response_data : dict
        The response payload to send back to Discord
        
    Architecture Note:
    -----------------
    This is one of two ways we respond to Discord:
    1. Immediate responses (this function)
    2. Followup messages (used in handle_command.py)
    """
    # Construct the Discord API endpoint using the interaction's ID and token.
    url = f"https://discord.com/api/v10/interactions/{interaction_id}/{interaction_token}/callback"
    
    # Set the headers to indicate JSON content.
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        # Send a POST request to Discord to respond to the interaction.
        response = requests.post(url, headers=headers, json=response_data)
        
        # If Discord returns an HTTP error (4xx or 5xx), raise_for_status() will throw an exception.
        response.raise_for_status()
        
        # If successful, we return True to indicate the immediate response was sent successfully.
        return True
    except requests.exceptions.RequestException as e:
        # Log the error if there's any issue (network, HTTP error, etc.).
        logger.error(f"Error sending interaction response: {e}")
        return False

def verify_signature(event):
    """
    Verifies the cryptographic signature of Discord requests.
    
    Security Deep Dive:
    -----------------
    1. Discord sends three key pieces:
       - Request body (the actual command/interaction)
       - Timestamp (when the request was sent)
       - Ed25519 signature (cryptographic proof)
       
    2. We verify these using Discord's public key to ensure:
       - Request really came from Discord
       - Request hasn't been tampered with
       - Request isn't too old (replay attack protection)
       
    This is a critical security feature required by Discord.
    """
    try:
        # The public key is stored in the same secret dictionary used above.
        discord_public_key = secrets_dict["DISCORD_PUBLIC_KEY"]
        
        # Extract headers and body from the API Gateway event.
        # event["headers"] holds all incoming HTTP headers.
        headers = event.get("headers", {})
        raw_body = event.get("body", "")
        
        # The Ed25519 signature is in the 'x-signature-ed25519' header.
        # The timestamp used to prevent replay attacks is in 'x-signature-timestamp'.
        signature = headers.get("x-signature-ed25519")
        timestamp = headers.get("x-signature-timestamp")
        
        # If either signature or timestamp is missing, it's an invalid request.
        if not signature or not timestamp:
            logger.error("Missing signature or timestamp headers")
            return False
            
        # Use the verify_key function provided by discord_interactions to verify authenticity.
        # If this fails, it means the request didn't come from Discord or the signature is invalid.
        is_verified = verify_key(raw_body.encode(), signature, timestamp, discord_public_key)
        logger.info(f"Event verification status: {is_verified}")
        return is_verified
    except Exception as e:
        # Catch any unexpected exceptions (e.g. missing keys, library errors, etc.)
        logger.error(f"Error verifying signature: {e}", exc_info=True)
        return False

def trigger_command_handler(event_body):
    """
    Triggers the command handler Lambda function asynchronously.
    
    Architecture Note:
    ----------------
    This is where the two Lambda functions connect. We:
    1. Find the handle_command Lambda by name pattern
    2. Invoke it asynchronously (InvocationType="Event")
    3. Don't wait for its response
    
    Why Async?
    ---------
    - Discord needs a response in 3 seconds
    - Commands might take longer (API calls, processing)
    - Async lets us acknowledge quickly and process later
    
    AWS Integration:
    --------------
    - Uses Lambda list_functions to find the handler dynamically
    - AWS SAM automatically adds required IAM permissions
    - Function names are based on CloudFormation stack name
    """
    try:
        # Retrieve the stack name from environment variables.
        # This is inserted by the SAM template to dynamically identify resources.
        stack_name = os.environ.get("AWS_SAM_STACK_NAME", "discord-bot")
        
        # Construct the beginning of the function name. SAM adds a unique suffix after deployment.
        function_name = f"{stack_name}-HandleCommandFunction-"
        
        logger.info("Listing Lambda functions to find command handler")
        functions = lambda_client.list_functions()
        
        # We look through the list of Lambda functions to find one that starts with the above prefix.
        # This works because CloudFormation/SAM might append random characters to the end.
        handle_command_function = next(
            (f["FunctionName"] for f in functions["Functions"] 
             if f["FunctionName"].startswith(function_name)),
            None
        )
        
        # If we don't find a match, we raise an exception because we can't invoke the handler.
        if not handle_command_function:
            raise Exception(f"Could not find function starting with {function_name}")
            
        logger.info(f"Invoking function: {handle_command_function}")
        
        # Invoke the command handler Lambda asynchronously.
        # InvocationType="Event" means we don't wait for a response; we just fire and forget.
        response = lambda_client.invoke(
            FunctionName=handle_command_function,
            InvocationType="Event",
            Payload=json.dumps(event_body)  # The data we want the command handler to process.
        )
        
        # Log only basic info about the result (status code).
        # Full payload isn't needed here, and might contain sensitive info.
        logger.info(f"Lambda invoke response status code: {response['ResponseMetadata']['HTTPStatusCode']}")
        
        # Return True if the function was successfully invoked (meaning no immediate exception).
        return True
    except Exception as e:
        # Log any errors (e.g., function not found, permissions issues, etc.)
        logger.error(f"Error triggering command handler: {str(e)}", exc_info=True)
        return False

def lambda_handler(event, context):
    """
    Main entry point for all Discord interactions.
    
    This is where the Discord -> AWS integration begins:
    1. API Gateway receives Discord's HTTPS POST
    2. Converts it to Lambda event format
    3. Triggers this handler
    
    Interaction Types:
    ----------------
    1 = PING (Discord checking if endpoint is valid)
    2 = APPLICATION_COMMAND (slash commands)
    
    Response Types:
    -------------
    1 = PONG (respond to ping)
    4 = MESSAGE (direct response)
    5 = DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE (bot is thinking...)
    
    Architecture Flow:
    ----------------
    PING -> Immediate response
    COMMAND -> Defer to handle_command Lambda
    """
    try:
        # Log the raw event for debugging.
        # The event comes from API Gateway, which transforms the original HTTP request from Discord.
        logger.info(f"Received event: {json.dumps(event)}")
        
        # First, verify the request's authenticity using the signature verification method.
        if not verify_signature(event):
            # If invalid, return a 401 (Unauthorized) with an error message.
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "Invalid request signature"})
            }

        # Parse the JSON body from the API Gateway event.
        event_body = json.loads(event.get("body", "{}"))
        
        # Extract the "type" from the Discord interaction.
        interaction_type = event_body.get("type")
        logger.info(f"Processing interaction type: {interaction_type}")
        
        if interaction_type == 1:  # PING
            # Interaction type 1 is a health check from Discord to confirm our endpoint is valid.
            logger.info("Handling PING interaction")
            
            # We must return a "PONG" response (type = 1) within 3 seconds or Discord will consider us invalid.
            # This is a synchronous return, so we don't have to call the second Lambda for PING.
            return {
                "statusCode": 200,
                "body": json.dumps({"type": 1})
            }
        elif interaction_type == 2:  # APPLICATION_COMMAND
            # Interaction type 2 is a slash command or other command-based interaction from Discord.
            logger.info(f"Handling command: {event_body.get('data', {}).get('name')}")
            
            # We want to immediately acknowledge the command to Discord so it doesn't timeout.
            # This response effectively says "the bot is thinking...", giving us more time to process the command.
            response_data = {
                "type": 5,  # Discord's DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE response
            }
            
            # Now we call our second Lambda (handle_command) asynchronously to do the actual processing.
            # If this fails for any reason, we log the error and return a 500 to Discord.
            if not trigger_command_handler(event_body):
                logger.error("Failed to trigger command handler")
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": "Failed to process command"})
                }
            
            # If the invocation was successful, we return a 200 with a "deferred" response.
            logger.info("Successfully deferred command and triggered handler")
            return {
                "statusCode": 200,
                "body": json.dumps(response_data)
            }
        
        else:
            # Any other interaction type is not recognized by our bot logic right now.
            logger.warning(f"Unknown interaction type: {interaction_type}")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Unknown interaction type: {interaction_type}"})
            }

    except Exception as e:
        # Catch all exceptions to avoid crashing the Lambda and provide a clear error response.
        logger.error(f"Error in handler: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }
