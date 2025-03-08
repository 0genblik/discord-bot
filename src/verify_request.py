import json
import boto3
import logging
import requests
from discord_interactions import verify_key
from botocore.exceptions import ClientError

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
    """Send an immediate response to an interaction"""
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
    """Verifies the Discord event signature"""
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
    """Triggers the command handler lambda asynchronously"""
    try:
        # Get the stack name from environment variables or use a default
        stack_name = "discord-bot"  # This should match your SAM application name
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
    """Handle button click interactions"""
    try:
        # Extract the custom_id from the button that was clicked
        custom_id = event_body["data"]["custom_id"]
        
        if custom_id.startswith("trivia_answer_"):
            # Extract the selected answer number and correct index
            _, _, selected_num, correct_index = custom_id.split("_")
            selected_num = int(selected_num)
            correct_index = int(correct_index)
            
            # Get message that contains the question
            message = event_body.get("message", {})
            content = message.get("content", "")
            
            # Find all answers from the message content
            lines = content.split("\n")
            answers = []
            for line in lines:
                # Look for lines starting with number emojis
                if any(line.strip().startswith(emoji) for emoji in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]):
                    # Split after the emoji to get just the answer text
                    answer = line.split(" ", 1)[1].strip()
                    answers.append(answer)
            
            if selected_num <= len(answers):
                selected_answer = answers[selected_num - 1]
                correct_answer = answers[correct_index]
                is_correct = selected_num - 1 == correct_index
                
                if is_correct:
                    response_message = f"✅ Correct! The answer was: {correct_answer}"
                else:
                    response_message = f"❌ Sorry, that's incorrect. The correct answer was: {correct_answer}"
                
                response_data = {
                    "type": 4,  # MESSAGE_WITH_SOURCE
                    "data": {
                        "content": response_message,
                        "flags": 64  # EPHEMERAL - only the user who clicked can see this
                    }
                }
                return response_data
    except Exception as e:
        logger.error(f"Error handling button interaction: {e}")
    
    return {
        "type": 4,
        "data": {
            "content": "Sorry, there was an error processing your answer.",
            "flags": 64
        }
    }

def lambda_handler(event, context):
    """Main handler that verifies requests and processes interactions"""
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