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


def test_failure_detail_does_not_disclose_provider_body():
    import httpx
    from openai import APIStatusError
    from casepilot_api.model_client import model_failure_detail
    error = APIStatusError('private-token-and-user-content', response=httpx.Response(500,
        request=httpx.Request('POST', 'https://example.invalid/private')), body={'secret': 'private'})
    detail = model_failure_detail(error)
    assert '模型服务暂时不可用' in detail
    assert '未执行' in detail and '原草稿已保留' in detail
    assert 'private' not in detail


def test_error_chain_omits_messages_and_handles_cycles():
    from casepilot_api.model_client import model_error_chain
    inner = OSError('private connection URL')
    outer = RuntimeError('private request content')
    outer.__cause__ = inner
    inner.__context__ = outer
    assert model_error_chain(outer) == 'RuntimeError>OSError'
