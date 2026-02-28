"""
FastAPI + Kafka Event Producer
Publishes events to Kafka topics
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kafka import KafkaProducer
from typing import Optional, Dict, Any
import json
import os
from datetime import datetime

app = FastAPI(title="Event Producer API")

# Initialize Kafka producer
# TODO: add SSL/SASL authentication
producer = KafkaProducer(
    bootstrap_servers=['kafka.internal:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    key_serializer=lambda k: k.encode('utf-8') if k else None,
    acks='all',
    retries=3
)

class Event(BaseModel):
    event_type: str
    data: Dict[str, Any]
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}

class EventResponse(BaseModel):
    status: str
    topic: str
    partition: int
    offset: int
    timestamp: str

@app.on_event("shutdown")
async def shutdown_event():
    """Flush and close Kafka producer on shutdown"""
    producer.flush()
    producer.close()

@app.get("/")
async def root():
    return {
        "message": "Event Producer API",
        "version": "1.0",
        "kafka_brokers": "kafka.internal:9092"
    }

@app.post("/events", response_model=EventResponse)
async def publish_event(event: Event, topic: str = "events"):
    """
    Publish an event to a Kafka topic
    """
    # TODO: validate event schema
    # TODO: add rate limiting per user

    # Enrich event with metadata
    event_data = {
        "event_type": event.event_type,
        "data": event.data,
        "user_id": event.user_id,
        "metadata": event.metadata or {},
        "timestamp": datetime.utcnow().isoformat(),
        "source": "api"
    }

    try:
        # Send to Kafka
        # Use user_id as key for partitioning
        future = producer.send(
            topic,
            key=event.user_id,
            value=event_data
        )

        # Wait for confirmation
        record_metadata = future.get(timeout=10)

        return EventResponse(
            status="published",
            topic=record_metadata.topic,
            partition=record_metadata.partition,
            offset=record_metadata.offset,
            timestamp=datetime.utcnow().isoformat()
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish event: {str(e)}")

@app.post("/events/batch")
async def publish_batch(events: list[Event], topic: str = "events"):
    """
    Publish multiple events in batch
    """
    results = []
    errors = []

    for idx, event in enumerate(events):
        event_data = {
            "event_type": event.event_type,
            "data": event.data,
            "user_id": event.user_id,
            "metadata": event.metadata or {},
            "timestamp": datetime.utcnow().isoformat(),
            "source": "api"
        }

        try:
            future = producer.send(
                topic,
                key=event.user_id,
                value=event_data
            )
            results.append({"index": idx, "status": "queued"})
        except Exception as e:
            errors.append({"index": idx, "error": str(e)})

    # Flush to ensure all messages are sent
    producer.flush()

    return {
        "published": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors
    }

@app.post("/events/{event_type}")
async def publish_typed_event(
    event_type: str,
    data: Dict[str, Any],
    user_id: Optional[str] = None
):
    """
    Simplified endpoint for publishing events by type
    """
    event = Event(
        event_type=event_type,
        data=data,
        user_id=user_id
    )

    # Route to different topics based on event type
    # TODO: make this configurable
    topic_mapping = {
        "user_action": "user-events",
        "system": "system-events",
        "analytics": "analytics-events"
    }

    topic = topic_mapping.get(event_type, "events")

    return await publish_event(event, topic)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # TODO: actually check Kafka broker connectivity
    return {
        "status": "ok",
        "kafka": "connected",
        "producer": "ready"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
