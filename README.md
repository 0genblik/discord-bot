# Discord Bot with AWS Lambda

This project implements a Discord bot using AWS Lambda serverless functions. The bot currently supports weather queries, a ping command, and an interactive trivia game.

## Architecture Overview

```ascii
                                             AWS Cloud
+----------------+        +-----------------+          +------------------------+
|                |  HTTP  |                |          |                        |
| Discord API    +------->+  API Gateway   +--------->+ verify_request Lambda |
|                |        |                |          |                        |
+----------------+        +-----------------+          +------------+----------+
                                                                  |
                                                                  | Async Invoke
                                                                  v
                                                     +------------------------+
                                                     |                        |
                                                     | handle_command Lambda  |
                                                     |                        |
                                                     +------------------------+
                                                              |
                                                              | Uses
                                                              v
                                                     +------------------------+
                                                     |   AWS Secrets Manager  |
                                                     |   (Bot Token & Keys)   |
                                                     +------------------------+
```

## How It Works

### 1. AWS Lambda Functions

AWS Lambda is a serverless compute service that lets you run code without provisioning or managing servers. Our bot uses two Lambda functions:

#### verify_request Lambda (Entry Point)
- Receives all incoming Discord interactions
- Verifies the request signature for security
- For commands, triggers the handle_command Lambda asynchronously
- For button clicks (trivia answers), processes them directly
- Returns immediate responses to Discord

#### handle_command Lambda
- Processes the actual command logic (weather, trivia, ping)
- Makes external API calls when needed (OpenWeather API, OpenTrivia DB)
- Returns formatted responses back to Discord

### 2. Project Structure

```
discord-bot/
├── src/
│   ├── verify_request.py    # Entry point Lambda function
│   ├── handle_command.py    # Command processing Lambda function
│   └── register_commands.py # Script to register Discord commands
├── package/                 # Lambda layer dependencies
├── template.yaml           # AWS SAM template
└── requirements.txt        # Python dependencies
```

### 3. Key Components

#### YAML Template (template.yaml)
YAML (YAML Ain't Markup Language) is a human-readable data serialization format. In AWS, we use it to define our infrastructure as code. Our template.yaml:
- Defines both Lambda functions
- Sets up API Gateway
- Configures IAM (Identity and Access Management) permissions - AWS's system for controlling who and what has access to different AWS services. Think of it as a security system where you give specific keys (permissions) to specific people or services (roles) to access specific rooms (AWS resources).
- Creates a Lambda Layer for dependencies
- Sets environment variables
- Configures logging

#### Dependencies Management
Dependencies are handled through a Lambda Layer, which is a way to share code and libraries between functions:
1. Dependencies are listed in requirements.txt
2. They are installed into the package/ directory
3. The template.yaml bundles them as a Layer
4. Both Lambda functions can access these shared dependencies

### 4. Command Flow

1. User types a command in Discord (e.g., /weather london)
2. Discord sends an HTTP POST to our API Gateway endpoint
3. API Gateway forwards the request to verify_request Lambda
4. verify_request:
   - Validates the request signature
   - For commands: Triggers handle_command Lambda asynchronously
   - For button clicks: Processes the interaction directly
5. handle_command (for commands):
   - Processes the command logic
   - Makes any necessary API calls
   - Formats and sends the response back to Discord

### 5. Security

- Discord interactions are verified using Ed25519 signatures
- Bot tokens and API keys are stored in AWS Secrets Manager
- IAM roles limit what each Lambda function can access
- API Gateway only accepts POST requests with specific headers

### 6. Building and Deployment

The project uses AWS SAM (Serverless Application Model) for building and deployment:

1. **Build Process:**
   ```bash
   sam build
   ```
   - Installs dependencies in package/
   - Creates deployment packages
   - Prepares Lambda Layer

2. **Deployment:**
   ```bash
   sam deploy
   ```
   - Uploads code to AWS
   - Creates/updates Lambda functions
   - Configures API Gateway
   - Sets up IAM roles

### 7. Features

#### Weather Command
- Uses OpenWeather API
- Provides temperature, conditions, humidity, and wind speed
- Handles location validation

#### Trivia Command
- Fetches random questions from OpenTrivia DB
- Interactive buttons for answers
- Supports category selection
- Shows immediate feedback

#### Ping Command
- Simple health check
- Verifies bot responsiveness

## Development Setup

1. Install AWS SAM CLI
2. Configure AWS credentials
3. Create Discord application and bot
4. Store secrets in AWS Secrets Manager:
   - BOT_TOKEN
   - APPLICATION_ID
   - DISCORD_PUBLIC_KEY
   - WEATHER_API_KEY

## Environment Variables

Required secrets in AWS Secrets Manager (discord_keys):
- BOT_TOKEN: Discord bot token
- APPLICATION_ID: Discord application ID
- DISCORD_PUBLIC_KEY: Discord public key for request verification
- WEATHER_API_KEY: OpenWeather API key

## Command Registration

After deployment, register Discord commands:
```bash
python src/register_commands.py
```

## Technical Concepts Explained

### Serverless Architecture
Unlike traditional servers that run continuously, serverless functions only run when needed. In our case:
- When Discord sends a command, AWS spins up a Lambda instance
- The function processes the request and then shuts down
- You only pay for the milliseconds your code runs
- AWS handles all scaling, from 0 to thousands of concurrent requests

### Why Two Lambda Functions?
We split the bot into two functions because Discord requires a response within 3 seconds:
1. verify_request responds quickly with "thinking..."
2. handle_command takes its time to process the actual command
This pattern is called "deferred response" in Discord terminology.

### Lambda Layers
Think of Lambda Layers as shared libraries:
- Without layers, we'd need to include all dependencies in each function
- With layers, dependencies are packaged once and shared
- This makes deployments faster and reduces code duplication
- Our layer contains packages like 'requests', 'boto3', and 'discord-interactions'

### API Gateway Explained
API Gateway acts as a front door to our Lambda:
- It converts HTTP requests to a format Lambda understands
- Handles request routing and validation
- Provides a fixed HTTPS endpoint for Discord to call
- Can throttle requests to prevent abuse

### IAM Roles and Permissions
Each Lambda function has specific permissions:
- verify_request can invoke handle_command
- Both can access Secrets Manager
- Neither can access other AWS services
This follows the "principle of least privilege"

### Discord Interaction Security
Every request from Discord includes:
1. A timestamp
2. The request body
3. A cryptographic signature
Our verify_request function checks these to prevent fake requests.

## Common Development Tasks

### Adding a New Command
1. Add command definition in register_commands.py
2. Add handling logic in handle_command.py
3. Run register_commands.py to update Discord
4. Deploy with `sam deploy`

### Updating Dependencies
1. Add package to requirements.txt
2. Run `sam build` to update layer
3. Deploy with `sam deploy`

### Debugging
- Check CloudWatch Logs for each function
- API Gateway logs show incoming requests
- Use log levels (INFO/ERROR) to trace issues

### Local Testing
You can test locally using:
```bash
sam local invoke verify_request -e test-events/discord-command.json
```

## Architecture Benefits

1. **Scalability:** AWS Lambda automatically scales based on load
2. **Cost-Effective:** Pay only for actual usage
3. **Low Maintenance:** No server management required
4. **High Availability:** AWS handles redundancy
5. **Security:** Built-in security features and easy secrets management