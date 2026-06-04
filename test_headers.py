import asyncio
from kosong.chat_provider.openai_common import create_openai_client
import httpx

async def test():
    class DummyTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            print("HEADERS SENT:")
            for k, v in request.headers.items():
                print(f"{k}: {v}")
            return httpx.Response(200, json={"choices": [{"message": {"content": "Hello"}}]})

    client = create_openai_client(
        api_key="fake",
        base_url="http://fake",
        client_kwargs={"http_client": httpx.AsyncClient(transport=DummyTransport()), "default_headers": {"User-Agent": "Claude Code/0.2.29"}}
    )
    
    try:
        await client.chat.completions.create(model="fake", messages=[{"role": "user", "content": "hi"}])
    except Exception as e:
        print("Error:", e)

asyncio.run(test())
