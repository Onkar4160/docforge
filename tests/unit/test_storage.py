from __future__ import annotations

from pathlib import Path

import pytest

from docforge.container import Container
from docforge.core.errors import NotFoundError, StorageError
from docforge.models.artifact import Artifact, ArtifactVersion
from docforge.models.conversation import Message, Role, Session
from docforge.models.intent import OutputFormat
from docforge.models.ir import DeckPlan, SlideArchetype, SlidePlan
from docforge.storage import BlobStore


def _deck(title: str = "Deck") -> DeckPlan:
    return DeckPlan(
        title=title,
        slides=[SlidePlan(id="s01", purpose="open", archetype=SlideArchetype.title, headline=title)],
    )


def test_repository_put_get_update(container: Container):
    repo = container.repos.sessions
    repo.put(Session(id="ses_1", owner="demo", title="A"))
    assert repo.get("ses_1").title == "A"
    repo.put(Session(id="ses_1", owner="demo", title="B"))
    assert repo.require("ses_1").title == "B"
    assert repo.get("missing") is None
    with pytest.raises(NotFoundError):
        repo.require("missing")


def test_list_by_parent_in_insert_order(container: Container):
    for i in range(3):
        container.repos.messages.put(
            Message(id=f"msg_{i}", session_id="ses_1", role=Role.user, content=str(i))
        )
    container.repos.messages.put(Message(id="msg_x", session_id="ses_2", role=Role.user, content="other"))
    assert [m.content for m in container.repos.messages.list_by_parent("ses_1")] == ["0", "1", "2"]


def test_delete(container: Container):
    container.repos.sessions.put(Session(id="ses_1", owner="demo"))
    assert container.repos.sessions.delete("ses_1") is True
    assert container.repos.sessions.delete("ses_1") is False


def test_artifact_versions_are_sequential_and_immutable(container: Container):  # FR-EDIT-1
    repos = container.repos
    repos.artifacts.put(Artifact(id="art_1", task_id="tsk_1", format=OutputFormat.pptx))
    repos.add_artifact_version(ArtifactVersion(artifact_id="art_1", version=1, ir=_deck("v1")))
    repos.add_artifact_version(
        ArtifactVersion(artifact_id="art_1", version=2, parent_version=1, ir=_deck("v2"))
    )
    assert repos.artifacts.require("art_1").current_version == 2
    assert [v.ir.title for v in repos.artifact_versions.list_by_parent("art_1")] == ["v1", "v2"]

    with pytest.raises(StorageError, match="immutable"):
        repos.add_artifact_version(ArtifactVersion(artifact_id="art_1", version=2, ir=_deck("dup")))
    with pytest.raises(StorageError, match="does not follow"):
        repos.add_artifact_version(ArtifactVersion(artifact_id="art_1", version=5, ir=_deck("gap")))


def test_data_survives_container_restart(settings, fake_llm):  # FR-CONV-8
    c1 = Container.build(settings, llm=fake_llm)
    c1.repos.sessions.put(Session(id="ses_keep", owner="demo", title="persisted"))
    c1.engine.dispose()
    c2 = Container.build(settings, llm=fake_llm)
    assert c2.repos.sessions.require("ses_keep").title == "persisted"
    c2.engine.dispose()


def test_blob_store_content_addressed(tmp_path: Path):
    store = BlobStore(tmp_path / "blobs")
    a = store.put_bytes(b"hello", ".txt")
    b = store.put_bytes(b"hello", "txt")
    assert a == b
    assert store.read_bytes(a.path) == b"hello"
    assert store.exists(a.path)
    assert not store.exists("00/00/nothing")


def test_blob_store_blocks_path_traversal(tmp_path: Path):
    store = BlobStore(tmp_path / "blobs")
    (tmp_path / "secret.txt").write_text("x")
    with pytest.raises(StorageError, match="escapes"):
        store.resolve("../secret.txt")
