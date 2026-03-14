from pydantic import BaseModel, Field, ValidationError
from typing import Dict, List, Any, Optional


class DocumentMetadata(BaseModel):
    author: str = "Unknown"
    tags: List[str] = Field(default_factory=list)
    custom_fields: Dict[str, str] = Field(default_factory=dict)
    page_count: int = 0
    keywords: List[str] = Field(default_factory=list)
    detected_language: str = "und"
    version: int = 1

    @classmethod
    def sanitize(cls, data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return cls().model_dump()

        try:
            return cls(**data).model_dump()
        except ValidationError:
            clean: Dict[str, Any] = {}

            author = data.get("author")
            if isinstance(author, str):
                clean["author"] = author

            tags = data.get("tags")
            if isinstance(tags, list):
                clean["tags"] = [str(t) for t in tags if t is not None]

            custom_fields = data.get("custom_fields")
            if isinstance(custom_fields, dict):
                clean["custom_fields"] = {
                    str(k): str(v) for k, v in custom_fields.items() if v is not None
                }

            page_count = data.get("page_count")
            try:
                clean["page_count"] = int(page_count)
            except (TypeError, ValueError):
                pass

            keywords = data.get("keywords")
            if isinstance(keywords, list):
                clean["keywords"] = [str(k) for k in keywords if k is not None]

            detected_language = data.get("detected_language")
            if isinstance(detected_language, str):
                clean["detected_language"] = detected_language

            version = data.get("version")
            try:
                clean["version"] = int(version)
            except (TypeError, ValueError):
                pass

            return cls(**clean).model_dump()


def sanitize_metadata(raw_metadata: dict | None) -> dict:
    defaults = {
        "author": "Desconocido",
        "page_count": 0,
        "keywords": [],
        "detected_language": "und",
        "version": 1
    }

    if not isinstance(raw_metadata, dict):
        return defaults

    clean = {}

    for k, v in raw_metadata.items():
        if v is None:
            continue

        if k == "author":
            clean[k] = str(v)

        elif k == "page_count":
            try:
                clean[k] = int(v)
            except (ValueError, TypeError):
                clean[k] = 0

        elif k == "keywords":
            if isinstance(v, list):
                clean[k] = [str(x) for x in v]
            else:
                clean[k] = [str(v)]

        elif k == "detected_language":
            clean[k] = str(v)

        elif k == "version":
            try:
                clean[k] = int(v)
            except (ValueError, TypeError):
                clean[k] = 1

        else:
            clean[k] = v

    return {**defaults, **clean}
