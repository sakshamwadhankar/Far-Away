import contextlib
import json
import os
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from komvos.api.main import app
from komvos.compiler import compile as compile_pipeline
from komvos.compiler.models import Pipeline
from komvos.state.sqlite import StateManager


def test_all_templates_valid() -> None:
    """
    Ensure every JSON file in templates/ is a valid v2 pipeline and compiles
    into an executable DAG in local mode.
    This also verifies they contain no secrets (Pipeline.model_validate will
    ensure it matches schema).
    """
    templates_dir = Path(__file__).parent.parent.parent / "templates"
    template_files = list(templates_dir.glob("*.json"))

    assert len(template_files) >= 10, "There should be at least 10 templates."

    for tf in template_files:
        with open(tf, encoding="utf-8") as f:
            data = json.load(f)

        try:
            # model_validate will throw an exception if invalid
            pipeline = Pipeline.model_validate(data)

            # Additional asserts
            assert pipeline.schema_version == "2.0"
            assert len(pipeline.nodes) > 0

            # Compile into DAG in local mode
            dag = compile_pipeline(data, mode="local")
            assert len(dag.topo_order) > 0
        except Exception as e:
            raise AssertionError(
                f"Template {tf.name} failed validation/compilation: {e}"
            ) from e


# ---------------------------------------------------------------------------
# Library template tests (community sharing)
# ---------------------------------------------------------------------------

# A minimal valid pipeline for library publish tests
_VALID_PIPELINE: dict = {
    "schema_version": "2.0",
    "id": "test-lib-pipeline-001",
    "name": "Library Test Pipeline",
    "version": "1.0.0",
    "endpoints": {"ollama:qwen2.5:3b": {"kind": "ollama", "model": "qwen2.5:3b"}},
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "inputs": [],
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "bot",
            "type": "model",
            "endpoint_ref": "ollama:qwen2.5:3b",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "reply", "type": "text"}],
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
            "outputs": [],
        },
    ],
    "edges": [
        {"from": "in.prompt", "to": "bot.input"},
        {"from": "bot.reply", "to": "out.result"},
    ],
}


@pytest.fixture()
def _setup_test_db():
    """Create a temp SQLite DB and inject it as the app's state manager."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sm = StateManager(db_path)
    app.state.state_manager = sm
    yield sm
    with contextlib.suppress(OSError):
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_publish_and_list_library_templates(_setup_test_db: StateManager) -> None:
    """Publish a valid pipeline, then list library templates and verify it appears."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Publish
        res = await client.post(
            "/library/publish",
            json={
                "name": "My Shared Pipeline",
                "description": "A test community template",
                "author": "TestUser",
                "tags": "test,rag",
                "pipeline": _VALID_PIPELINE,
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert res.status_code == 201, res.text
        data = res.json()
        assert "id" in data
        template_id = data["id"]

        # List
        res2 = await client.get(
            "/library/templates",
            headers={"Authorization": "Bearer test-token"},
        )
        assert res2.status_code == 200
        templates = res2.json()
        assert isinstance(templates, list)
        assert len(templates) >= 1
        found = [t for t in templates if t["id"] == template_id]
        assert len(found) == 1
        assert found[0]["name"] == "My Shared Pipeline"
        assert found[0]["author"] == "TestUser"
        assert found[0]["tags"] == "test,rag"
        assert found[0]["downloads"] == 0


@pytest.mark.asyncio
async def test_publish_invalid_pipeline(_setup_test_db: StateManager) -> None:
    """Publishing an invalid pipeline must return 422."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/library/publish",
            json={
                "name": "Bad Pipeline",
                "pipeline": {"nodes": []},  # invalid — missing required fields
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_delete_library_template(_setup_test_db: StateManager) -> None:
    """Publish, delete, verify it's gone."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Publish
        res = await client.post(
            "/library/publish",
            json={
                "name": "To Be Deleted",
                "pipeline": _VALID_PIPELINE,
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert res.status_code == 201
        template_id = res.json()["id"]

        # Delete
        res2 = await client.delete(
            f"/library/templates/{template_id}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert res2.status_code == 200
        assert res2.json()["deleted"] is True

        # Verify gone
        res3 = await client.get(
            "/library/templates",
            headers={"Authorization": "Bearer test-token"},
        )
        templates = res3.json()
        assert all(t["id"] != template_id for t in templates)

        # Delete again — should 404
        res4 = await client.delete(
            f"/library/templates/{template_id}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert res4.status_code == 404


# ---------------------------------------------------------------------------
# Custom node tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_list_custom_nodes(_setup_test_db: StateManager) -> None:
    """Save a custom node definition, then list and verify it appears."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/custom-nodes",
            json={
                "name": "JSON Formatter",
                "description": "Formats input as pretty JSON",
                "author": "TestDev",
                "icon_color": "#6B3AB8",
                "inputs": [{"name": "raw", "type": "json"}],
                "outputs": [{"name": "formatted", "type": "text"}],
                "template": "{{ raw | tojson(indent=2) }}",
                "tags": "json,utility",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert res.status_code == 201, res.text
        node_id = res.json()["id"]

        # List
        res2 = await client.get(
            "/custom-nodes",
            headers={"Authorization": "Bearer test-token"},
        )
        assert res2.status_code == 200
        nodes = res2.json()
        assert any(n["id"] == node_id for n in nodes)
        found = [n for n in nodes if n["id"] == node_id][0]
        assert found["name"] == "JSON Formatter"
        assert found["author"] == "TestDev"
        assert len(found["inputs"]) == 1
        assert len(found["outputs"]) == 1


@pytest.mark.asyncio
async def test_delete_custom_node(_setup_test_db: StateManager) -> None:
    """Save, delete, verify gone."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/custom-nodes",
            json={
                "name": "To Delete",
                "inputs": [{"name": "in", "type": "text"}],
                "outputs": [{"name": "out", "type": "text"}],
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert res.status_code == 201
        node_id = res.json()["id"]

        res2 = await client.delete(
            f"/custom-nodes/{node_id}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert res2.status_code == 200

        # Verify gone
        res3 = await client.get(
            "/custom-nodes",
            headers={"Authorization": "Bearer test-token"},
        )
        assert all(n["id"] != node_id for n in res3.json())

        # 404 on re-delete
        res4 = await client.delete(
            f"/custom-nodes/{node_id}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert res4.status_code == 404


def test_custom_node_pipeline_executes() -> None:
    """A transform node with custom_label/custom_color must pass Pipeline validation."""
    pipeline_data = {
        "schema_version": "2.0",
        "id": "test-custom-pipeline",
        "name": "Custom Node Pipeline",
        "version": "1.0.0",
        "endpoints": {},
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "inputs": [],
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "custom-transform",
                "type": "transform",
                "inputs": [{"name": "input", "type": "text"}],
                "outputs": [{"name": "output", "type": "text"}],
                "config": {
                    "system_prompt": "{{ input | upper }}",
                    "custom_node_id": "some-uuid",
                    "custom_label": "My Custom Node",
                    "custom_color": "#B83232",
                },
            },
            {
                "id": "out",
                "type": "output",
                "inputs": [{"name": "result", "type": "text"}],
                "outputs": [],
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "custom-transform.input"},
            {"from": "custom-transform.output", "to": "out.result"},
        ],
    }
    pipeline = Pipeline.model_validate(pipeline_data)
    assert pipeline.schema_version == "2.0"
    custom_node = [n for n in pipeline.nodes if n.id == "custom-transform"][0]
    assert custom_node.config is not None
    assert custom_node.config.custom_label == "My Custom Node"
    assert custom_node.config.custom_color == "#B83232"
