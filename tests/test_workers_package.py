import asyncio
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    @classmethod
    def json(cls, value, status=200):
        return cls(json.dumps(value), status=status)

    def json_value(self):
        return json.loads(self.body)


class _FakeWorkerEntrypoint:
    pass


_workers = types.ModuleType('workers')
_workers.Response = _FakeResponse
_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
with patch.dict(sys.modules, {'workers': _workers}):
    from discord_workers import Interaction, WorkerBot, command, verify_signature


class _Request:
    def __init__(self, method, url, body='', headers=None):
        self.method = method
        self.url = url
        self._body = body
        self.headers = headers or {}

    async def text(self):
        return self._body


class _TestBot(WorkerBot):
    async def _verify_signature(self, body, signature, timestamp, public_key):
        return signature == 'valid' and timestamp == 'now' and public_key == 'a' * 64

    @command(description='Check whether the bot is responding')
    async def ping(self, interaction: Interaction):
        return interaction.respond('Pong!')

    @command(
        description='Greet a person',
        options=[
            {
                'type': 3,
                'name': 'name',
                'description': 'Name to greet',
                'required': True,
            }
        ],
    )
    async def greet(self, interaction: Interaction):
        name = interaction.data['options'][0]['value']
        return interaction.respond('Hello, {}!'.format(name), ephemeral=True)


class WorkersPackageTests(unittest.TestCase):
    def setUp(self):
        self.bot = _TestBot()
        self.bot.env = types.SimpleNamespace(DISCORD_PUBLIC_KEY='a' * 64)
        self.headers = {
            'x-signature-ed25519': 'valid',
            'x-signature-timestamp': 'now',
        }

    def fetch(self, request):
        return asyncio.run(self.bot.fetch(request))

    def test_exposes_command_schema_without_importing_gateway_client(self):
        self.assertEqual(
            _TestBot.application_commands(),
            [
                {
                    'name': 'ping',
                    'description': 'Check whether the bot is responding',
                    'type': 1,
                },
                {
                    'name': 'greet',
                    'description': 'Greet a person',
                    'type': 1,
                    'options': [
                        {
                            'type': 3,
                            'name': 'name',
                            'description': 'Name to greet',
                            'required': True,
                        }
                    ],
                },
            ],
        )

    def test_health_check_and_unknown_paths(self):
        health = self.fetch(_Request('GET', 'https://bot.example/'))
        self.assertEqual(health.status, 200)
        self.assertEqual(health.json_value(), {'status': 'ok'})
        missing = self.fetch(_Request('GET', 'https://bot.example/other'))
        self.assertEqual(missing.status, 404)

    def test_checks_signature_before_dispatching_ping_and_command(self):
        ping = self.fetch(_Request('POST', 'https://bot.example/interactions', '{"type":1}', self.headers))
        self.assertEqual(ping.status, 200)
        self.assertEqual(ping.json_value(), {'type': 1})

        command = self.fetch(
            _Request(
                'POST',
                'https://bot.example/interactions',
                '{"type":2,"data":{"name":"ping"}}',
                self.headers,
            )
        )
        self.assertEqual(
            command.json_value(),
            {
                'type': 4,
                'data': {
                    'content': 'Pong!',
                    'allowed_mentions': {'parse': []},
                },
            },
        )

        greeting = self.fetch(
            _Request(
                'POST',
                'https://bot.example/interactions',
                '{"type":2,"data":{"name":"greet","options":[{"name":"name","value":"Ada"}]}}',
                self.headers,
            )
        )
        self.assertEqual(
            greeting.json_value(),
            {
                'type': 4,
                'data': {
                    'content': 'Hello, Ada!',
                    'allowed_mentions': {'parse': []},
                    'flags': 64,
                },
            },
        )

    def test_rejects_missing_or_invalid_signature(self):
        missing = self.fetch(_Request('POST', 'https://bot.example/interactions', '{}'))
        self.assertEqual(missing.status, 401)

        invalid = dict(self.headers, **{'x-signature-ed25519': 'invalid'})
        response = self.fetch(_Request('POST', 'https://bot.example/interactions', '{}', invalid))
        self.assertEqual(response.status, 401)

    def test_unknown_command_is_ephemeral_and_json_errors_are_rejected(self):
        unknown = self.fetch(
            _Request(
                'POST',
                'https://bot.example/interactions',
                '{"type":2,"data":{"name":"missing"}}',
                self.headers,
            )
        )
        self.assertEqual(unknown.json_value()['data']['flags'], 64)

        malformed = self.fetch(_Request('POST', 'https://bot.example/interactions', '{', self.headers))
        self.assertEqual(malformed.status, 400)

    def test_signature_verifier_rejects_malformed_and_stale_inputs(self):
        import time

        self.assertFalse(asyncio.run(verify_signature('{}', 'not-hex', '0', '00')))
        self.assertFalse(asyncio.run(verify_signature('{}', '00' * 64, 'not-a-timestamp', '00' * 32)))
        old_timestamp = str(int(time.time()) - 301)
        self.assertFalse(asyncio.run(verify_signature('{}', '00' * 64, old_timestamp, '00' * 32)))


if __name__ == '__main__':
    unittest.main()
