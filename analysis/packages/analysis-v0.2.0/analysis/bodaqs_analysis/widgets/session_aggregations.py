# -*- coding: utf-8 -*-
"""Compatibility wrapper for legacy widget aggregation imports.

Default aggregation behavior now targets the canonical library-backed store.
This module keeps legacy imports stable while exposing the retired local backend
only as an explicit compatibility path.
"""

from bodaqs_analysis.library.aggregations import (
    CANONICAL_DEFAULT_FILENAME as DEFAULT_FILENAME,
    DEFAULT_DIRNAME,
    CANONICAL_STORE_SCHEMA as STORE_SCHEMA,
    STORE_VERSION,
    AggregationStoreError as SessionAggregationError,
    AggregationStoreValidationError as SessionAggregationValidationError,
    CanonicalAggregationStore,
    LocalAggregationStore,
    bootstrap_canonical_from_local,
    definition_from_mapping,
    definition_to_mapping,
    is_valid_session_key,
    make_aggregation_key,
    now_utc_iso,
    make_default_aggregation_store,
    user_store_path as local_user_store_path,
    validate_aggregation_definition,
    validate_store as _validate_store,
)


class SessionAggregationStore(CanonicalAggregationStore):
    def __init__(self, path=None, *, artifact_store=None):
        super().__init__(artifact_store=artifact_store, path=path)


def validate_store(obj):
    return _validate_store(obj, schema=STORE_SCHEMA)


user_store_path = local_user_store_path

__all__ = [
    "DEFAULT_DIRNAME",
    "DEFAULT_FILENAME",
    "STORE_SCHEMA",
    "STORE_VERSION",
    "LocalAggregationStore",
    "SessionAggregationError",
    "SessionAggregationStore",
    "SessionAggregationValidationError",
    "bootstrap_canonical_from_local",
    "definition_from_mapping",
    "definition_to_mapping",
    "is_valid_session_key",
    "make_aggregation_key",
    "make_default_aggregation_store",
    "now_utc_iso",
    "user_store_path",
    "local_user_store_path",
    "validate_aggregation_definition",
    "validate_store",
]
