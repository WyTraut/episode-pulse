import json
from typing import Any

from azure.eventhub import EventData, EventHubProducerClient


def publish_observations(
    observations: list[dict[str, Any]],
    fully_qualified_namespace: str,
    event_hub_name: str,
    credential: Any,
) -> int:
    """Publish normalized observations as individual Event Hubs events."""

    if not observations:
        return 0

    producer = EventHubProducerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=event_hub_name,
        credential=credential,
    )

    published_count = 0

    try:
        batch = producer.create_batch()
        batch_count = 0

        for observation in observations:
            event = EventData(
                json.dumps(
                    observation,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            event.content_type = "application/json"

            try:
                batch.add(event)
                batch_count += 1
            except ValueError:
                if batch_count == 0:
                    raise ValueError(
                        "A single observation exceeds the Event Hubs message limit."
                    ) from None

                producer.send_batch(batch)
                published_count += batch_count

                batch = producer.create_batch()
                batch_count = 0

                try:
                    batch.add(event)
                    batch_count = 1
                except ValueError:
                    raise ValueError(
                        "A single observation exceeds the Event Hubs message limit."
                    ) from None

        if batch_count:
            producer.send_batch(batch)
            published_count += batch_count
    finally:
        producer.close()

    return published_count
