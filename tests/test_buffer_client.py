import json

from src.buffer_client import (
    build_post_text,
    build_service_text_map,
    canonical_buffer_service,
)


def write_metadata(package_dir, payload):
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "metadata.json").write_text(json.dumps(payload))


def test_build_post_text_prefers_service_specific_caption(tmp_path):
    package_dir = tmp_path / "package"
    write_metadata(
        package_dir,
        {
            "title_options": ["Bitcoin ETF flow spike"],
            "description": "Generic package description.",
            "hashtags": ["#Bitcoin", "#ETF"],
            "platform_captions": {
                "twitter": "BTC ETFs just pulled in fresh flows.",
                "linkedin": "Institutions are treating BTC ETFs like a treasury product.",
            },
        },
    )

    text = build_post_text(package_dir, "twitter")

    assert "Bitcoin ETF flow spike" in text
    assert "BTC ETFs just pulled in fresh flows." in text
    assert "Generic package description." not in text
    assert "#Bitcoin #ETF" in text


def test_build_post_text_uses_service_aliases(tmp_path):
    package_dir = tmp_path / "package"
    write_metadata(
        package_dir,
        {
            "title_options": ["Stablecoin bill moves"],
            "description": "Fallback description.",
            "hashtags": ["#Stablecoins"],
            "platform_captions": {
                "twitter": "Stablecoin policy just moved another step forward.",
            },
        },
    )

    text = build_post_text(package_dir, "x")

    assert "Stablecoin policy just moved another step forward." in text
    assert "Fallback description." not in text


def test_build_service_text_map_canonicalizes_services(tmp_path):
    package_dir = tmp_path / "package"
    write_metadata(
        package_dir,
        {
            "title_options": ["Exchange reserve shift"],
            "description": "Fallback description.",
            "hashtags": ["#Crypto"],
            "platform_captions": {
                "x": "Exchange reserves are dropping again.",
                "linkedin": "Treasury teams are watching exchange reserve changes closely.",
            },
        },
    )

    text_map = build_service_text_map(package_dir)

    assert text_map["twitter"].startswith("Exchange reserve shift")
    assert "Exchange reserves are dropping again." in text_map["twitter"]
    assert text_map["linkedin"].startswith("Exchange reserve shift")
    assert canonical_buffer_service("google_business_profile") == "google"
