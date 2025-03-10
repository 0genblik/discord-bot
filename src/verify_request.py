"""
Entry Point Lambda Function for Discord Bot

This Lambda function serves as the primary entry point for all Discord interactions.
It implements Discord's Interactions architecture requirements:
1. Responds to PING requests (interaction_type 1) for endpoint validation
2. Handles command requests (interaction_type 2) by deferring to a second Lambda
3. Processes button clicks (interaction_type 3) for interactive components

Architecture Flow:
---------------
1. Discord -> API Gateway -> This Lambda
2. This Lambda validates the request signature
3. For commands: Triggers handle_command Lambda asynchronously
4. For buttons: Processes directly and responds

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

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
secrets_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")
logger.info("AWS clients initialized")

# Get secrets once at module level
secrets = secrets_client.get_secret_value(SecretId="discord_keys")
secrets_dict = json.loads(secrets["SecretString"])
BOT_TOKEN = secrets_dict["BOT_TOKEN"]
APPLICATION_ID = secrets_dict["APPLICATION_ID"]

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
    url = f"https://discord.com/api/v10/interactions/{interaction_id}/{interaction_token}/callback"
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, headers=headers, json=response_data)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
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
        discord_public_key = secrets_dict["DISCORD_PUBLIC_KEY"]
        
        headers = event.get("headers", {})
        raw_body = event.get("body", "")
        
        signature = headers.get("x-signature-ed25519")
        timestamp = headers.get("x-signature-timestamp")
        
        if not signature or not timestamp:
            logger.error("Missing signature or timestamp headers")
            return False
            
        is_verified = verify_key(raw_body.encode(), signature, timestamp, discord_public_key)
        logger.info(f"Event verification status: {is_verified}")
        return is_verified
    except Exception as e:
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
        # Get stack name from environment variable or use default
        stack_name = os.environ.get("AWS_SAM_STACK_NAME", "discord-bot")
        function_name = f"{stack_name}-HandleCommandFunction-"  # AWS SAM will append a unique suffix
        
        logger.info("Listing Lambda functions to find command handler")
        functions = lambda_client.list_functions()
        handle_command_function = next(
            (f["FunctionName"] for f in functions["Functions"] 
             if f["FunctionName"].startswith(function_name)),
            None
        )
        
        if not handle_command_function:
            raise Exception(f"Could not find function starting with {function_name}")
            
        logger.info(f"Invoking function: {handle_command_function}")
        response = lambda_client.invoke(
            FunctionName=handle_command_function,
            InvocationType="Event",
            Payload=json.dumps(event_body)
        )
        
        # Only log response metadata, not the full response object
        logger.info(f"Lambda invoke response status code: {response['ResponseMetadata']['HTTPStatusCode']}")
        return True
    except Exception as e:
        logger.error(f"Error triggering command handler: {str(e)}", exc_info=True)
        return False

def handle_button_interaction(event_body):
    """
    Process button click interactions (used for trivia answers).
    
    Unlike commands, button clicks are processed directly here because:
    1. They're simple and fast (just checking correct/incorrect)
    2. The question data is already in the message
    3. No external API calls needed
    
    Technical Flow:
    -------------
    1. Extract custom_id from clicked button
    2. Parse selected answer and correct answer index
    3. Find all possible answers from original message
    4. Compare selection with correct answer
    5. Send ephemeral response (only visible to clicker)
    
    Note: Button custom_ids follow format: trivia_answer_${selected}_${correct}
    This embeds both the user's choice and correct answer for verification.
    """
    try:
        logger.info("Processing button interaction")
        # Extract the custom_id from the button that was clicked
        custom_id = event_body["data"]["custom_id"]
        
        if custom_id.startswith("trivia_answer_"):
            # Extract the selected answer number and correct index
            _, _, selected_num, correct_index = custom_id.split("_")
            selected_num = int(selected_num)  # This is already 0-based from the button custom_id
            correct_index = int(correct_index)
            
            # Get message that contains the question
            message = event_body.get("message", {})
            content = message.get("content", "")
            logger.info(f"Processing answer for question: {content}")
            
            # Find all answers from the message content
            lines = content.split("\n")
            answers = []
            for line in lines:
                # Look for lines starting with numbers (1. 2. etc)
                if line.strip() and line.strip()[0].isdigit():
                    # Split after the number and period to get just the answer text
                    answer = line.split(".", 1)[1].strip()
                    answers.append(answer)
            
            logger.info(f"Found answers: {answers}")
            logger.info(f"Selected num: {selected_num}, Correct index: {correct_index}")
            
            if selected_num < len(answers):  # Changed <= to < since we're using 0-based index
                selected_answer = answers[selected_num]  # Use selected_num directly since it's already 0-based
                correct_answer = answers[correct_index]
                is_correct = selected_num == correct_index
                
                if is_correct:
                    response_message = f"✅ Correct! The answer was: {correct_answer}"
                else:
                    response_message = f"❌ Sorry, that's incorrect. The correct answer was: {correct_answer}"
                
                logger.info(f"Sending response: {response_message}")
                response_data = {
                    "type": 4,  # MESSAGE_WITH_SOURCE
                    "data": {
                        "content": response_message,
                        "flags": 64  # EPHEMERAL - only the user who clicked can see this
                    }
                }
                return response_data
    except Exception as e:
        logger.error(f"Error handling button interaction: {e}", exc_info=True)
    
    return {
        "type": 4,
        "data": {
            "content": "Sorry, there was an error processing your answer.",
            "flags": 64
        }
    }

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
    3 = MESSAGE_COMPONENT (button clicks)
    
    Response Types:
    -------------
    1 = PONG (respond to ping)
    4 = MESSAGE (direct response)
    5 = DEFERRED_MESSAGE (bot is thinking...)
    
    Architecture Flow:
    ----------------
    PING -> Immediate response
    COMMAND -> Defer to handle_command Lambda
    BUTTON -> Process directly here
    """
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Verify the request
        if not verify_signature(event):
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "Invalid request signature"})
            }

        # Parse the request body
        event_body = json.loads(event.get("body", "{}"))
        interaction_type = event_body.get("type")
        logger.info(f"Processing interaction type: {interaction_type}")
        
        if interaction_type == 1:  # PING
            logger.info("Handling PING interaction")
            return {
                "statusCode": 200,
                "body": json.dumps({"type": 1})
            }
        elif interaction_type == 2:  # APPLICATION_COMMAND
            logger.info(f"Handling command: {event_body.get('data', {}).get('name')}")
            # For commands, acknowledge receipt and defer to command handler
            response_data = {
                "type": 5,  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
            }
            
            # Trigger command handler asynchronously
            if not trigger_command_handler(event_body):
                logger.error("Failed to trigger command handler")
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": "Failed to process command"})
                }
            
            logger.info("Successfully deferred command and triggered handler")
            return {
                "statusCode": 200,
                "body": json.dumps(response_data)
            }
        elif interaction_type == 3:  # MESSAGE_COMPONENT (Button clicks)
            logger.info("Handling button interaction")
            response_data = handle_button_interaction(event_body)
            
            return {
                "statusCode": 200,
                "body": json.dumps(response_data)
            }
        else:
            logger.warning(f"Unknown interaction type: {interaction_type}")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Unknown interaction type: {interaction_type}"})
            }

    except Exception as e:
        logger.error(f"Error in handler: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }