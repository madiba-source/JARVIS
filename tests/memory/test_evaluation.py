"""Deterministic retrieval evaluation and lightweight resource observation."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.memory.context import ContextAssembler
from app.memory.models import Candidate, Provenance, Query, Scope, Status, now
from app.memory.runtime import MemoryRuntime
from app.memory.service import MemoryService
from app.core.events import EventBus
from app.memory.config import MemoryConfig
from tests.memory.test_rag import Embeddings, candidate, setup


def test_retrieval_evaluation_dataset(tmp_path):
    service, scope = setup(tmp_path)
    other = Scope(namespace="project", project_id="unrelated")
    dataset = [
        # (scope, content, query, expected_first)
        (scope, "The deployment deadline is Friday", "when is the deployment deadline", "deadline"),
        (scope, "JARVIS uses SQLite for storage", "which database does jarvis use", "SQLite"),
        (scope, "The automobile registry needs migration", "car registry migration", "automobile"),
        (other, "Unrelated project fact about rockets", "rocket", "rockets"),
        (scope, "The user prefers dark mode", "preferred theme", "dark"),
    ]
    identities = {}
    for item_scope, content, _, key in dataset:
        identities[key] = service.capture(item_scope, candidate(content), approved=True).memory_id
    assert service.indexer.sync() == 5
    cases = [
        ("when is the deployment deadline", scope, "deadline"),
        ("which database does jarvis use", scope, "SQLite"),
        ("car registry migration", scope, "automobile"),
        ("preferred theme", scope, "dark"),
    ]
    successes, latencies, context_sizes = 0, [], []
    for text, query_scope, expected in cases:
        started = time.monotonic()
        result = service.retrieve(query_scope, Query(text=text))
        latencies.append((time.monotonic() - started) * 1000)
        context_sizes.append(ContextAssembler(service, query_scope).assemble(text, Query(text=text)).characters)
        if result.hits and result.hits[0].record.memory_id == identities[expected]:
            successes += 1
    assert successes == 4
    assert max(latencies) < 2000
    assert max(context_sizes) <= service.config.max_context_chars
    isolation = service.retrieve(other, Query(text="deployment deadline SQLite dark"))
    assert not isolation.hits or isolation.hits[0].record.memory_id == identities["rockets"]
    # Recency: newer correction wins over older contradicting fact.
    service.correct(scope, identities["dark"], 1, candidate("The user prefers light mode"), approved=True)
    # Stale dense matches are rejected until the corrected version is re-indexed.
    assert not service.retrieve(scope, Query(text="preferred theme")).hits
    assert service.indexer.sync() == 1
    assert service.retrieve(scope, Query(text="preferred theme")).hits[0].record.content.endswith("light mode")
    # Deleted memory is not retrievable even while its vector may briefly persist.
    service.transition(scope, identities["deadline"], Status.DELETED, approved=True)
    assert not service.retrieve(scope, Query(text="deployment deadline")).hits
    service.close()


def test_runtime_degrades_without_vector_and_survives_restore(tmp_path):
    bus = EventBus()
    runtime = MemoryRuntime(tmp_path / "data", MemoryConfig(), bus)
    assert runtime.available and not runtime.vector_available
    scope = Scope(namespace="global")
    item = runtime.service.capture(scope, candidate("restore recovery fact"), approved=True)
    backup = runtime.service.store.database.backup()
    runtime.service.store.database.restore(backup)
    runtime.service.store.reset_index()
    assert runtime.service.inspect(scope, item.memory_id) is not None
    context = runtime.context(scope, "Explain the fact", Query(text="restore"))
    assert context.memory_available
    runtime.close()
    broken = MemoryRuntime(tmp_path / "data", MemoryConfig(), bus, vector_enabled=True)
    # Vector startup may fail without a model; structured memory must remain usable.
    assert broken.available
    assert broken.context(scope, "task", Query(text="fact")).memory_available
    broken.close()


def test_boot_shutdown_with_memory(tmp_path):
    from app.core import JarvisCore
    from app.core.config import Settings
    settings = Settings(data_dir=tmp_path / "data", memory_enabled=True)
    core = JarvisCore(settings)
    core.start()
    assert core.memory_runtime.available
    core.shutdown()
    assert core.memory_runtime is None


def test_bounded_concurrent_index_and_retrieval(tmp_path):
    service, scope = setup(tmp_path)
    def worker(index):
        item = service.capture(scope, candidate(f"concurrent fact {index % 3}"), approved=True)
        service.retrieve(scope, Query(text=f"concurrent fact {index % 3}"))
        return item.memory_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(pool.map(worker, range(8)))
    assert service.indexer.sync() == 3
    assert len(set(identities)) == 3
    assert service.retrieve(scope, Query(text="concurrent")).available
    service.close()