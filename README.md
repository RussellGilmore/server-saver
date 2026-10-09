# Server Saver

Automatically shut down EC2 instances on a schedule (midnight US Eastern by
default) to prevent runaway costs from forgotten instances.

## Features

- 🕐 **Scheduled shutdown** at midnight Eastern time (configurable) using
  EventBridge Scheduler
- 📧 **Email notifications** via SNS with a summary of each run
- 🏷️ **Tag-gated permissions** - the function can only stop instances tagged
  `AutoShutdown: true`
- 📊 **CloudWatch alarm** for Lambda errors
- 🔒 **Least-privilege IAM** - only the permissions needed to describe and stop
  tagged instances
- ✅ **Idempotent** - safely handles already-stopped instances

## How Targeting Works

An instance is stopped only when **both** of these are true:

1. Its ID is listed in the `InstanceIds` parameter
2. It is tagged `AutoShutdown: true`

The list tells the function _what to try_ to stop; the tag is enforced by IAM
and controls _what it is allowed_ to stop.

> Each instance is checked and stopped independently. A listed ID that doesn't
> exist, or an instance missing the tag, is reported as a failure in the email
> notification, and the remaining instances are still stopped.

## Prerequisites

- AWS CLI with credentials configured
- AWS SAM CLI
- [uv](https://docs.astral.sh/uv/)
- Python 3.13
- Docker (for `sam local invoke` and `sam build --use-container`)

**Using Rancher Desktop?** Point SAM at its Docker socket for local invoke:

```bash
export DOCKER_HOST=unix://$HOME/.rd/docker.sock
```

You will also need to switch from containerd to dockerd in Rancher Desktop
settings.

## Development Setup

```bash
make install-dev
```

## Deploying

### 1. Tag Your EC2 Instances

Add the `AutoShutdown` tag to every instance you want shut down:

```bash
aws ec2 create-tags \
  --resources i-0123456789abcdef0 \
  --tags Key=AutoShutdown,Value=true
```

### 2. Configure

```bash
cp samconfig.example.toml samconfig.toml
```

Edit `parameter_overrides` in `samconfig.toml` and set your `InstanceIds`
(comma-separated if multiple) and `NotificationEmail`.

Alternatively, skip this step and run `make deploy-guided`, which prompts for
the values and writes `samconfig.toml` for you.

### 3. Build and Deploy

```bash
make deploy
```

### 4. Confirm SNS Subscription

Check your email and confirm the SNS subscription to receive notifications.

### Updating the Instance List or Schedule

Edit `parameter_overrides` in `samconfig.toml` and run `make deploy` again. For
example, to run at 11 PM:

```
ScheduleExpression=\"cron(0 23 * * ? *)\"
```

Remember to tag any newly added instances.

### Cleanup

```bash
make delete
```

## Testing

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
cp tests/local-env.json.example tests/local-env.json
# Edit INSTANCE_IDS with your instance ID(s)

make local-invoke
```

> **Warning:** `sam local invoke` runs with **your local AWS credentials**, not
> the deployed function's IAM role, so the tag restriction does not apply. If
> your credentials can stop instances, the listed instances **will be stopped**.
> Use a test instance or credentials without `ec2:StopInstances`. Notifications
> are skipped locally when `SNS_TOPIC_ARN` is empty.

## Commands

| Command                   | Description                                      |
| ------------------------- | ------------------------------------------------ |
| `make help`               | Show all available commands                      |
| `make install`            | Install production dependencies only             |
| `make install-dev`        | Install all dependencies + pre-commit hooks      |
| `make test`               | Run pytest                                       |
| `make test-cov`           | Run tests with coverage report                   |
| `make type-check`         | Run mypy type checker                            |
| `make pre-commit`         | Run pre-commit on all files                      |
| `make validate`           | Validate SAM template                            |
| `make build`              | Build SAM application                            |
| `make build-container`    | Build SAM using container                        |
| `make deploy`             | Build and deploy using `samconfig.toml`          |
| `make deploy-guided`      | Build and deploy with prompts (writes samconfig) |
| `make delete`             | Delete the CloudFormation stack                  |
| `make local-invoke`       | Invoke function locally with test event          |
| `make local-invoke-debug` | Invoke locally with debug output                 |
| `make logs`               | Tail Lambda logs                                 |
| `make clean`              | Remove build artifacts                           |
| `make lock`               | Update uv.lock file                              |
| `make update-hooks`       | Update pre-commit hooks                          |
| `make ci-check`           | Run all CI checks                                |

## Configuration

### Parameters

| Parameter            | Description                              | Default                        |
| -------------------- | ---------------------------------------- | ------------------------------ |
| `InstanceIds`        | Comma-separated list of EC2 instance IDs | (required)                     |
| `NotificationEmail`  | Email for shutdown notifications         | (required)                     |
| `ScheduleExpression` | Cron expression for schedule             | `cron(0 0 * * ? *)` (midnight) |
| `ScheduleTimezone`   | IANA timezone for the schedule           | `America/New_York`             |
| `Environment`        | Environment tag (dev/staging/prod)       | `prod`                         |

`America/New_York` follows daylight saving time, so the default schedule runs at
local midnight year-round (EST in winter, EDT in summer).

## How It Works

1. **EventBridge Scheduler** triggers the Lambda function on the configured
   schedule
2. **Lambda** reads instance IDs from the `INSTANCE_IDS` environment variable
3. For each instance:
    - Checks current state via `ec2:DescribeInstances`
    - If running or pending, adds it to the stop request
    - If already stopped or stopping, logs and skips
    - If terminated or missing, reports it as failed
4. Running instances are stopped with a single `ec2:StopInstances` call
5. **SNS notification** is sent with a results summary
6. **CloudWatch alarm** fires if the Lambda itself errors

Stop failures (such as an untagged instance) are reported in the notification
but do not cause the Lambda to error, so they will not trigger the CloudWatch
alarm.

## IAM Permissions

The Lambda function has these permissions:

- `ec2:DescribeInstances`, `ec2:DescribeInstanceStatus` - check instance states
  (all instances; these actions do not support resource-level scoping)
- `ec2:StopInstances` - stop instances, only those tagged `AutoShutdown: true`
- `sns:Publish` - send notifications to the shutdown topic
