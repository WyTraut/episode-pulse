import json

import pytest

import publisher


class FakeBatch:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.events = []

    def add(self, event) -> None:
        if len(self.events) >= self.capacity:
            raise ValueError("Batch is full.")

        self.events.append(event)


class FakeProducer:
    def __init__(self, capacity: int = 2) -> None:
        self.capacity = capacity
        self.created_with = None
        self.sent_batches = []
        self.closed = False

    def factory(self, **kwargs):
        self.created_with = kwargs
        return self

    def create_batch(self) -> FakeBatch:
        return FakeBatch(self.capacity)

    def send_batch(self, batch: FakeBatch) -> None:
        self.sent_batches.append(batch)

    def close(self) -> None:
        self.closed = True


def test_publishes_each_observation_in_size_safe_batches(monkeypatch) -> None:
    fake_producer = FakeProducer(capacity=2)
    monkeypatch.setattr(
        publisher,
        "EventHubProducerClient",
        fake_producer.factory,
    )

    observations = [
        {"event_id": "one", "title": "First Show"},
        {"event_id": "two", "title": "Second Show"},
        {"event_id": "three", "title": "Third Show"},
    ]

    published_count = publisher.publish_observations(
        observations=observations,
        fully_qualified_namespace="example.servicebus.windows.net",
        event_hub_name="observations",
        credential="test-credential",
    )

    assert published_count == 3
    assert [len(batch.events) for batch in fake_producer.sent_batches] == [2, 1]
    assert fake_producer.created_with == {
        "fully_qualified_namespace": "example.servicebus.windows.net",
        "eventhub_name": "observations",
        "credential": "test-credential",
    }
    assert json.loads(
        fake_producer.sent_batches[0].events[0].body_as_str()
    ) == observations[0]
    assert fake_producer.sent_batches[0].events[0].content_type == (
        "application/json"
    )
    assert fake_producer.closed is True


def test_skips_client_creation_when_there_are_no_observations(
    monkeypatch,
) -> None:
    def fail_if_called(**kwargs):
        raise AssertionError("Producer should not be created.")

    monkeypatch.setattr(publisher, "EventHubProducerClient", fail_if_called)

    assert publisher.publish_observations(
        observations=[],
        fully_qualified_namespace="example.servicebus.windows.net",
        event_hub_name="observations",
        credential="test-credential",
    ) == 0


def test_rejects_an_observation_larger_than_an_empty_batch(
    monkeypatch,
) -> None:
    fake_producer = FakeProducer(capacity=0)
    monkeypatch.setattr(
        publisher,
        "EventHubProducerClient",
        fake_producer.factory,
    )

    with pytest.raises(ValueError, match="single observation exceeds"):
        publisher.publish_observations(
            observations=[{"event_id": "too-large"}],
            fully_qualified_namespace="example.servicebus.windows.net",
            event_hub_name="observations",
            credential="test-credential",
        )

    assert fake_producer.sent_batches == []
    assert fake_producer.closed is True
