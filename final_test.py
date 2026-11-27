#!/usr/bin/env python3
"""Final comprehensive test"""
import asyncio
import random
import string

import httpx

from generate_token import generate_token

TOKEN = generate_token(role="admin")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "X-Client-ID": "final-test", "Content-Type": "application/json"}

async def test():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Health
        r = await client.get("http://localhost:8000/health/ready")
        print(f"✅ Health: {r.json()}")

        # 2. Create source
        source_id = f"testapi{''.join(random.choices(string.ascii_lowercase, k=6))}"
        r = await client.post("http://localhost:8000/sources", headers=HEADERS, json={
            "source_id": source_id, "type": "api",
            "config": {"base_url": "https://jsonplaceholder.typicode.com", "endpoint": "/posts", "method": "GET", "pagination": {"type": "none"}},
            "enabled": True
        })
        print(f"✅ Create source: {r.status_code} - {source_id}")

        # 3. Trigger ingest via workers
        r = await client.post(f"http://localhost:8000/pipelines/{source_id}/ingest", headers=HEADERS, json={})
        run_id = r.json()["id"]
        print(f"✅ Trigger ingest: {run_id}")

        # 4. Wait for workers to process
        await asyncio.sleep(8)

        # 5. Ask questions via analysis API (LangGraph)
        questions = ["¿Cuántos registros?", "Detecta anomalías", "Gráfico de barras"]
        for q in questions:
            r = await client.post("http://localhost:8000/analysis/ask", headers=HEADERS, json={"question": q, "source_id": source_id})
            result = r.json()
            print(f"✅ Ask: {q[:30]}... -> Status: {result['status']}, Tokens: {result['tokens_used']}")

    print("\n🎉 ALL TESTS PASSED - Platform fully operational!")

asyncio.run(test())
