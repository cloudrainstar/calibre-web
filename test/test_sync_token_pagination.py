import importlib.util
import json
import sys
import types
from datetime import datetime
from pathlib import Path


def load_sync_token_module():
    flask_stub = types.ModuleType("flask")
    flask_stub.json = json
    sys.modules["flask"] = flask_stub

    jsonschema_stub = types.ModuleType("jsonschema")
    jsonschema_stub.validate = lambda instance, schema: None
    jsonschema_stub.exceptions = types.SimpleNamespace(ValidationError=ValueError)
    sys.modules["jsonschema"] = jsonschema_stub

    cps_stub = types.ModuleType("cps")
    cps_stub.__path__ = []
    logger_stub = types.ModuleType("cps.logger")
    logger_stub.create = lambda: types.SimpleNamespace(error=lambda *args, **kwargs: None)
    services_stub = types.ModuleType("cps.services")
    services_stub.__path__ = []
    sys.modules["cps"] = cps_stub
    sys.modules["cps.logger"] = logger_stub
    sys.modules["cps.services"] = services_stub

    module_path = Path(__file__).resolve().parents[1] / "cps" / "services" / "SyncToken.py"
    spec = importlib.util.spec_from_file_location("cps.services.SyncToken", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cps.services.SyncToken"] = module
    spec.loader.exec_module(module)
    return module


sync_token_module = load_sync_token_module()
SyncToken = sync_token_module.SyncToken


def test_sync_token_round_trips_pagination_state():
    assert hasattr(sync_token_module, "SyncTokenPagination")
    SyncTokenPagination = sync_token_module.SyncTokenPagination
    pagination = SyncTokenPagination(
        snapshot_ts=datetime(2026, 1, 2, 3, 4, 5),
        books_last_id=42,
        books_max_last_modified=datetime(2026, 1, 2, 3, 0, 0),
        books_max_last_created=datetime(2026, 1, 2, 2, 0, 0),
        reading_state_last_id=7,
        reading_state_max_last_modified=datetime(2026, 1, 2, 1, 0, 0),
        archive_max_last_modified=datetime(2026, 1, 2, 0, 30, 0),
    )
    token = SyncToken(
        raw_kobo_store_token="store-token",
        books_last_created=datetime(2026, 1, 1, 10, 0, 0),
        books_last_modified=datetime(2026, 1, 1, 11, 0, 0),
        archive_last_modified=datetime(2026, 1, 1, 12, 0, 0),
        reading_state_last_modified=datetime(2026, 1, 1, 13, 0, 0),
        tags_last_modified=datetime(2026, 1, 1, 14, 0, 0),
        pagination=pagination,
    )

    headers = {}
    token.to_headers(headers)

    parsed = SyncToken.from_headers(headers)

    assert parsed.raw_kobo_store_token == "store-token"
    assert parsed.pagination is not None
    assert parsed.pagination.snapshot_ts == datetime(2026, 1, 2, 3, 4, 5)
    assert parsed.pagination.books_last_id == 42
    assert parsed.pagination.books_max_last_modified == datetime(2026, 1, 2, 3, 0, 0)
    assert parsed.pagination.books_max_last_created == datetime(2026, 1, 2, 2, 0, 0)
    assert parsed.pagination.reading_state_last_id == 7
    assert parsed.pagination.reading_state_max_last_modified == datetime(2026, 1, 2, 1, 0, 0)
    assert parsed.pagination.archive_max_last_modified == datetime(2026, 1, 2, 0, 30, 0)


def test_sync_token_parses_legacy_token_without_pagination():
    legacy_token = sync_token_module.b64encode_json({
        "version": "1-1-0",
        "data": {
            "raw_kobo_store_token": "legacy-store-token",
            "books_last_created": sync_token_module.to_epoch_timestamp(datetime(2026, 1, 1, 10, 0, 0)),
            "books_last_modified": sync_token_module.to_epoch_timestamp(datetime(2026, 1, 1, 11, 0, 0)),
            "archive_last_modified": sync_token_module.to_epoch_timestamp(datetime(2026, 1, 1, 12, 0, 0)),
            "reading_state_last_modified": sync_token_module.to_epoch_timestamp(datetime(2026, 1, 1, 13, 0, 0)),
            "tags_last_modified": sync_token_module.to_epoch_timestamp(datetime(2026, 1, 1, 14, 0, 0)),
        },
    })
    headers = {SyncToken.SYNC_TOKEN_HEADER: legacy_token}

    parsed = SyncToken.from_headers(headers)

    assert parsed.raw_kobo_store_token == "legacy-store-token"
    assert parsed.books_last_created == datetime(2026, 1, 1, 10, 0, 0)
    assert parsed.books_last_modified == datetime(2026, 1, 1, 11, 0, 0)
    assert parsed.archive_last_modified == datetime(2026, 1, 1, 12, 0, 0)
    assert parsed.reading_state_last_modified == datetime(2026, 1, 1, 13, 0, 0)
    assert parsed.tags_last_modified == datetime(2026, 1, 1, 14, 0, 0)
    assert parsed.pagination is None
