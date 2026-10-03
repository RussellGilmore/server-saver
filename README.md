# Server Saver

Automatically shut down EC2 instances at midnight EST to prevent runaway costs
from forgotten instances.

## Features

- 🕐 **Scheduled shutdown** at midnight EST (configurable) using EventBridge
  Scheduler
- 📧 **Email notifications** via SNS when instances are stopped
- 🏷️ **Tag-based targeting** - only stops instances tagged with
  `AutoShutdown: true`
- 📊 **CloudWatch alarms** for Lambda errors
- 🔒 **Least-privilege IAM** - only permissions needed to stop specified
  instances
- ✅ **Idempotent** - safely handles already-stopped instances

## Prerequisites

- AWS CLI
- AWS SAM CLI
- UV
- Python 3.13
- Docker (for `sam build --use-container`)

**USE THIS IF USING RANCHER DESKTOP AND NEED LOCAL INVOKE:**

> `export DOCKER_HOST=unix://$HOME/.rd/docker.sock`

You will also need to switch from containerd to dockerd in Rancher Desktop
settings.

## Project Structure

```
server-saver/
├── src/
│   └── shutdown/
│       ├── __init__.py
│       ├── handler.py      # Lambda function code
├── tests/
│   ├── __init__.py
│   └── test_handler.py     # Unit tests with moto mocking
├── template.yaml           # SAM template
├── samconfig.toml          # SAM deployment configuration
├── pyproject.toml          # Python project & tooling config
├── uv.lock                 # UV lockfile (committed for reproducibility)
├── Makefile                # Common commands
├── .pre-commit-config.yaml # Pre-commit hooks
└── README.md
```

## Development Setup

```bash
make install-dev
```

## Deploying

### 1. Tag Your EC2 Instances

Add the `AutoShutdown` tag to instances you want to automatically shut down:

```bash
aws ec2 create-tags \
  --resources i-0123456789abcdef0 \
  --tags Key=AutoShutdown,Value=true
```

### 2. Build and Deploy

```bash
# First time deployment (guided)
sam build
sam deploy --guided

# You'll be prompted for:
# - Stack name: server-saver
# - AWS Region: us-east-1
# - InstanceIds: i-0123456789abcdef0 (comma-separated if multiple)
# - NotificationEmail: your@email.com
```

### 3. Confirm SNS Subscription

Check your email and confirm the SNS subscription to receive notifications.

### Updating Instance List

```bash
sam deploy --parameter-overrides \
  InstanceIds="i-abc123,i-def456,i-ghi789" \
  NotificationEmail="you@example.com"
```

### Changing the Schedule

To run at a different time (e.g., 11 PM):

```bash
sam deploy --parameter-overrides \
  InstanceIds="i-abc123" \
  NotificationEmail="you@example.com" \
  ScheduleExpression="cron(0 23 * * ? *)"
```

### Cleanup

```bash
sam delete --stack-name server-saver
```

## Testing

> You can test this with a real instance ID in a local env file. The function
> will attempt to describe the instance but won't stop it without proper
> permissions.

```json
{
    "ShutdownFunction": {
        "INSTANCE_IDS": "<YOUR_TEST_INSTANCE_IDS>",
        "SNS_TOPIC_ARN": ""
    }
}
```

### Run Tests

```bash
make test
```

### Run Tests with Coverage

```bash
make test-cov
```

### Local Lambda Invocation

```bash
# Copy example env file
cp local-env.json.example local-env.json

# Edit with your instance ID
vim local-env.json

# Build and invoke locally
make build
make local-invoke
```

**Note:** Local invocation with real AWS credentials will attempt to describe
instances but won't stop them without proper permissions.

## Commands

| Command                | Description                                 |
| ---------------------- | ------------------------------------------- |
| `make help`            | Show all available commands                 |
| `make install`         | Install production dependencies only        |
| `make install-dev`     | Install all dependencies + pre-commit hooks |
| `make test`            | Run pytest                                  |
| `make test-cov`        | Run tests with coverage report              |
| `make type-check`      | Run mypy type checker                       |
| `make pre-commit`      | Run pre-commit on all files                 |
| `make build`           | Build SAM application                       |
| `make build-container` | Build SAM using container                   |
| `make deploy`          | Build and deploy to AWS                     |
| `make deploy-guided`   | Build and deploy with guided prompts        |
| `make deploy-dev`      | Deploy to dev environment                   |
| `make deploy-prod`     | Deploy to prod environment                  |
| `make validate`        | Validate SAM template                       |
| `make local-invoke`    | Invoke function locally with test event     |
| `make logs`            | Tail Lambda logs                            |
| `make clean`           | Remove build artifacts                      |
| `make lock`            | Update uv.lock file                         |
| `make ci-check`        | Run all CI checks                           |

## Configuration

### Parameters

| Parameter            | Description                              | Default                        |
| -------------------- | ---------------------------------------- | ------------------------------ |
| `InstanceIds`        | Comma-separated list of EC2 instance IDs | (required)                     |
| `NotificationEmail`  | Email for shutdown notifications         | (required)                     |
| `ScheduleExpression` | Cron expression for schedule             | `cron(0 0 * * ? *)` (midnight) |
| `ScheduleTimezone`   | Timezone for schedule                    | `America/New_York`             |
| `Environment`        | Environment name (dev/staging/prod)      | `prod`                         |

## How It Works

1. **EventBridge Scheduler** triggers the Lambda function at midnight EST daily
2. **Lambda** reads instance IDs from the `INSTANCE_IDS` environment variable
3. For each instance:
    - Checks current state via `ec2:DescribeInstances`
    - If running, stops it via `ec2:StopInstances`
    - If already stopped, logs and skips
4. **SNS notification** sent with results summary
5. **CloudWatch alarm** fires if Lambda encounters errors

## IAM Permissions

The Lambda function has these permissions:

- `ec2:DescribeInstances` - Check instance states (all instances)
- `ec2:StopInstances` - Stop instances (only those tagged `AutoShutdown: true`)
- `sns:Publish` - Send notifications to the shutdown topic
