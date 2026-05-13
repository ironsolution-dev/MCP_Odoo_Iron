"""Cliente Odoo actor-aware via XML-RPC.

Reglas (sec 2.2, 5.4, 7.1 Task Packet):
- UID se obtiene por authenticate() del actor — NUNCA hardcodear UID 9 ni de Willy.
- API Key NUNCA en logs, NUNCA en responses, NUNCA en str(client).
- NO se expone metodo `execute_kw` generico al exterior; los tools llaman
  metodos especificos (search_read, read, create, write).
- NO se usa `sudo` ni context con privilege escalation.
- UID cacheado por actor con TTL 5min para evitar round-trips innecesarios.
"""

from __future__ import annotations

import asyncio
import re
import time
import xmlrpc.client
from dataclasses import dataclass
from typing import Any, Optional

from app.credentials_resolver import CredentialsResolver, OdooCredentials
from app.token_registry import ActorEntry


UID_CACHE_TTL_SECONDS = 300  # 5 minutos

# Limites para no inundar contexto del LLM
_DESCRIPTION_MAX_CHARS = 800
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_SPACE_RE = re.compile(r"\s+")
# Campos donde Odoo guarda HTML que el LLM no necesita renderizado
_HTML_FIELDS = {"description", "note", "body", "comment", "summary"}


def _normalize_value(field: str, value: Any) -> Any:
    """Limpia valores crudos de Odoo para que el LLM los parsee sin ambigüedad.

    - False (Odoo: 'sin valor') -> None
    - [id, "Display Name"] (Odoo many2one) -> {"id": id, "name": name}
    - HTML en description/note/body -> texto plano, max 800 chars
    """
    if value is False:
        return None
    if isinstance(value, list) and len(value) == 2 \
            and isinstance(value[0], int) and isinstance(value[1], str):
        # Odoo many2one tuple
        return {"id": value[0], "name": value[1]}
    if field in _HTML_FIELDS and isinstance(value, str) and "<" in value:
        text = _HTML_TAG_RE.sub(" ", value)
        text = _HTML_SPACE_RE.sub(" ", text).strip()
        if len(text) > _DESCRIPTION_MAX_CHARS:
            text = text[: _DESCRIPTION_MAX_CHARS - 1] + "…"
        return text
    return value


def _normalize_record(record: dict) -> dict:
    return {k: _normalize_value(k, v) for k, v in record.items()}


class OdooAuthError(RuntimeError):
    """Authenticate retorno false; user/api_key invalido o user disabled."""


class OdooAccessError(RuntimeError):
    """Odoo ACL denego la operacion."""


@dataclass
class _CachedUid:
    uid: int
    expires_at: float


class OdooClient:
    def __init__(self, resolver: Optional[CredentialsResolver] = None):
        self._resolver = resolver or CredentialsResolver()
        self._uid_cache: dict[str, _CachedUid] = {}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_creds(self, actor: ActorEntry) -> OdooCredentials:
        return self._resolver.resolve(actor)

    def _common_proxy(self, url: str) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(f"{url.rstrip('/')}/xmlrpc/2/common", allow_none=True)

    def _object_proxy(self, url: str) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(f"{url.rstrip('/')}/xmlrpc/2/object", allow_none=True)

    def _authenticate_sync(self, creds: OdooCredentials) -> int:
        common = self._common_proxy(creds.url)
        uid = common.authenticate(creds.db, creds.username, creds.api_key, {})
        if not uid:
            raise OdooAuthError(f"authenticate failed for user={creds.username!r}")
        return int(uid)

    def _execute_kw_sync(
        self,
        creds: OdooCredentials,
        uid: int,
        model: str,
        method: str,
        args: list,
        kwargs: Optional[dict] = None,
    ) -> Any:
        models = self._object_proxy(creds.url)
        try:
            return models.execute_kw(creds.db, uid, creds.api_key, model, method, args, kwargs or {})
        except xmlrpc.client.Fault as e:
            msg = (e.faultString or "").lower()
            if "access" in msg or "permission" in msg or "groups" in msg:
                raise OdooAccessError(e.faultString) from None
            raise

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def authenticate(self, actor: ActorEntry) -> int:
        """Autentica al actor en Odoo y retorna UID. Cachea TTL 5min por actor."""
        now = time.monotonic()
        cached = self._uid_cache.get(actor.actor)
        if cached and cached.expires_at > now:
            return cached.uid

        creds = self._get_creds(actor)
        uid = await asyncio.to_thread(self._authenticate_sync, creds)
        self._uid_cache[actor.actor] = _CachedUid(uid=uid, expires_at=now + UID_CACHE_TTL_SECONDS)
        return uid

    async def get_credentials(self, actor: ActorEntry) -> OdooCredentials:
        """Resuelve creds (sin auth). Util para tools que necesitan url/db/username."""
        return self._get_creds(actor)

    async def search_read(
        self,
        actor: ActorEntry,
        model: str,
        domain: list,
        fields: list[str],
        limit: int = 50,
        offset: int = 0,
        order: Optional[str] = None,
    ) -> list[dict]:
        uid = await self.authenticate(actor)
        creds = self._get_creds(actor)
        kwargs: dict[str, Any] = {"fields": fields, "limit": limit, "offset": offset}
        if order:
            kwargs["order"] = order
        raw = await asyncio.to_thread(
            self._execute_kw_sync, creds, uid, model, "search_read", [domain], kwargs
        )
        return [_normalize_record(r) for r in raw]

    async def read(
        self,
        actor: ActorEntry,
        model: str,
        ids: list[int],
        fields: list[str],
    ) -> list[dict]:
        uid = await self.authenticate(actor)
        creds = self._get_creds(actor)
        raw = await asyncio.to_thread(
            self._execute_kw_sync, creds, uid, model, "read", [ids], {"fields": fields}
        )
        return [_normalize_record(r) for r in raw]

    async def create(
        self,
        actor: ActorEntry,
        model: str,
        values: dict,
    ) -> int:
        uid = await self.authenticate(actor)
        creds = self._get_creds(actor)
        return await asyncio.to_thread(
            self._execute_kw_sync, creds, uid, model, "create", [values], {}
        )

    async def write(
        self,
        actor: ActorEntry,
        model: str,
        ids: list[int],
        values: dict,
    ) -> bool:
        uid = await self.authenticate(actor)
        creds = self._get_creds(actor)
        return await asyncio.to_thread(
            self._execute_kw_sync, creds, uid, model, "write", [ids, values], {}
        )

    async def call(
        self,
        actor: ActorEntry,
        model: str,
        method: str,
        args: list,
        kwargs: Optional[dict] = None,
    ) -> Any:
        """Metodo restringido para llamar acciones especificas (ej. message_post,
        action_done). Las tools que lo usen DEBEN validar via policy_engine antes."""
        uid = await self.authenticate(actor)
        creds = self._get_creds(actor)
        return await asyncio.to_thread(
            self._execute_kw_sync, creds, uid, model, method, args, kwargs or {}
        )

    # ------------------------------------------------------------------
    # Server info
    # ------------------------------------------------------------------

    async def server_version(self, actor: ActorEntry) -> dict:
        creds = self._get_creds(actor)
        return await asyncio.to_thread(
            lambda: self._common_proxy(creds.url).version()
        )

    def invalidate_uid_cache(self, actor: Optional[str] = None) -> None:
        if actor is None:
            self._uid_cache.clear()
        else:
            self._uid_cache.pop(actor, None)
