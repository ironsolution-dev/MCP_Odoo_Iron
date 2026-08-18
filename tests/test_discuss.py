"""Tests G4 (Fase A daily driver): Discuss (leer/postear canal) + copiar
adjunto hacia una tarea.

Cubre: lectura de canal allowlisted, canal NO listado denegado y visible en
audit, post con read-after-write, copia de adjunto sin mutar el original,
adjunto de canal fuera de allowlist denegado aunque el ID exista, y
file_size>limite denegado ANTES de leer el binario (datas).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.audit import Audit
from app.policy_engine import PolicyEngine
from app.schemas import ValidationError
from app.token_registry import TokenRegistry
from app.tools.discuss import (
    odoo_attach_discuss_attachment_to_task,
    odoo_post_discuss_message,
    odoo_read_discuss_channel,
)


class FakeOdoo:
    """Doble de OdooClient. `read_returns`/`search_read_returns` aceptan un
    valor fijo o un callable(*, ids/domain, fields) para responder distinto
    segun los campos pedidos (necesario para distinguir el read de `datas`
    del read de metadatos post-copia sobre el MISMO modelo ir.attachment).

    Deliberadamente NO define `write` ni `unlink`: si el codigo bajo prueba
    intentara mutar el adjunto original, el test fallaria con AttributeError
    en vez de pasar en falso.
    """

    def __init__(self, search_read_returns: dict = None, read_returns: dict = None,
                call_returns=77, create_returns=999):
        self.calls: list[tuple] = []
        self.search_read_returns = search_read_returns or {}
        self.read_returns = read_returns or {}
        self.call_returns = call_returns
        self.create_returns = create_returns
        self._uid = 42

    async def authenticate(self, actor):
        return self._uid

    async def search_read(self, actor, model, domain, fields, limit=50, offset=0, order=None):
        self.calls.append(("search_read", model, domain, list(fields)))
        handler = self.search_read_returns.get(model)
        if callable(handler):
            return handler(domain, fields)
        return handler if handler is not None else []

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", model, tuple(ids), list(fields)))
        handler = self.read_returns.get(model)
        if callable(handler):
            return handler(ids, fields)
        return handler if handler is not None else [{"id": ids[0]}]

    async def call(self, actor, model, method, args, kwargs=None):
        self.calls.append(("call", model, method, args, kwargs))
        return self.call_returns

    async def create(self, actor, model, values):
        self.calls.append(("create", model, values))
        return self.create_returns


# ---------------------------------------------------------------------------
# Lectura de canal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_discuss_channel_allowlisted_ok(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    messages = [{"id": 1, "body": "hola equipo", "author_id": {"id": 9, "name": "Willy"},
                 "date": "2026-08-18 10:00:00", "message_type": "comment", "attachment_ids": []}]
    odoo = FakeOdoo(search_read_returns={"mail.message": messages})
    actor = reg.verify(token_willy)

    result = await odoo_read_discuss_channel(actor, odoo, pe, channel_id=53, limit=10)

    assert result == messages
    call = next(c for c in odoo.calls if c[0] == "search_read" and c[1] == "mail.message")
    assert ("res_id", "=", 53) in call[2]
    assert ("model", "=", "discuss.channel") in call[2]


@pytest.mark.asyncio
async def test_read_discuss_channel_not_allowlisted_denied_and_audited(
    actors_yaml, policies_yaml, env_actors, token_willy, tmp_path: Path,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    with pytest.raises(PermissionError) as exc:
        await odoo_read_discuss_channel(actor, odoo, pe, channel_id=99, limit=10)
    assert str(exc.value) == "discuss_channel_not_allowed:99"
    assert odoo.calls == []  # se corta antes de tocar Odoo

    # El mismo patron que _audited() en odoo_mcp_remote.py: denied_reason =
    # str(exc)[:120]. Prueba que el motivo queda VISIBLE en audit.jsonl.
    audit = Audit(tmp_path / "audit.jsonl")
    audit.emit(actor=actor.actor, role=actor.role, tool="odoo_read_discuss_channel",
              model="mail.message", action="read", allowed=False,
              denied_reason=str(exc.value)[:120])
    lines = [json.loads(l) for l in audit.log_path.read_text().splitlines() if l.strip()]
    assert lines[0]["allowed"] is False
    assert lines[0]["denied_reason"] == "discuss_channel_not_allowed:99"


# ---------------------------------------------------------------------------
# Post + read-after-write
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_discuss_message_read_after_write(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    posted = {"id": 123, "body": "reporte enviado", "author_id": {"id": 9, "name": "Willy"},
              "date": "2026-08-18 11:00:00", "message_type": "comment", "attachment_ids": []}
    odoo = FakeOdoo(call_returns=123, read_returns={"mail.message": [posted]})
    actor = reg.verify(token_willy)

    result = await odoo_post_discuss_message(actor, odoo, pe, channel_id=53, body="reporte enviado")

    assert result == posted
    ops = [c[0] for c in odoo.calls]
    assert ops.index("call") < ops.index("read"), "read-after-write violado"
    read_call = next(c for c in odoo.calls if c[0] == "read")
    assert read_call[2] == (123,)


@pytest.mark.asyncio
async def test_post_discuss_message_empty_body_rejected(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)
    with pytest.raises(ValidationError):
        await odoo_post_discuss_message(actor, odoo, pe, channel_id=53, body="   ")
    assert odoo.calls == []


# ---------------------------------------------------------------------------
# Copiar adjunto — COPIA, nunca mueve
# ---------------------------------------------------------------------------

def _attach_fixture():
    """search_read_returns compartidos para los tests de exito de attach."""
    return {
        "mail.message": [{"id": 5}],  # el attachment SI pertenece a un mensaje del canal
        "ir.attachment": [{"id": 77, "name": "foto.png", "mimetype": "image/png",
                            "file_size": 1000, "res_model": "discuss.channel", "res_id": 53}],
        "project.task": [{"id": 42}],
    }


@pytest.mark.asyncio
async def test_attach_copies_without_mutating_original(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)

    def read_ir_attachment(ids, fields):
        if "datas" in fields:
            return [{"id": ids[0], "datas": "QmFzZTY0ZGF0YQ=="}]
        # read-after-write de la COPIA nueva (id distinto del original 77)
        return [{"id": 999, "name": "foto.png", "mimetype": "image/png",
                 "file_size": 1000, "res_model": "project.task", "res_id": 42}]

    odoo = FakeOdoo(
        search_read_returns=_attach_fixture(),
        read_returns={"ir.attachment": read_ir_attachment},
        create_returns=999,
    )
    actor = reg.verify(token_willy)

    result = await odoo_attach_discuss_attachment_to_task(
        actor, odoo, pe, channel_id=53, attachment_id=77, task_id=42)

    assert result["copied"] is True
    assert result["attachment"]["id"] == 999
    assert result["source_attachment_id"] == 77
    assert result["task_id"] == 42

    create_calls = [c for c in odoo.calls if c[0] == "create"]
    assert len(create_calls) == 1
    values = create_calls[0][2]
    assert values["res_model"] == "project.task"
    assert values["res_id"] == 42
    assert values["name"] == "foto.png"

    # El original (id 77 en discuss.channel/53) nunca se escribe ni se borra:
    # FakeOdoo no define write/unlink, asi que cualquier intento habria
    # reventado con AttributeError antes de llegar aqui.
    assert not any(c[0] in ("write", "unlink") for c in odoo.calls)


@pytest.mark.asyncio
async def test_attach_denied_when_channel_not_allowlisted_even_if_id_exists(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    # El attachment "existiria" (fixture lo tendria), pero channel_id=99 no
    # esta en discuss_channel_allowlist: se corta ANTES de consultarlo.
    odoo = FakeOdoo(search_read_returns=_attach_fixture())
    actor = reg.verify(token_willy)

    with pytest.raises(PermissionError) as exc:
        await odoo_attach_discuss_attachment_to_task(
            actor, odoo, pe, channel_id=99, attachment_id=77, task_id=42)
    assert str(exc.value) == "discuss_channel_not_allowed:99"
    assert odoo.calls == []


@pytest.mark.asyncio
async def test_attach_file_too_large_denied_before_reading_datas(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    oversized = dict(_attach_fixture())
    oversized["ir.attachment"] = [{"id": 77, "name": "video.mp4", "mimetype": "video/mp4",
                                   "file_size": 999_999_999,  # > 10 MB default
                                   "res_model": "discuss.channel", "res_id": 53}]
    odoo = FakeOdoo(search_read_returns=oversized)
    actor = reg.verify(token_willy)

    with pytest.raises(ValidationError) as exc:
        await odoo_attach_discuss_attachment_to_task(
            actor, odoo, pe, channel_id=53, attachment_id=77, task_id=42)
    assert "attachment_too_large" in str(exc.value)

    # Nunca se llego a pedir el binario: cero "read" con fields=["datas"],
    # de hecho cero "read" en absoluto (el unico read del flujo es datas).
    read_calls = [c for c in odoo.calls if c[0] == "read"]
    assert read_calls == []
    create_calls = [c for c in odoo.calls if c[0] == "create"]
    assert create_calls == []


@pytest.mark.asyncio
async def test_attach_attachment_not_in_channel_denied(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    # El attachment existe, pero NO pertenece a ningun mensaje del canal 53.
    odoo = FakeOdoo(search_read_returns={"mail.message": []})
    actor = reg.verify(token_willy)

    with pytest.raises(PermissionError) as exc:
        await odoo_attach_discuss_attachment_to_task(
            actor, odoo, pe, channel_id=53, attachment_id=999, task_id=42)
    assert "attachment_not_in_channel" in str(exc.value)
    create_calls = [c for c in odoo.calls if c[0] == "create"]
    assert create_calls == []
