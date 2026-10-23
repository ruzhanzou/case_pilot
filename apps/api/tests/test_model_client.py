import asyncio
from unittest.mock import AsyncMock

import pytest

from casepilot_api.model_client import managed_model_client


@pytest.mark.parametrize('fails', [False, True])
def test_request_client_closes_on_same_loop_even_on_failure(fails):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    observed = []
    async def close():
        observed.append(asyncio.get_running_loop())
    client = AsyncMock()
    client.close.side_effect = close
    try:
        if fails:
            with pytest.raises(ValueError), managed_model_client(client):
                raise ValueError('provider unavailable')
        else:
            with managed_model_client(client):
                pass
        client.close.assert_awaited_once()
        assert observed == [loop]
        assert not loop.is_closed()
    finally:
        loop.close()
        asyncio.set_event_loop(None)
