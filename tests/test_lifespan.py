import asyncio

from conftest import Client


def test_services_start_and_stop_with_server(runtime):
    events = []

    class Service:
        async def start(self):
            events.append("start")

        async def stop(self):
            events.append("stop")

    runtime._background_services.append(Service())
    client = Client(runtime)
    assert client.get("/api/settings").status_code == 200
    assert events == []
    with client:
        assert events == ["start"]
    assert events == ["start", "stop"]


def test_shutdown_cancels_learning(runtime):
    async def scenario():
        async def pending():
            await asyncio.Event().wait()
        runtime.spawn(pending())
        await asyncio.sleep(0)
        await runtime.stop()
        assert not runtime._tasks
    asyncio.run(scenario())
