Cloudflare Workers
==================

``discord_workers`` is a small HTTP-interactions package for Cloudflare's Python Workers
runtime. It uses Workers' ``WorkerEntrypoint`` and ``Response`` classes and the runtime's Web
Crypto API to validate Discord's Ed25519 request signatures.

This package is intentionally separate from ``discord``. Importing ``discord`` starts the
upstream Gateway client and its ``aiohttp`` dependency; neither is used by ``discord_workers``.
This package supports application-command HTTP interactions only. It does not open a Discord
Gateway connection, make general Discord REST calls, or support voice.

Requirements
------------

Use Cloudflare's Python Worker runtime (Pyodide) and include this repository's
``discord_workers`` package in the Python Worker bundle. The fork's ``aiohttp`` and
``audioop-lts`` dependencies are excluded on ``emscripten``; the package itself has no third-party
Python dependencies. Follow Cloudflare's current `Python Workers guide
<https://developers.cloudflare.com/workers/languages/python/>`__ for project setup and local
development.

Worker entrypoint
-----------------

Define the Worker by subclassing ``WorkerBot``. Each decorated method becomes a chat-input
slash command. A handler can return a string or an ``InteractionResponse`` from
``interaction.respond``:

.. code-block:: python

    from discord_workers import Interaction, WorkerBot, command


    class Default(WorkerBot):
        @command(description='Check whether the bot is responding')
        async def ping(self, interaction: Interaction):
            return interaction.respond('Pong!')

The Worker exposes ``GET /`` as a health check and accepts Discord requests at
``POST /interactions``. Set the Discord application's **Interactions Endpoint URL** to the
Worker URL ending in ``/interactions``. Discord's verification PING is answered with PONG.

Configure ``DISCORD_PUBLIC_KEY`` as a Worker secret/binding containing the application's
64-character hexadecimal public key from the Discord Developer Portal. Do not put a bot token
in Worker configuration for this interaction-only flow. Discord signs the exact request body
with the timestamp; the library verifies that Ed25519 signature with Web Crypto and rejects
timestamps more than five minutes from the Worker clock.

Command registration
--------------------

``Default.application_commands()`` returns the JSON definitions expected by Discord's
application-command REST API. For example, evaluate it in a local Python environment and use
the returned JSON as the body for Discord's **Bulk Overwrite Global Application Commands**
endpoint. To import ``WorkerBot`` in a regular Python environment for this step, install
Cloudflare's ``workers-runtime-sdk`` as a development dependency. Registering commands is a
deployment/setup step, not a request-time Worker action.

Command options can be provided using Discord's option schema directly:

.. code-block:: python

    from discord_workers import WorkerBot, command


    class Default(WorkerBot):
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
        async def greet(self, interaction):
            name = interaction.data['options'][0]['value']
            return interaction.respond('Hello, {}!'.format(name), ephemeral=True)

Responses are immediate interaction messages. Ephemeral responses are available with
``ephemeral=True``. Returned content disables mentions by default to avoid accidental user or
``@everyone`` pings. Handlers should finish within Discord's initial interaction response
deadline; this package does not implement deferred responses or follow-up webhook requests.

Request handling and state
--------------------------

Each invocation is an independent HTTP request. Do not rely on Python module globals for
persistent or per-user state; use an appropriate Cloudflare binding when state must survive
requests. The library handles only the initial interaction callback and leaves command-specific
authorization, application logic, and durable state to the Worker.
