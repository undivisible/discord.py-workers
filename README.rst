discord.py-workers
==================

.. image:: https://discord.com/api/guilds/336642139381301249/embed.png
   :target: https://discord.gg/r3sSKJJ
   :alt: Discord server invite

This is a fork of `discord.py <https://github.com/Rapptz/discord.py>`__ with an additional,
standalone ``discord_workers`` package for handling Discord application interactions on
`Cloudflare Workers <https://developers.cloudflare.com/workers/languages/python/>`__.

The original ``discord`` package remains the upstream Gateway client and is intended for
regular Python runtimes. It is **not** what runs inside a Worker. ``discord_workers`` handles
HTTP application-command interactions and deliberately does not import ``discord.py`` or
``aiohttp``. It does not provide a persistent Gateway connection, voice, or a general Discord
REST client. See the `Workers guide <docs/workers.rst>`__ for its runtime and API limits.

Key Features
-------------

- Modern Pythonic API using ``async`` and ``await``.
- Proper rate limit handling.
- Optimised in both speed and memory.

Installing
----------

**Python 3.8 or higher is required for the upstream ``discord`` package.** A
`virtual environment <https://docs.python.org/3/library/venv.html>`__ is recommended.

To install this fork from source on a regular Python runtime:

.. code:: sh

    git clone https://github.com/undivisible/discord.py-workers.git
    cd discord.py-workers
    python -m pip install .

For the upstream client's optional voice dependencies, run ``python -m pip install ".[voice]"``.
Cloudflare Workers use the ``discord_workers`` package and Cloudflare's Python runtime; follow
the `Workers guide <docs/workers.rst>`__ rather than importing the Gateway client there.


Optional Packages
~~~~~~~~~~~~~~~~~~

* `PyNaCl <https://pypi.org/project/PyNaCl/>`__ (for voice support)

Please note that when installing voice support on Linux, you must install the following packages via your favourite package manager (e.g. ``apt``, ``dnf``, etc) before running the above commands:

* libffi-dev (or ``libffi-devel`` on some systems)
* python-dev (e.g. ``python3.8-dev`` for Python 3.8)

Quick Example
--------------

.. code:: py

    import discord

    class MyClient(discord.Client):
        async def on_ready(self):
            print('Logged on as', self.user)

        async def on_message(self, message):
            # don't respond to ourselves
            if message.author == self.user:
                return

            if message.content == 'ping':
                await message.channel.send('pong')

    intents = discord.Intents.default()
    intents.message_content = True
    client = MyClient(intents=intents)
    client.run('token')

Bot Example
~~~~~~~~~~~~~

.. code:: py

    import discord
    from discord.ext import commands

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix='>', intents=intents)

    @bot.command()
    async def ping(ctx):
        await ctx.send('pong')

    bot.run('token')

You can find more examples in the examples directory.

Links
------

- `Documentation <https://discordpy.readthedocs.io/en/latest/index.html>`_
- `Cloudflare Workers guide <docs/workers.rst>`__
- `This fork on GitHub <https://github.com/undivisible/discord.py-workers>`__
- `Official Discord Server <https://discord.gg/r3sSKJJ>`_
- `Discord API <https://discord.gg/discord-api>`_
