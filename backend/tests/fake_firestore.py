"""An in-memory stand-in for the Firestore client.

Covers only what the services actually use: document get/set/update, equality
and range filters, ordering, limits, array-contains, `in`, Increment/ArrayUnion
sentinels, and transactions (run directly, since there is no contention).
"""

import copy
import uuid
from datetime import datetime

from google.cloud import firestore


class FakeSnapshot:
    def __init__(self, doc_id: str, data: dict | None):
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        return copy.deepcopy(self._data)


class FakeDocument:
    def __init__(self, store: dict, collection: str, doc_id: str):
        self._store = store
        self._collection = collection
        self.id = doc_id

    @property
    def _bucket(self) -> dict:
        return self._store.setdefault(self._collection, {})

    def set(self, data: dict) -> None:
        self._bucket[self.id] = copy.deepcopy(data)

    def update(self, data: dict) -> None:
        if self.id not in self._bucket:
            raise KeyError(self.id)

        current = self._bucket[self.id]
        for key, value in data.items():
            if isinstance(value, firestore.Increment):
                current[key] = current.get(key, 0) + value.value
            elif isinstance(value, firestore.ArrayUnion):
                merged = list(current.get(key) or [])
                merged.extend(v for v in value.values if v not in merged)
                current[key] = merged
            else:
                current[key] = copy.deepcopy(value)

    def get(self, transaction=None) -> FakeSnapshot:
        return FakeSnapshot(self.id, copy.deepcopy(self._bucket.get(self.id)))

    def collection(self, name: str) -> "FakeCollection":
        return FakeCollection(self._store, f"{self._collection}/{self.id}/{name}")


def _matches(data: dict, field: str, op: str, value) -> bool:
    actual = data.get(field)

    if op == "==":
        return actual == value
    if op == "array_contains":
        return isinstance(actual, list) and value in actual
    if op == "in":
        return actual in value
    if actual is None:
        # Firestore range filters skip documents where the field is null.
        return False
    if op == "<=":
        return actual <= value
    if op == "<":
        return actual < value
    if op == ">=":
        return actual >= value
    if op == ">":
        return actual > value
    raise NotImplementedError(op)


class FakeQuery:
    def __init__(self, store, collection, filters=None, order=None, limit=None):
        self._store = store
        self._collection = collection
        self._filters = filters or []
        self._order = order
        self._limit = limit

    def _clone(self, **overrides) -> "FakeQuery":
        return FakeQuery(
            self._store,
            self._collection,
            overrides.get("filters", self._filters),
            overrides.get("order", self._order),
            overrides.get("limit", self._limit),
        )

    def where(self, filter=None, **_) -> "FakeQuery":
        return self._clone(
            filters=[*self._filters, (filter.field_path, filter.op_string, filter.value)]
        )

    def order_by(self, field, direction=None) -> "FakeQuery":
        return self._clone(order=(field, direction))

    def limit(self, count: int) -> "FakeQuery":
        return self._clone(limit=count)

    def stream(self):
        bucket = self._store.get(self._collection, {})
        results = [
            FakeSnapshot(doc_id, copy.deepcopy(data))
            for doc_id, data in bucket.items()
            if all(_matches(data, *f) for f in self._filters)
        ]

        if self._order:
            field, direction = self._order
            results.sort(
                key=lambda s: s.to_dict().get(field) or datetime.min,
                reverse=direction == firestore.Query.DESCENDING,
            )

        if self._limit is not None:
            results = results[: self._limit]

        return iter(results)


class FakeCollection(FakeQuery):
    def __init__(self, store, name):
        super().__init__(store, name)
        self._name = name

    def document(self, doc_id: str | None = None) -> FakeDocument:
        return FakeDocument(self._store, self._name, doc_id or uuid.uuid4().hex)

    def add(self, data: dict) -> tuple[None, FakeDocument]:
        doc = self.document()
        doc.set(data)
        return None, doc


class FakeTransaction:
    """Applies writes immediately; @firestore.transactional drives the hooks."""

    _max_attempts = 1
    _id = b"fake-transaction"
    _read_only = False

    def __init__(self, store):
        self._store = store

    def update(self, ref: FakeDocument, data: dict) -> None:
        ref.update(data)

    def set(self, ref: FakeDocument, data: dict) -> None:
        ref.set(data)

    def _clean_up(self) -> None:
        pass

    def _begin(self, retry_id=None) -> None:
        pass

    def _rollback(self) -> None:
        pass

    def _commit(self) -> list:
        return []

    @property
    def in_progress(self) -> bool:
        return False


class FakeFirestore:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self._store, name)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self._store)

    def raw(self, collection: str) -> dict:
        return self._store.setdefault(collection, {})
