from schemas import DocumentMetadata, sanitize_metadata


def test_document_metadata_sanitize_returns_defaults_for_invalid_input():
    result = DocumentMetadata.sanitize(None)
    assert result["author"] == "Unknown"
    assert result["tags"] == []
    assert result["custom_fields"] == {}
    assert result["page_count"] == 0
    assert result["keywords"] == []
    assert result["detected_language"] == "und"
    assert result["version"] == 1


def test_document_metadata_sanitize_coerces_valid_partial_payload():
    result = DocumentMetadata.sanitize(
        {
            "author": "Vega",
            "tags": ["finanzas", 2026],
            "custom_fields": {"department": "legal", "priority": 1},
            "page_count": "12",
            "keywords": ["sat", "balance"],
            "detected_language": "es",
            "version": "3",
        }
    )

    assert result["author"] == "Vega"
    assert result["tags"] == ["finanzas", "2026"]
    assert result["custom_fields"] == {"department": "legal", "priority": "1"}
    assert result["page_count"] == 12
    assert result["keywords"] == ["sat", "balance"]
    assert result["detected_language"] == "es"
    assert result["version"] == 3


def test_sanitize_metadata_returns_safe_defaults():
    result = sanitize_metadata(None)
    assert result == {
        "author": "Desconocido",
        "page_count": 0,
        "keywords": [],
        "detected_language": "und",
        "version": 1,
    }


def test_sanitize_metadata_normalizes_known_fields():
    result = sanitize_metadata(
        {
            "author": 123,
            "page_count": "7",
            "keywords": "ocr",
            "detected_language": "es",
            "version": "2",
            "custom_note": "ok",
            "ignore_me": None,
        }
    )

    assert result["author"] == "123"
    assert result["page_count"] == 7
    assert result["keywords"] == ["ocr"]
    assert result["detected_language"] == "es"
    assert result["version"] == 2
    assert result["custom_note"] == "ok"
    assert "ignore_me" not in result
