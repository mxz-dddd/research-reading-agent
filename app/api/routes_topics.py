from __future__ import annotations

from fastapi import APIRouter

from app.schemas.topic import TopicCreate, TopicRead
from app.services.topic_service import TopicService

router = APIRouter(prefix="/topics", tags=["topics"])
topic_service = TopicService()


@router.post("", response_model=TopicRead)
def create_topic(payload: TopicCreate) -> TopicRead:
    return topic_service.create_topic(payload)


@router.get("", response_model=list[TopicRead])
def list_topics() -> list[TopicRead]:
    return topic_service.list_topics()
