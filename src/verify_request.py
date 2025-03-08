import json
import boto3
import logging
from discord_interactions import verify_key
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
secrets_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")

def verify_signature(event):
    """Verifies the Discord event signature"""
    try:
        secret_value = secrets_client.get_secret_value(SecretId="discord_keys")
        secrets = json.loads(secret_value["SecretString"])
        discord_public_key = secrets["DISCORD_PUBLIC_KEY"]
        
        headers = event.get("headers", {})
        raw_body = event.get("body", "")
        
        signature = headers.get("x-signature-ed25519")
        timestamp = headers.get("x-signature-timestamp")
        
        if not signature or not timestamp:
            return False
            
        is_verified = verify_key(raw_body.encode(), signature, timestamp, discord_public_key)
        logger.info(f"Event verification status: {is_verified}")
        return is_verified
    except ClientError as e:
        logger.error(f"Error retrieving secret: {e}")
        return False

def trigger_command_handler(event_body):
    """Triggers the command handler lambda asynchronously"""
    try:
        # Get the stack name from environment variables or use a default
        stack_name = "discord-bot"  # This should match your SAM application name
        function_name = f"{stack_name}-HandleCommandFunction-"  # AWS SAM will append a unique suffix
        
        # List functions to find the exact name
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
        logger.info("Successfully triggered command handler")
        return True
    except Exception as e:
        logger.error(f"Error triggering command handler: {e}")
        return False

def lambda_handler(event, context):
    """Main handler that verifies requests and defers to command handler"""
    try:
        # Verify the request
        if not verify_signature(event):
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "Invalid request signature"})
            }

        # Parse the request body
        event_body = json.loads(event.get("body", "{}"))
        
        # Handle Discord ping
        if event_body.get("type") == 1:
            return {
                "statusCode": 200,
                "body": json.dumps({"type": 1})
            }

        # For actual commands, acknowledge receipt and defer to command handler
        response_data = {
            "type": 5,  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
            "data": {
                "flags": 64  # EPHEMERAL flag, optional
            }
        }

        # Trigger command handler asynchronously
        trigger_command_handler(event_body)

        return {
            "statusCode": 200,
            "body": json.dumps(response_data)
        }

    except Exception as e:
        logger.error(f"Error in handler: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }