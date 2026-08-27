"""Entry point MCP Odoo v2 — multiusuario Bearer auth + policy engine.

Usa mcp 1.27.0 (mcp.server.fastmcp.FastMCP) + uvicorn directo.
El middleware Bearer intercepta Authorization header via streamable_http_app()
y pasa el actor al ContextVar que cada tool lee.
"""
from __future__ import annotations

import os
import uvicorn
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.audit import Audit
from app.auth_middleware import AuthMiddleware
from app.credentials_resolver import CredentialsResolver
from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.rate_limit import RateLimiter
from app.token_registry import ActorEntry, TokenRegistry
from app.tools import system as S, tasks as T, projects as P
from app.tools import calendar as C, employees as E, crm as CR, partners as PA
from app.tools import attachments as AT
from app.tools import discuss as D
from app.tools import openai_compat as OC

# ---------------------------------------------------------------------------
# ContextVar: pasa el actor desde middleware a cada tool
# ---------------------------------------------------------------------------
_actor: ContextVar[Optional[ActorEntry]] = ContextVar('actor', default=None)

# Globals inicializados en load() antes de arrancar uvicorn
_registry: Optional[TokenRegistry] = None
_policy: Optional[PolicyEngine] = None
_odoo: Optional[OdooClient] = None
_mw: Optional[AuthMiddleware] = None


def load() -> None:
    global _registry, _policy, _odoo, _mw
    _registry = TokenRegistry(Path(os.environ['ACTORS_REGISTRY_PATH']))
    _policy   = PolicyEngine(Path(os.environ['POLICIES_PATH']))
    _audit    = Audit(Path(os.environ['AUDIT_LOG_PATH']))
    _odoo     = OdooClient(CredentialsResolver())
    _mw       = AuthMiddleware(_registry, _policy, RateLimiter(), _audit)


# ---------------------------------------------------------------------------
# Middleware ASGI puro — permite reescribir el path antes de FastMCP
# ---------------------------------------------------------------------------
_JSON_401 = (
    b'{"jsonrpc":"2.0","id":null,'
    b'"error":{"code":-32001,"message":"Unauthorized: invalid_token"}}'
)


class BearerMiddleware:
    """Middleware ASGI mínimamente invasivo:
    - GET /mcp: pasa directo a FastMCP (que maneja SSE o devuelve 406 si no es SSE,
      tal como BLUE). NO intercepta para evitar romper el protocolo MCP estándar.
    - POST /mcp: extrae token de Bearer, X-Api-Key o path opaco. Reescribe
      /mcp/<token> → /mcp y autentica al actor. 401 si el token no es válido.
    - Resto de paths: pasa directo.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        path   = scope.get('path', '')
        method = scope.get('method', '')

        if not path.startswith('/mcp'):
            await self.app(scope, receive, send)
            return

        # GET: pasar directo a FastMCP. Si Accept incluye text/event-stream,
        # FastMCP abre SSE; si no, devuelve 406 (comportamiento estándar MCP).
        if method == 'GET':
            await self.app(scope, receive, send)
            return

        # POST: requiere autenticacion.
        headers_raw = dict(scope.get('headers', []))
        auth      = headers_raw.get(b'authorization', b'').decode()
        x_api_key = headers_raw.get(b'x-api-key', b'').decode()
        ua        = headers_raw.get(b'user-agent', b'').decode()
        token, src = AuthMiddleware.extract_token(auth, path, x_api_key)
        actor = _registry.verify(token) if _registry else None

        if not actor:
            if _mw:
                _mw.audit.emit(
                    allowed=False,
                    denied_reason='invalid_token',
                    client_type=AuthMiddleware.detect_client_type(ua, src),
                )
            await self._send_json(send, 401, _JSON_401)
            return

        # Si el token vino en el path (/mcp/<token>), reescribir → /mcp
        # para que FastMCP lo procese en su endpoint registrado.
        if src == 'path' and path != '/mcp':
            scope = {**scope, 'path': '/mcp', 'raw_path': b'/mcp'}

        tok = _actor.set(actor)
        try:
            await self.app(scope, receive, send)
        finally:
            _actor.reset(tok)

    @staticmethod
    async def _send_json(send: Send, status: int, body: bytes) -> None:
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'application/json'),
                                (b'content-length', str(len(body)).encode())]})
        await send({'type': 'http.response.body', 'body': body, 'more_body': False})


from app.auth_middleware import now_ms


def _a() -> ActorEntry:
    a = _actor.get()
    if not a:
        raise PermissionError('no_authenticated_actor')
    return a


async def _audited(coro, tool_name: str, actor: Optional[ActorEntry] = None):
    """Ejecuta coro y emite audit entry de success o error con latencia.

    actor debe pasarse explicitamente desde el scope de la tool (@mcp.tool),
    donde el ContextVar si es accesible. No leer _actor.get() aqui: Starlette
    BaseHTTPMiddleware ejecuta call_next en un task group separado de anyio y
    la copia del ContextVar puede no propagarse a este scope.
    """
    start = now_ms()
    try:
        result = await coro
        if _mw and actor:
            # Para search/fetch que devuelven {"results": [...]} contar el array
            # interno. Para listas contar largo. Para otros dicts contar 1.
            if isinstance(result, list):
                rc = len(result)
            elif isinstance(result, dict) and isinstance(result.get('results'), list):
                rc = len(result['results'])
            else:
                rc = 1
            _mw.audit.emit(
                actor=actor.actor,
                role=actor.role,
                tool=tool_name,
                allowed=True,
                latency_ms=now_ms() - start,
                result_count=rc,
            )
        return result
    except Exception as exc:
        is_denied = isinstance(exc, PermissionError)
        if _mw and actor:
            _mw.audit.emit(
                actor=actor.actor,
                role=actor.role,
                tool=tool_name,
                allowed=not is_denied,
                denied_reason=str(exc)[:120] if is_denied else None,
                error_class=None if is_denied else exc.__class__.__name__,
                latency_ms=now_ms() - start,
            )
        raise


# ---------------------------------------------------------------------------
# FastMCP + registro de tools
# ---------------------------------------------------------------------------
mcp = FastMCP(
    'odoo-mcp-v2',
    instructions=(
        "Servidor MCP multiusuario para Odoo APL 2.0 con capacidad COMPLETA "
        "de lectura Y escritura. ChatGPT chat-mode descubre `search(query)` y "
        "`fetch(id)` — usalas para TODO. "
        ""
        "READS: search('mis tareas'), search('proyectos'), search('empleados'), "
        "search('contactos'), search('leads crm'), search('eventos'), "
        "search('quien soy'). Drill-down con fetch('task:N'), fetch('project:N'), etc. "
        ""
        "WRITES (esto es CRITICO): para crear, modificar, cerrar, cancelar o mover "
        "tareas/proyectos/eventos, DEBES llamar search() pasando un STRING JSON "
        "como query. El JSON debe tener clave 'action' con uno de estos valores: "
        "create_task, create_todo, update_task, move_task, move_task_to_project, "
        "close_task, cancel_task, create_project, create_event, whoami. "
        ""
        "EJEMPLO de write: el usuario dice 'crea una tarea de X en proyecto Y'. "
        "Tu DEBES armar el JSON con todos los campos APL 2.0: title en texto "
        "libre (verbo + entregable + contexto, SIN prefijos ni corchetes), "
        "description con 8 campos con encabezado emoji (👤 Responsable / "
        "🎯 Objetivo / 📦 Entregable / 📅 Fecha limite / ✅ Criterio de cierre / "
        "📎 Evidencia requerida / ⚠️ Riesgo si no se cierra / ▶️ Siguiente "
        "accion), deadline (YYYY-MM-DD), area (departamento que EJECUTA: "
        "Comercial/Contabilidad-Finanzas/Marketing/Operaciones/RR.HH/"
        "Tecnologia/Gerencia/Staff Profesionales Salud), task_type "
        "(Entregable/Documentacion/Decision/Proyecto/Handover/Recurrente/"
        "Gestion), priority (P0-P3) — y llamar search(query=JSON_STRING). El "
        "servidor resuelve las 3 etiquetas canonicas (prioridad, "
        "departamento, tipo) desde su propia fuente de IDs: si area o "
        "task_type no matchean un nombre conocido, la tarea se crea igual "
        "sin esa etiqueta y el aviso viene en la respuesta. "
        ""
        "PROHIBIDO responder 'no puedo escribir' o 'no hay endpoint' — SI HAY "
        "endpoint, es esta misma tool search(). Si te falta un dato pregunta al "
        "usuario, NO inventes que no se puede. "
        ""
        "Si llamas search() con verbos de escritura sin JSON, recibiras un "
        "help_response — eso es una INSTRUCCION para ti (no info para el usuario): "
        "arma el JSON con los datos que tengas y llama search() de nuevo en el "
        "siguiente turno. "
        ""
        "Validaciones server-side: APL 2.0 (title + 8 campos en description), "
        "read-after-write, policy engine. Si la creacion falla, devuelvo error "
        "claro con el campo problema — reintenta con el dato corregido."
    ),
    stateless_http=True,
    json_response=True,
    host='0.0.0.0',
    port=8000,
)


@mcp.tool()
async def odoo_who_am_i(ctx: Context) -> dict:
    """Retorna el actor MCP autenticado, su UID real en Odoo, rol y política activa."""
    a = _a(); return await _audited(S.odoo_who_am_i(a, _odoo), 'odoo_who_am_i', a)

@mcp.tool()
async def odoo_health(ctx: Context) -> dict:
    """Healthcheck del servidor MCP y la conexión con Odoo."""
    a = _a(); return await _audited(S.odoo_health(a, _odoo), 'odoo_health', a)

@mcp.tool()
async def odoo_validate_apl_stages(ctx: Context) -> dict:
    """Lista las etapas APL 2.0 disponibles en Odoo con sus IDs reales."""
    a = _a(); return await _audited(S.odoo_validate_apl_stages(a, _odoo), 'odoo_validate_apl_stages', a)

@mcp.tool()
async def odoo_my_tasks(ctx: Context, limit: int = 50) -> list:
    """Lista las tareas personales To Do del usuario actual en Odoo (sin proyecto asignado)."""
    a = _a(); return await _audited(T.odoo_my_tasks(a, _odoo, _policy, limit=limit), 'odoo_my_tasks', a)

@mcp.tool()
async def odoo_my_tasks_today(ctx: Context, stage_today_id: int, limit: int = 50) -> list:
    """Lista las tareas del actor en la etapa Hoy. Requiere stage_today_id del APL (usa odoo_validate_apl_stages para obtenerlo)."""
    a = _a(); return await _audited(T.odoo_my_tasks_today(a, _odoo, _policy, stage_today_id, limit=limit), 'odoo_my_tasks_today', a)

@mcp.tool()
async def odoo_my_tasks_overdue(ctx: Context, today_iso: str, limit: int = 50) -> list:
    """Lista las tareas vencidas del actor. today_iso en formato YYYY-MM-DD."""
    a = _a(); return await _audited(T.odoo_my_tasks_overdue(a, _odoo, _policy, today_iso, limit=limit), 'odoo_my_tasks_overdue', a)

@mcp.tool()
async def odoo_create_my_todo_apl(ctx: Context, payload: dict) -> dict:
    """Crea una tarea To Do personal APL 2.0. payload incluye titulo, descripcion, prioridad, fecha_limite."""
    a = _a(); return await _audited(T.odoo_create_my_todo_apl(a, _odoo, _policy, payload), 'odoo_create_my_todo_apl', a)

@mcp.tool()
async def odoo_create_project_task_apl(ctx: Context, project_id: int, payload: dict) -> dict:
    """Crea una tarea en un proyecto de Odoo siguiendo el formato APL 2.0."""
    a = _a(); return await _audited(T.odoo_create_project_task_apl(a, _odoo, _policy, project_id, payload), 'odoo_create_project_task_apl', a)

@mcp.tool()
async def odoo_update_task_apl(ctx: Context, task_id: int, changes: dict) -> dict:
    """Actualiza campos permitidos de una tarea en Odoo. Acepta alias deadline->date_deadline (no enviar ambos). Campos: name, description, priority, date_deadline, stage_id, tag_ids, user_ids. project_id NO editable aqui: usa odoo_move_task_to_project."""
    a = _a(); return await _audited(T.odoo_update_task_apl(a, _odoo, _policy, task_id, changes), 'odoo_update_task_apl', a)

@mcp.tool()
async def odoo_move_task(ctx: Context, task_id: int, stage_id: int) -> dict:
    """Mueve una tarea a otra etapa del APL 2.0."""
    a = _a(); return await _audited(T.odoo_move_task(a, _odoo, _policy, task_id, stage_id), 'odoo_move_task', a)

@mcp.tool()
async def odoo_move_task_to_project(ctx: Context, task_id: int, new_project_id: int) -> dict:
    """Mueve una tarea a otro proyecto. Registra el movimiento en el chatter y hace read-after-write. NO usar update_task/odoo_update_task_apl para esto: project_id esta bloqueado ahi a proposito."""
    a = _a(); return await _audited(T.odoo_move_task_to_project(a, _odoo, _policy, task_id, new_project_id), 'odoo_move_task_to_project', a)

@mcp.tool()
async def odoo_mark_task_done(ctx: Context, task_id: int, evidence: str, done_stage_id: int) -> dict:
    """Cierra una tarea con evidencia obligatoria y hace read-after-write."""
    a = _a(); return await _audited(T.odoo_mark_task_done(a, _odoo, _policy, task_id, evidence, done_stage_id), 'odoo_mark_task_done', a)

@mcp.tool()
async def odoo_cancel_task(ctx: Context, task_id: int, reason: str, cancelled_stage_id: int) -> dict:
    """Cancela una tarea registrando el motivo."""
    a = _a(); return await _audited(T.odoo_cancel_task(a, _odoo, _policy, task_id, reason, cancelled_stage_id), 'odoo_cancel_task', a)

@mcp.tool()
async def odoo_list_projects(ctx: Context, limit: int = 50) -> list:
    """Lista los proyectos visibles para el actor en Odoo."""
    a = _a(); return await _audited(P.odoo_list_projects(a, _odoo, _policy, limit=limit), 'odoo_list_projects', a)

@mcp.tool()
async def odoo_get_project(ctx: Context, project_id: int) -> dict:
    """Obtiene el detalle de un proyecto por ID."""
    a = _a(); return await _audited(P.odoo_get_project(a, _odoo, _policy, project_id), 'odoo_get_project', a)

@mcp.tool()
async def odoo_create_project(ctx: Context, name: str, description: str = None,
                               user_id: int = None) -> dict:
    """Crea un nuevo proyecto en Odoo con campos básicos."""
    a = _a(); return await _audited(P.odoo_create_project(a, _odoo, _policy, name, description, user_id), 'odoo_create_project', a)

@mcp.tool()
async def odoo_update_project_basic(ctx: Context, project_id: int, changes: dict) -> dict:
    """Actualiza campos básicos de un proyecto (nombre, descripcion, responsable)."""
    a = _a(); return await _audited(P.odoo_update_project_basic(a, _odoo, _policy, project_id, changes), 'odoo_update_project_basic', a)

@mcp.tool()
async def odoo_project_tasks(ctx: Context, project_id: int, limit: int = 100) -> list:
    """Lista las tareas de un proyecto específico en Odoo."""
    a = _a(); return await _audited(P.odoo_project_tasks(a, _odoo, _policy, project_id, limit=limit), 'odoo_project_tasks', a)

@mcp.tool()
async def odoo_list_calendar_events(ctx: Context, start_after: str, end_before: str,
                                    limit: int = 100) -> list:
    """Lista eventos de calendario entre dos fechas ISO (YYYY-MM-DD)."""
    a = _a(); return await _audited(C.odoo_list_calendar_events(a, _odoo, _policy, start_after, end_before, limit=limit), 'odoo_list_calendar_events', a)

@mcp.tool()
async def odoo_create_calendar_event(ctx: Context, name: str, start: str, stop: str,
                                     description: str = None, location: str = None,
                                     partner_ids: list = None, allday: bool = False) -> dict:
    """Crea un evento en el calendario de Odoo. start y stop en formato ISO."""
    a = _a(); return await _audited(C.odoo_create_calendar_event(a, _odoo, _policy, name, start, stop,
                                               description, location, partner_ids, allday), 'odoo_create_calendar_event', a)

@mcp.tool()
async def odoo_update_calendar_event(ctx: Context, event_id: int, changes: dict) -> dict:
    """Actualiza un evento de calendario existente."""
    a = _a(); return await _audited(C.odoo_update_calendar_event(a, _odoo, _policy, event_id, changes), 'odoo_update_calendar_event', a)

@mcp.tool()
async def odoo_list_employees(ctx: Context, department_id: int = None, limit: int = 50) -> list:
    """Lista empleados activos en Odoo. Solo campos permitidos (sin datos financieros ni privados)."""
    a = _a(); return await _audited(E.odoo_list_employees(a, _odoo, _policy, department_id=department_id, limit=limit), 'odoo_list_employees', a)

@mcp.tool()
async def odoo_get_employee(ctx: Context, employee_id: int) -> dict:
    """Obtiene el detalle de un empleado por ID."""
    a = _a(); return await _audited(E.odoo_get_employee(a, _odoo, _policy, employee_id), 'odoo_get_employee', a)

@mcp.tool()
async def odoo_search_employee(ctx: Context, query: str, limit: int = 20) -> list:
    """Busca empleados por nombre o email en Odoo."""
    a = _a(); return await _audited(E.odoo_search_employee(a, _odoo, _policy, query, limit=limit), 'odoo_search_employee', a)

@mcp.tool()
async def odoo_list_crm_leads(ctx: Context, stage_id: int = None, limit: int = 50) -> list:
    """Lista leads y oportunidades CRM en Odoo. Solo lectura."""
    a = _a(); return await _audited(CR.odoo_list_crm_leads(a, _odoo, _policy, stage_id=stage_id, limit=limit), 'odoo_list_crm_leads', a)

@mcp.tool()
async def odoo_get_crm_lead(ctx: Context, lead_id: int) -> dict:
    """Obtiene el detalle de un lead o oportunidad CRM."""
    a = _a(); return await _audited(CR.odoo_get_crm_lead(a, _odoo, _policy, lead_id), 'odoo_get_crm_lead', a)

@mcp.tool()
async def odoo_add_crm_note(ctx: Context, lead_id: int, body: str) -> dict:
    """Agrega una nota interna a un lead o oportunidad CRM."""
    a = _a(); return await _audited(CR.odoo_add_crm_note(a, _odoo, _policy, lead_id, body), 'odoo_add_crm_note', a)

@mcp.tool()
async def odoo_create_crm_activity(ctx: Context, lead_id: int, summary: str, deadline: str,
                                    activity_type_id: int, user_id: int = None,
                                    note: str = None) -> dict:
    """Crea una actividad programada en un lead CRM."""
    a = _a(); return await _audited(CR.odoo_create_crm_activity(a, _odoo, _policy, lead_id, summary,
                                              deadline, activity_type_id, user_id, note), 'odoo_create_crm_activity', a)

@mcp.tool()
async def odoo_list_partners(ctx: Context, only_companies: bool = False, limit: int = 50) -> list:
    """Lista contactos o empresas en Odoo. Solo campos permitidos (sin datos fiscales ni financieros)."""
    a = _a(); return await _audited(PA.odoo_list_partners(a, _odoo, _policy, only_companies=only_companies, limit=limit), 'odoo_list_partners', a)

@mcp.tool()
async def odoo_get_partner(ctx: Context, partner_id: int) -> dict:
    """Obtiene el detalle de un contacto por ID."""
    a = _a(); return await _audited(PA.odoo_get_partner(a, _odoo, _policy, partner_id), 'odoo_get_partner', a)

@mcp.tool()
async def odoo_search_partner(ctx: Context, query: str, limit: int = 20) -> list:
    """Busca contactos por nombre, email o teléfono en Odoo."""
    a = _a(); return await _audited(PA.odoo_search_partner(a, _odoo, _policy, query, limit=limit), 'odoo_search_partner', a)

@mcp.tool()
async def odoo_get_task(ctx: Context, task_id: int) -> dict:
    """Obtiene el detalle completo de una tarea por ID, incluyendo padre y subtareas."""
    a = _a(); return await _audited(T.odoo_get_task(a, _odoo, _policy, task_id), 'odoo_get_task', a)

@mcp.tool()
async def odoo_task_subtasks(ctx: Context, parent_task_id: int, limit: int = 100) -> list:
    """Lista las subtareas (hijas) de una tarea padre en Odoo."""
    a = _a(); return await _audited(T.odoo_task_subtasks(a, _odoo, _policy, parent_task_id, limit=limit), 'odoo_task_subtasks', a)

@mcp.tool()
async def odoo_list_attachments(ctx: Context, model: str, record_id: int, limit: int = 50) -> list:
    """Lista adjuntos (archivos, imágenes, documentos) asociados a un registro de Odoo. Acepta model='project.task' o 'project.project'. Retorna metadatos + URL de descarga."""
    a = _a(); return await _audited(AT.odoo_list_attachments(a, _odoo, _policy, model, record_id, limit=limit), 'odoo_list_attachments', a)

@mcp.tool()
async def odoo_get_attachment(ctx: Context, attachment_id: int) -> dict:
    """Obtiene los metadatos y URL de descarga de un adjunto específico por ID."""
    a = _a(); return await _audited(AT.odoo_get_attachment(a, _odoo, _policy, attachment_id), 'odoo_get_attachment', a)

# ---------------------------------------------------------------------------
# Discuss (sec G4) — canales allowlisted por policy. Fase 1: solo owner_policy.
# ---------------------------------------------------------------------------

@mcp.tool()
async def odoo_read_discuss_channel(ctx: Context, channel_id: int, limit: int = 50) -> list:
    """Lee mensajes de un canal de Discuss (chatter de discuss.channel). Solo canales explicitamente allowlisted por policy — deniega aunque el ID exista."""
    a = _a(); return await _audited(D.odoo_read_discuss_channel(a, _odoo, _policy, channel_id, limit=limit), 'odoo_read_discuss_channel', a)

@mcp.tool()
async def odoo_post_discuss_message(ctx: Context, channel_id: int, body: str) -> dict:
    """Posta un mensaje de texto plano en un canal de Discuss allowlisted. Read-after-write."""
    a = _a(); return await _audited(D.odoo_post_discuss_message(a, _odoo, _policy, channel_id, body), 'odoo_post_discuss_message', a)

@mcp.tool()
async def odoo_attach_discuss_attachment_to_task(ctx: Context, channel_id: int, attachment_id: int, task_id: int) -> dict:
    """Copia (NUNCA mueve) un adjunto de un mensaje de Discuss hacia una tarea. El adjunto original y el mensaje del canal quedan intactos. Verifica tamano ANTES de leer el binario."""
    a = _a(); return await _audited(D.odoo_attach_discuss_attachment_to_task(a, _odoo, _policy, channel_id, attachment_id, task_id), 'odoo_attach_discuss_attachment_to_task', a)

# ---------------------------------------------------------------------------
# OpenAI ChatGPT chat-mode adapter: search + fetch
# ChatGPT chat-mode solo descubre tools con estos 2 nombres exactos. Routean
# internamente a las tools odoo_* segun query/id. Claude.ai sigue viendo todo.
# ---------------------------------------------------------------------------

@mcp.tool()
async def search(ctx: Context, query: str) -> dict:
    """Busca tareas, proyectos, empleados, contactos, leads o eventos en Odoo segun el texto del query. Devuelve {results:[{id,title,text,url}]} con ids "<kind>:<num>" para usar con fetch(). Usa esta tool cuando el usuario pida ver/listar/buscar cualquier cosa en Odoo: tareas, proyectos, contactos, etc."""
    a = _a(); return await _audited(OC.search(a, _odoo, _policy, query), 'search', a)

@mcp.tool()
async def fetch(ctx: Context, id: str) -> dict:
    """Obtiene el detalle completo de un registro Odoo por id compuesto. El id debe ser "<kind>:<num>" donde kind es task/project/employee/partner/lead. Por ejemplo "task:42" o "project:7". Usalo despues de search() para profundizar en un resultado."""
    a = _a(); return await _audited(OC.fetch(a, _odoo, _policy, id), 'fetch', a)


# Write tools — nombres simples que ChatGPT chat-mode puede descubrir. Cada uno
# enruta a la tool odoo_* nativa correspondiente con APL 2.0 + read-after-write.

@mcp.tool()
async def create_task(ctx: Context, project_id: int, title: str, description: str,
                       deadline: str, area: str, task_type: str,
                       priority: str = "P2") -> dict:
    """Crea una tarea APL 2.0 dentro de un proyecto. project_id obligatorio. APL 2.0 exige: title (verbo + entregable + contexto, sin corchetes), description con 8 campos emoji (Responsable/Objetivo/Entregable/Fecha limite/Criterio de cierre/Evidencia requerida/Riesgo si no se cierra/Siguiente accion), deadline (YYYY-MM-DD), area (departamento que ejecuta), task_type (tipo de ticket), priority (P0-P3, default P2)."""
    a = _a(); return await _audited(OC.create_task(a, _odoo, _policy, project_id, title, description, deadline, area, task_type, priority), 'create_task', a)

@mcp.tool()
async def create_todo(ctx: Context, title: str, description: str,
                       deadline: str, area: str, task_type: str,
                       priority: str = "P2") -> dict:
    """Crea un To-Do personal APL 2.0 sin proyecto. Mismos campos APL que create_task pero sin project_id."""
    a = _a(); return await _audited(OC.create_todo(a, _odoo, _policy, title, description, deadline, area, task_type, priority), 'create_todo', a)

@mcp.tool()
async def update_task(ctx: Context, id: str, changes: dict) -> dict:
    """Actualiza campos de una tarea. id puede ser "task:42" o "42". Campos editables: name, description, priority, date_deadline (alias: deadline; no enviar los dos a la vez), stage_id, tag_ids, user_ids. project_id NO es editable aqui: usa move_task_to_project."""
    a = _a(); return await _audited(OC.update_task(a, _odoo, _policy, id, changes), 'update_task', a)

@mcp.tool()
async def move_task(ctx: Context, id: str, stage_id: int) -> dict:
    """Mueve una tarea a otra etapa. Usa odoo_validate_apl_stages para conocer stage_ids disponibles."""
    a = _a(); return await _audited(OC.move_task(a, _odoo, _policy, id, stage_id), 'move_task', a)

@mcp.tool()
async def move_task_to_project(ctx: Context, id: str, new_project_id: int) -> dict:
    """Mueve una tarea a otro proyecto. Distinto de move_task (que solo cambia de etapa)."""
    a = _a(); return await _audited(OC.move_task_to_project(a, _odoo, _policy, id, new_project_id), 'move_task_to_project', a)

@mcp.tool()
async def close_task(ctx: Context, id: str, evidence: str, done_stage_id: int) -> dict:
    """Cierra una tarea con evidencia obligatoria (APL 2.0). La evidencia queda en el chatter. done_stage_id es el ID de la etapa Done del flujo APL."""
    a = _a(); return await _audited(OC.close_task(a, _odoo, _policy, id, evidence, done_stage_id), 'close_task', a)

@mcp.tool()
async def cancel_task(ctx: Context, id: str, reason: str, cancelled_stage_id: int) -> dict:
    """Cancela una tarea registrando el motivo en el chatter. cancelled_stage_id es el ID de la etapa Cancelled del flujo APL."""
    a = _a(); return await _audited(OC.cancel_task(a, _odoo, _policy, id, reason, cancelled_stage_id), 'cancel_task', a)

@mcp.tool()
async def create_project(ctx: Context, name: str, description: str = None,
                          user_id: int = None) -> dict:
    """Crea un proyecto nuevo en Odoo. name obligatorio. description y user_id (responsable) opcionales."""
    a = _a(); return await _audited(OC.create_project(a, _odoo, _policy, name, description, user_id), 'create_project', a)

@mcp.tool()
async def create_event(ctx: Context, name: str, start: str, stop: str,
                        description: str = None, location: str = None,
                        partner_ids: list = None, allday: bool = False) -> dict:
    """Crea un evento de calendario. start y stop en ISO (YYYY-MM-DD HH:MM:SS). partner_ids es lista de IDs de res.partner invitados."""
    a = _a(); return await _audited(OC.create_event(a, _odoo, _policy, name, start, stop, description, location, partner_ids, allday), 'create_event', a)


# Aliases BLUE — compatibilidad con conectores que usan nombres originales
odoo_personal_tasks  = odoo_my_tasks
odoo_test_connection = odoo_who_am_i

# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    load()
    # BearerMiddleware es ASGI puro: wrapping directo, no add_middleware()
    # Esto permite reescribir scope['path'] antes de que FastMCP lo procese.
    inner = mcp.streamable_http_app()
    app   = BearerMiddleware(inner)
    uvicorn.run(app, host='0.0.0.0', port=8000)
