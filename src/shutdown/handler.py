"""Lambda handler for scheduled EC2 instance shutdown."""

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_instance_ids() -> list[str]:
    """Parse instance IDs from environment variable.

    Expected format: comma-separated list of instance IDs.
    Example: "i-1234567890abcdef0,i-0987654321fedcba0"

    Returns:
        List of instance IDs to shut down.

    Raises:
        ValueError: If INSTANCE_IDS environment variable is not set or empty.
    """
    raw_ids = os.environ.get("INSTANCE_IDS", "").strip()
    if not raw_ids:
        raise ValueError("INSTANCE_IDS environment variable is not set or empty")

    return [
        instance_id.strip() for instance_id in raw_ids.split(",") if instance_id.strip()
    ]


def shutdown_instances(instance_ids: list[str]) -> dict[str, Any]:
    """Attempt to stop the specified EC2 instances.

    Args:
        instance_ids: List of EC2 instance IDs to stop.

    Returns:
        Dictionary containing:
            - stopped: List of instance IDs that were successfully stopped
            - already_stopped: List of instance IDs that were already stopped
            - failed: List of dicts with instance_id and error for failures
    """
    ec2 = boto3.client("ec2")
    results: dict[str, Any] = {"stopped": [], "already_stopped": [], "failed": []}

    # First, get current state of all instances
    try:
        response = ec2.describe_instances(InstanceIds=instance_ids)
    except ClientError as e:
        logger.error("Failed to describe instances: %s", e)
        for instance_id in instance_ids:
            results["failed"].append({"instance_id": instance_id, "error": str(e)})
        return results

    # Build a map of instance states
    instance_states: dict[str, str] = {}
    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            inst_id = instance["InstanceId"]
            inst_state = instance["State"]["Name"]
            instance_states[inst_id] = inst_state
            logger.info("Instance %s is currently in state: %s", inst_id, inst_state)

    # Categorize instances by current state
    to_stop: list[str] = []
    for instance_id in instance_ids:
        state: str | None = instance_states.get(instance_id)
        if state is None:
            results["failed"].append(
                {"instance_id": instance_id, "error": "Instance not found in response"}
            )
        elif state in ("stopped", "stopping"):
            results["already_stopped"].append(instance_id)
            logger.info(
                "Instance %s is already stopped/stopping, skipping", instance_id
            )
        elif state in ("running", "pending"):
            to_stop.append(instance_id)
        else:
            # terminated, shutting-down, etc.
            results["failed"].append(
                {
                    "instance_id": instance_id,
                    "error": f"Instance in unexpected state: {state}",
                }
            )

    # Stop instances that need stopping
    if to_stop:
        try:
            stop_response = ec2.stop_instances(InstanceIds=to_stop)
            for stopping_instance in stop_response.get("StoppingInstances", []):
                stopped_id = stopping_instance["InstanceId"]
                previous_state = stopping_instance["PreviousState"]["Name"]
                current_state = stopping_instance["CurrentState"]["Name"]
                logger.info(
                    "Instance %s: %s -> %s",
                    stopped_id,
                    previous_state,
                    current_state,
                )
                results["stopped"].append(stopped_id)
        except ClientError as e:
            logger.error("Failed to stop instances %s: %s", to_stop, e)
            for instance_id in to_stop:
                results["failed"].append({"instance_id": instance_id, "error": str(e)})

    return results


def send_notification(results: dict[str, Any]) -> None:
    """Send SNS notification with shutdown results.

    Args:
        results: Dictionary containing stopped, already_stopped, and failed lists.
    """
    topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if not topic_arn:
        logger.warning("SNS_TOPIC_ARN not set, skipping notification")
        return

    sns = boto3.client("sns")

    # Build message
    lines = ["EC2 Auto-Shutdown Report", "=" * 30, ""]

    if results["stopped"]:
        lines.append(f"✅ Successfully stopped ({len(results['stopped'])}):")
        for instance_id in results["stopped"]:
            lines.append(f"   • {instance_id}")
        lines.append("")

    if results["already_stopped"]:
        lines.append(f"ℹ️  Already stopped ({len(results['already_stopped'])}):")
        for instance_id in results["already_stopped"]:
            lines.append(f"   • {instance_id}")
        lines.append("")

    if results["failed"]:
        lines.append(f"❌ Failed ({len(results['failed'])}):")
        for failure in results["failed"]:
            lines.append(f"   • {failure['instance_id']}: {failure['error']}")
        lines.append("")

    message = "\n".join(lines)

    # Determine subject based on results
    if results["failed"]:
        subject = "⚠️ EC2 Auto-Shutdown: Completed with errors"
    elif results["stopped"]:
        subject = "✅ EC2 Auto-Shutdown: Instances stopped"
    else:
        subject = "ℹ️ EC2 Auto-Shutdown: No action needed"

    try:
        sns.publish(TopicArn=topic_arn, Subject=subject, Message=message)
        logger.info("Notification sent to %s", topic_arn)
    except ClientError as e:
        logger.error("Failed to send SNS notification: %s", e)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for scheduled EC2 shutdown.

    Args:
        event: EventBridge scheduled event payload.
        context: Lambda context object.

    Returns:
        Dictionary with statusCode and results body.
    """
    logger.info("Received event: %s", json.dumps(event))

    try:
        instance_ids = get_instance_ids()
        logger.info("Target instances: %s", instance_ids)
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    results = shutdown_instances(instance_ids)
    logger.info("Shutdown results: %s", json.dumps(results))

    send_notification(results)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "EC2 shutdown check completed",
                "results": results,
            }
        ),
    }
