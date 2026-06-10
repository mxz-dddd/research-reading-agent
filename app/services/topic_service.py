from __future__ import annotations

from app.repositories.topic_repo import TopicRepository
from app.schemas.topic import TopicCreate, TopicRead


class TopicService:
    def __init__(
        self,
        topic_repo: TopicRepository | None = None,
    ) -> None:
        self.topic_repo = topic_repo if topic_repo is not None else TopicRepository()

    def create_topic(self, payload: TopicCreate) -> TopicRead:
        return self.topic_repo.create(payload)

    def list_topics(self) -> list[TopicRead]:
        return self.topic_repo.list_all()
