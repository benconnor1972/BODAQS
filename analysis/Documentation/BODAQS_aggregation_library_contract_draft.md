# BODAQS Aggregation Library Contract (Draft)

**Status:** Draft  
**Scope:** Canonical session aggregation management as part of the analysis library layer  
**Goal:** reuse the current aggregation domain model and expansion logic while moving canonical aggregation persistence and management out of the widget layer

---

## 1. Summary

The current aggregation implementation is a good **prototype domain model**, but not the right final home for canonical library management.

What should be retained:

- aggregation definition shape
- validation rules
- session-key membership model
- registry/event-schema policy fields
- expansion semantics used by selector/widget consumers

What should change:

- canonical persistence should not live in a per-user `~/.bodaqs/...` file
- aggregation services should not live primarily under `widgets/`
- the current aggregation editor should become a **consumer** of a library/service boundary, not the owner of aggregation persistence

---

## 2. Current-state assessment

### 2.1 Reusable parts

The following current behavior is worth keeping:

1. **AggregationDefinition shape**
   - stable `aggregation_key`
   - `title`
   - `member_session_keys`
   - `registry_policy`
   - `event_schema_policy`
   - timestamps
   - optional note

2. **Validation rules**
   - non-empty members
   - unique aggregation keys
   - valid `session_key` format
   - policy constraints to `union|intersection|strict`

3. **Selection expansion semantics**
   - explicit sessions take precedence over overlapping aggregation members
   - overlap reduction is explicit

### 2.2 Current limitations

The current implementation is not sufficient as the canonical library backend because:

1. it is **per-user local state**
2. it lives in the **widget layer**
3. it is managed through a selector-oriented UI rather than a library-management interface
4. it has no explicit store abstraction separating local vs canonical backends

---

## 3. Canonical vs local aggregation scope

### 3.1 Canonical aggregations

Canonical aggregations are part of the shared analysis library.

They should be:

- persisted in project/artifact-backed storage
- visible to all library-management views
- available to selectors and notebooks as standard entities

### 3.2 Local aggregations

Local aggregations were useful as personal shortcuts or temporary exploratory scopes.

They may still exist only as a legacy compatibility path:

- optional
- clearly separate from canonical aggregations
- not used as the default backend

### 3.3 Recommendation

For the library-management direction, aggregations that matter for analysis should be treated as **canonical**.

The local backend is now considered **retired by default** and should only remain as a compatibility/import path.

---

## 4. Canonical aggregation storage

Because aggregations may span sessions from multiple runs, they should not live under a single run/session subtree.

Recommended canonical location:

```text
artifacts/library/aggregations_v1.json
```

Alternative acceptable location:

```text
artifacts/aggregations_v1.json
```

Recommendation:

- prefer `artifacts/library/...` if more catalog/library objects are expected later
- keep one file for v1 unless scale forces partitioning

Legacy local per-user aggregation storage may continue to exist separately at:

```text
~/.bodaqs/session_aggregations_v1.json
```

but should be treated as a different backend, not the canonical store.

---

## 5. Canonical aggregation contract

### 5.1 Core identity

```python
AggregationKey = str
SessionKey = str
RegistryPolicy = Literal["union", "intersection", "strict"]
EventSchemaPolicy = RegistryPolicy
AggregationScope = Literal["canonical", "local"]
```

### 5.2 Aggregation definition

```python
@dataclass(frozen=True)
class AggregationDefinition:
    aggregation_key: str
    title: str
    member_session_keys: tuple[str, ...]
    registry_policy: RegistryPolicy = "union"
    event_schema_policy: EventSchemaPolicy = "union"
    created_at_utc: str = ""
    updated_at_utc: str = ""
    note: str | None = None
```

This can remain effectively unchanged from the current implementation.

### 5.3 Catalog-facing enrichment

For library management, the catalog layer may attach derived fields:

```python
@dataclass(frozen=True)
class AggregationCatalogRow:
    aggregation_key: str
    scope: AggregationScope
    title: str
    n_members: int
    registry_policy: RegistryPolicy
    event_schema_policy: EventSchemaPolicy
    created_at_utc: str | None
    updated_at_utc: str | None
    note: str | None
    member_session_keys: tuple[str, ...]
```

These are projection/catalog fields, not necessarily the raw storage schema.

---

## 6. Store contract

### 6.1 Store protocol

```python
class AggregationStore(Protocol):
    def load(self) -> None: ...
    def save(self) -> None: ...
    def list(self) -> list[AggregationDefinition]: ...
    def get(self, aggregation_key: str) -> AggregationDefinition | None: ...
    def create(
        self,
        *,
        title: str,
        member_session_keys: Sequence[str],
        registry_policy: RegistryPolicy = "union",
        event_schema_policy: EventSchemaPolicy = "union",
        note: str | None = None,
        aggregation_key: str | None = None,
    ) -> AggregationDefinition: ...
    def update(self, aggregation_key: str, *, patch: Mapping[str, Any]) -> AggregationDefinition: ...
    def delete(self, aggregation_key: str) -> bool: ...
```

The current `SessionAggregationStore` is already close to this shape.

### 6.2 Canonical backend

Recommended concrete implementation:

```python
class CanonicalAggregationStore(AggregationStore):
    ...
```

Responsibilities:

- persist canonical aggregations under `artifacts/library/aggregations_v1.json`
- use schema/versioned JSON
- use atomic writes
- validate all entries on load/save

### 6.3 Local backend

The current implementation may remain as:

```python
class LocalAggregationStore(AggregationStore):
    ...
```

Responsibilities:

- persist local per-user aggregations under `~/.bodaqs/session_aggregations_v1.json`
- support one-time migration/import into the canonical store

### 6.4 Unified resolution (optional)

If needed later:

```python
class CompositeAggregationStore(AggregationStore):
    ...
```

Possible semantics:

- read from canonical + local stores
- local keys must not silently shadow canonical keys
- duplicated keys across scopes should be treated as an error unless explicit precedence is configured

Do not implement composite behavior until canonical/local scope decisions are stable.

---

## 7. Validation and integrity rules

### 7.1 Keep current rules

- aggregation key required
- title required
- non-empty member session key list
- valid `session_key` format
- policy limited to `union|intersection|strict`

### 7.2 Additional canonical checks

Canonical library-management flows should additionally validate:

1. **member existence**
   - all member session keys should resolve against the current artifacts tree

2. **notes/catalog compatibility**
   - no special note/schema dependency is required in v1

3. **selection semantics**
   - expansion behavior remains non-destructive
   - aggregations are definitions, not materialized combined sessions

### 7.3 Non-goal

Do not require that all members share identical notes/templates.

Those differences may matter for catalog analysis, but they should not block the existence of an aggregation.

---

## 8. Selector/library integration contract

### 8.1 Selector consumption

The selector should consume aggregations through a store/service boundary, not directly own persistence.

Recommended selector-facing contract:

```python
class AggregationProvider(Protocol):
    def list(self) -> list[AggregationDefinition]: ...
    def get(self, aggregation_key: str) -> AggregationDefinition | None: ...
```

This is enough for entity-selection use.

### 8.2 Library-management consumption

Library management should use the fuller store contract for:

- browse
- create/update/delete
- later filtering/searching

### 8.3 Shared entity model

Selectors and widgets should continue to consume aggregations through the existing `ScopeEntity` / `EntitySelectionSnapshot` model.

That part of the current architecture is already correct.

---

## 9. Recommended module structure

### 9.1 Target structure

Recommended end-state:

```text
analysis/bodaqs_analysis/library/
    aggregations.py
    session_notes.py
    catalog.py
    selectors.py          # optional, if selector-facing adapters are needed
    ui/
        library_manager.py
```

### 9.2 Responsibilities

`aggregations.py`
- aggregation contracts
- validation
- canonical/local store implementations

`session_notes.py`
- note/template contracts and storage

`catalog.py`
- flat catalog dataframe builders for sessions, notes, and aggregations

`ui/library_manager.py`
- notebook-facing management UI for runs, sessions, notes, descriptions, aggregations

### 9.3 Widget layer responsibility

The widget layer should:

- consume aggregation providers
- not be the primary home of canonical aggregation persistence

---

## 10. Migration from current implementation

### 10.1 Reuse directly

The following can be migrated with minimal conceptual change:

- `AggregationDefinition`
- store CRUD method shapes
- validation helpers
- session-key normalization
- expansion semantics in `entity_scope.py`

### 10.2 Reposition

The following should be repositioned:

- `SessionAggregationStore` should move or be wrapped as a local backend implementation
- `make_session_aggregation_editor(...)` should become a consumer of aggregation services, not their owner

### 10.3 Keep compatibility temporarily

For an incremental migration, it is acceptable to:

1. keep the local store only as a compatibility/import path
2. introduce canonical aggregation services in parallel
3. retarget selector/editor defaults to the canonical backend

This avoids a disruptive rewrite.

---

## 11. Implementation order

1. Extract aggregation contracts/service boundary from widget-owned persistence
2. Implement canonical aggregation store under the library layer
3. Keep current local store as a separate backend
4. Add aggregation rows into the library/catalog service
5. Build library-management UI on the canonical store
6. Retarget selector aggregation consumption to the canonical provider
7. Optionally support local + canonical aggregation views later

---

## 12. Recommendation

Build the new library-management functionality **on top of the current aggregation model and logic**, but **not directly on top of the current widget-local persistence/editor implementation**.

That is the right compromise:

- maximum reuse of correct domain logic
- minimum entrenchment of the wrong persistence/UI boundary
