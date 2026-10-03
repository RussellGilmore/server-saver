"""Tests for EC2 shutdown handler."""

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from shutdown.handler import (
    get_instance_ids,
    lambda_handler,
    send_notification,
    shutdown_instances,
)


class TestGetInstanceIds:
    """Tests for get_instance_ids function."""

    def test_single_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test parsing a single instance ID."""
        monkeypatch.setenv("INSTANCE_IDS", "i-1234567890abcdef0")
        result = get_instance_ids()
        assert result == ["i-1234567890abcdef0"]

    def test_multiple_instances(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test parsing multiple instance IDs."""
        monkeypatch.setenv("INSTANCE_IDS", "i-1234567890abcdef0,i-0987654321fedcba0")
        result = get_instance_ids()
        assert result == ["i-1234567890abcdef0", "i-0987654321fedcba0"]

    def test_whitespace_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that whitespace is properly trimmed."""
        monkeypatch.setenv("INSTANCE_IDS", " i-123 , i-456 , i-789 ")
        result = get_instance_ids()
        assert result == ["i-123", "i-456", "i-789"]

    def test_empty_entries_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that empty entries from double commas are filtered."""
        monkeypatch.setenv("INSTANCE_IDS", "i-123,,i-456")
        result = get_instance_ids()
        assert result == ["i-123", "i-456"]

    def test_missing_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing env var raises ValueError."""
        monkeypatch.delenv("INSTANCE_IDS", raising=False)
        with pytest.raises(ValueError, match="not set or empty"):
            get_instance_ids()

    def test_empty_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that empty env var raises ValueError."""
        monkeypatch.setenv("INSTANCE_IDS", "")
        with pytest.raises(ValueError, match="not set or empty"):
            get_instance_ids()

    def test_whitespace_only_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that whitespace-only env var raises ValueError."""
        monkeypatch.setenv("INSTANCE_IDS", "   ")
        with pytest.raises(ValueError, match="not set or empty"):
            get_instance_ids()


@pytest.fixture
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def ec2_client(aws_credentials: None) -> Generator[Any, None, None]:
    """Create a mocked EC2 client."""
    with mock_aws():
        yield boto3.client("ec2", region_name="us-east-1")


@pytest.fixture
def sns_client(aws_credentials: None) -> Generator[Any, None, None]:
    """Create a mocked SNS client."""
    with mock_aws():
        yield boto3.client("sns", region_name="us-east-1")


def create_instance(ec2_client: Any, state: str = "running") -> str:
    """Create a test EC2 instance and return its ID."""
    response = ec2_client.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t2.micro",
    )
    instance_id = response["Instances"][0]["InstanceId"]

    if state == "stopped":
        ec2_client.stop_instances(InstanceIds=[instance_id])
        waiter = ec2_client.get_waiter("instance_stopped")
        waiter.wait(InstanceIds=[instance_id])

    return instance_id


class TestShutdownInstances:
    """Tests for shutdown_instances function."""

    def test_stop_running_instance(self, aws_credentials: None) -> None:
        """Test stopping a running instance."""
        with mock_aws():
            ec2 = boto3.client("ec2", region_name="us-east-1")
            instance_id = create_instance(ec2, state="running")

            results = shutdown_instances([instance_id])

            assert instance_id in results["stopped"]
            assert not results["already_stopped"]
            assert not results["failed"]

    def test_stop_multiple_running_instances(self, aws_credentials: None) -> None:
        """Test stopping multiple running instances."""
        with mock_aws():
            ec2 = boto3.client("ec2", region_name="us-east-1")
            instance_ids = [create_instance(ec2) for _ in range(3)]

            results = shutdown_instances(instance_ids)

            assert set(results["stopped"]) == set(instance_ids)
            assert not results["already_stopped"]
            assert not results["failed"]

    def test_already_stopped_instance(self, aws_credentials: None) -> None:
        """Test handling an already stopped instance."""
        with mock_aws():
            ec2 = boto3.client("ec2", region_name="us-east-1")
            instance_id = create_instance(ec2, state="stopped")

            results = shutdown_instances([instance_id])

            assert not results["stopped"]
            assert instance_id in results["already_stopped"]
            assert not results["failed"]

    def test_mixed_states(self, aws_credentials: None) -> None:
        """Test handling a mix of running and stopped instances."""
        with mock_aws():
            ec2 = boto3.client("ec2", region_name="us-east-1")
            running_id = create_instance(ec2, state="running")
            stopped_id = create_instance(ec2, state="stopped")

            results = shutdown_instances([running_id, stopped_id])

            assert running_id in results["stopped"]
            assert stopped_id in results["already_stopped"]
            assert not results["failed"]

    def test_nonexistent_instance(self, aws_credentials: None) -> None:
        """Test handling a nonexistent instance ID."""
        with mock_aws():
            results = shutdown_instances(["i-nonexistent123456"])

            assert not results["stopped"]
            assert not results["already_stopped"]
            assert len(results["failed"]) == 1
            assert results["failed"][0]["instance_id"] == "i-nonexistent123456"


class TestSendNotification:
    """Tests for send_notification function."""

    def test_sends_notification_on_success(
        self, aws_credentials: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that notification is sent with correct content."""
        with mock_aws():
            sns = boto3.client("sns", region_name="us-east-1")
            response = sns.create_topic(Name="test-topic")
            topic_arn = response["TopicArn"]
            monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)

            results: dict[str, Any] = {
                "stopped": ["i-123", "i-456"],
                "already_stopped": [],
                "failed": [],
            }

            # Should not raise
            send_notification(results)

    def test_skips_when_no_topic_arn(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that notification is skipped when SNS_TOPIC_ARN is not set."""
        monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)

        results: dict[str, Any] = {
            "stopped": ["i-123"],
            "already_stopped": [],
            "failed": [],
        }

        send_notification(results)
        assert "skipping notification" in caplog.text.lower()


class TestLambdaHandler:
    """Integration tests for the full lambda handler."""

    def test_handler_success(
        self, aws_credentials: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test successful handler execution."""
        with mock_aws():
            ec2 = boto3.client("ec2", region_name="us-east-1")
            sns = boto3.client("sns", region_name="us-east-1")

            instance_id = create_instance(ec2)
            monkeypatch.setenv("INSTANCE_IDS", instance_id)

            response = sns.create_topic(Name="test-topic")
            monkeypatch.setenv("SNS_TOPIC_ARN", response["TopicArn"])

            event: dict[str, Any] = {"source": "aws.events"}
            context = MagicMock()

            result = lambda_handler(event, context)

            assert result["statusCode"] == 200
            body = json.loads(result["body"])
            assert instance_id in body["results"]["stopped"]

    def test_handler_missing_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test handler with missing configuration."""
        monkeypatch.delenv("INSTANCE_IDS", raising=False)

        event: dict[str, Any] = {"source": "aws.events"}
        context = MagicMock()

        result = lambda_handler(event, context)

        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert "error" in body
