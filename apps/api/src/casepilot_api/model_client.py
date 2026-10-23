"""Close request-local async model clients on the SDK's synchronous event loop."""
import asyncio
import logging
from contextlib import contextmanager


@contextmanager
def managed_model_client(client):
    try:
        yield client
    finally:
        # Runner.run_sync keeps the thread's default loop alive. Reuse it to
        # close pooled connections before their owner is garbage-collected.
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(client.close())
        except Exception:
            logging.getLogger(__name__).warning("model_client_cleanup_failed", exc_info=True)
