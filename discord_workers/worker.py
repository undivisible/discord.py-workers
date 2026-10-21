"""A small, interaction-only Discord handler for Cloudflare Workers."""

from __future__ import annotations

import inspect
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from workers import Response, WorkerEntrypoint

_logger = logging.getLogger('discord_workers')
_COMMAND_ATTRIBUTE = '__discord_workers_command__'
_SIGNATURE_MAX_AGE_SECONDS = 300


@dataclass(frozen=True)
class _CommandDefinition:
    name: str
    description: str
    options: Optional[Tuple[Mapping[str, Any], ...]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'name': self.name,
            'description': self.description,
            'type': 1,
        }
        if self.options is not None:
            result['options'] = [dict(option) for option in self.options]
        return result


def command(
    *,
    description: str,
    name: Optional[str] = None,
    options: Optional[Sequence[Mapping[str, Any]]] = None,
):
    """Mark an instance method as a Discord slash command.

    ``options`` uses Discord's application-command option schema directly.
    """

    def decorate(callback):
        definition = _CommandDefinition(
            name=name or callback.__name__,
            description=description,
            options=tuple(dict(option) for option in options) if options is not None else None,
        )
        setattr(callback, _COMMAND_ATTRIBUTE, definition)
        return callback

    return decorate


def _registered_commands(cls) -> Dict[str, Tuple[str, _CommandDefinition]]:
    commands: Dict[str, Tuple[str, _CommandDefinition]] = {}
    for base in reversed(cls.__mro__):
        for attribute_name, callback in vars(base).items():
            definition = getattr(callback, _COMMAND_ATTRIBUTE, None)
            if definition is not None:
                commands[definition.name] = (attribute_name, definition)
    return commands


@dataclass(frozen=True)
class InteractionResponse:
    """An immediate Discord message response to an application interaction."""

    content: str
    ephemeral: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            'content': self.content,
            'allowed_mentions': {'parse': []},
        }
        if self.ephemeral:
            data['flags'] = 64
        return {'type': 4, 'data': data}


@dataclass(frozen=True)
class Interaction:
    """The raw Discord payload plus a few common fields and a response helper."""

    payload: Mapping[str, Any]

    @property
    def data(self) -> Mapping[str, Any]:
        value = self.payload.get('data')
        return value if isinstance(value, Mapping) else {}

    @property
    def user(self) -> Optional[Mapping[str, Any]]:
        member = self.payload.get('member')
        if isinstance(member, Mapping):
            user = member.get('user')
            return user if isinstance(user, Mapping) else member
        user = self.payload.get('user')
        return user if isinstance(user, Mapping) else None

    @property
    def guild_id(self) -> Optional[str]:
        value = self.payload.get('guild_id')
        return value if isinstance(value, str) else None

    @property
    def channel_id(self) -> Optional[str]:
        value = self.payload.get('channel_id')
        return value if isinstance(value, str) else None

    def respond(self, content: str, *, ephemeral: bool = False) -> InteractionResponse:
        """Build an immediate message response, optionally visible only to its user."""

        if not isinstance(content, str):
            raise TypeError('interaction response content must be a string')
        return InteractionResponse(content=content, ephemeral=ephemeral)


class WorkerBot(WorkerEntrypoint):
    """Cloudflare Worker entrypoint for Discord HTTP application interactions.

    Subclass this class, declare methods with :func:`command`, and configure the
    Discord application interactions URL to end in ``/interactions``.
    """

    async def fetch(self, request):
        path = urlsplit(request.url).path
        if request.method == 'GET' and path == '/':
            return Response.json({'status': 'ok'})

        if request.method != 'POST' or path != '/interactions':
            return Response('Not found', status=404)

        signature = request.headers.get('x-signature-ed25519')
        timestamp = request.headers.get('x-signature-timestamp')
        if not signature or not timestamp:
            return Response('Missing Discord signature headers', status=401)

        public_key = getattr(self.env, 'DISCORD_PUBLIC_KEY', None)
        if not public_key:
            return Response('Worker is missing DISCORD_PUBLIC_KEY', status=500)

        body = await request.text()
        if not await self._verify_signature(body, signature, timestamp, public_key):
            return Response('Invalid request signature', status=401)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return Response('Invalid JSON body', status=400)

        if not isinstance(payload, dict):
            return Response('Invalid interaction payload', status=400)

        response = await self._interaction_response(payload)
        if response is None:
            return Response('Unsupported interaction', status=400)
        return Response.json(response)

    @classmethod
    def application_commands(cls) -> List[Dict[str, Any]]:
        """Return command definitions for Discord's application-command REST API."""

        return [definition.to_dict() for _attribute, definition in _registered_commands(cls).values()]

    async def _verify_signature(self, body: str, signature: str, timestamp: str, public_key: str) -> bool:
        return await verify_signature(body, signature, timestamp, public_key)

    async def _interaction_response(self, payload: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        interaction_type = payload.get('type')
        if type(interaction_type) is int and interaction_type == 1:
            return {'type': 1}
        if type(interaction_type) is not int or interaction_type != 2:
            return None

        data = payload.get('data')
        if not isinstance(data, Mapping) or not isinstance(data.get('name'), str):
            return None

        registered = _registered_commands(type(self)).get(data['name'])
        if registered is None:
            return InteractionResponse('Unknown command.', ephemeral=True).to_dict()

        attribute_name, _definition = registered
        interaction = Interaction(payload)
        try:
            result = getattr(self, attribute_name)(interaction)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, str):
                result = interaction.respond(result)
            if not isinstance(result, InteractionResponse):
                raise TypeError('command handlers must return a string or InteractionResponse')
            return result.to_dict()
        except Exception:
            _logger.exception('Discord command %r failed', data['name'])
            return InteractionResponse('The command failed. Please try again.', ephemeral=True).to_dict()


async def verify_signature(body: str, signature: str, timestamp: str, public_key: str) -> bool:
    """Verify Discord's Ed25519 signature using the Workers Web Crypto runtime."""

    if not isinstance(signature, str) or len(signature) != 128:
        return False
    if not isinstance(public_key, str) or len(public_key) != 64:
        return False

    try:
        timestamp_seconds = int(timestamp)
        if abs(int(time.time()) - timestamp_seconds) > _SIGNATURE_MAX_AGE_SECONDS:
            return False
        signature_bytes = bytes.fromhex(signature)
        public_key_bytes = bytes.fromhex(public_key)
    except (TypeError, ValueError):
        return False

    if len(signature_bytes) != 64 or len(public_key_bytes) != 32:
        return False

    try:
        from js import Object, Uint8Array, crypto
        from pyodide.ffi import to_js

        def uint8_array(value):
            return Uint8Array.new(to_js(list(value)))

        algorithm = to_js({'name': 'Ed25519'}, dict_converter=Object.fromEntries)
        key = await crypto.subtle.importKey(
            'raw',
            uint8_array(public_key_bytes),
            algorithm,
            False,
            to_js(['verify']),
        )
        message = uint8_array((timestamp + body).encode('utf-8'))
        return bool(
            await crypto.subtle.verify(
                algorithm,
                key,
                uint8_array(signature_bytes),
                message,
            )
        )
    except Exception:
        return False
