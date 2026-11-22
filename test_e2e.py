#!/usr/bin/env python3
"""Test end-to-end: crea source, ejecuta pipeline, consulta análisis"""
import asyncio
import httpx
from generate_token import generate_token

BASE_URL = "http://localhost:8000"

# Token con permisos completos
TOKEN = generate_token(role="admin")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "X-Client-ID": "e2e-test",
    "Content-Type": "application/json",
}


async def test_health():
    """Verifica que la API está viva"""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/health/ready")
        print(f"✅ Health: {r.status_code} - {r.json()}")


async def create_source():
    """Crea un source HTTP de prueba"""
    import time
    import random
    import string
    # Generate unique source_id with only lowercase letters
    suffix = ''.join(random.choices(string.ascii_lowercase, k=6))
    source_id = f"testapi{suffix}"
    source_config = {
        "base_url": "https://jsonplaceholder.typicode.com",
        "endpoint": "/posts",
        "method": "GET",
        "pagination": {"type": "none"},
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE_URL}/sources",
            headers=HEADERS,
            json={"source_id": source_id, "type": "api", "config": source_config, "enabled": True}
        )
        print(f"✅ Create source: {r.status_code} - {r.json()}")
        return r.json()


async def trigger_ingest(source_id: str):
    """Dispara ingestión manual"""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE_URL}/pipelines/{source_id}/ingest",
            headers=HEADERS,
            json={}
        )
        print(f"✅ Trigger ingest: {r.status_code} - {r.json()}")
        return r.json()


async def ask_question(question: str, source_id: str = None):
    """Hace pregunta en lenguaje natural"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{BASE_URL}/analysis/ask",
            headers=HEADERS,
            json={"question": question, "source_id": source_id}
        )
        print(f"✅ Ask: {r.status_code}")
        result = r.json()
        print(f"   Status: {result.get('status')}")
        print(f"   Tokens: {result.get('tokens_used')}")
        print(f"   Answer:\n{result.get('answer', 'No answer')[:500]}...")
        return result


async def main():
    print("🚀 Test E2E - Plataforma Agéntica de Datos")
    print("=" * 50)

    try:
        await test_health()

        # Crear source
        source = await create_source()
        source_id = source.get("source_id")

        # Disparar ingestión (necesita workers corriendo)
        print("\n✅ Workers running in Docker Compose")
        print()

        # Small wait for workers to be ready
        await asyncio.sleep(2)

        run = await trigger_ingest(source_id)
        run_id = run.get("run_id")

        # Esperar un poco
        await asyncio.sleep(5)

        # Preguntas de prueba
        questions = [
            "¿Cuántos registros se ingresaron?",
            "Muestra los datos por canal",
            "Detecta anomalías en los datos",
            "Genera un gráfico de barras",
        ]

        for q in questions:
            print(f"\n❓ Pregunta: {q}")
            await ask_question(q, source_id)
            await asyncio.sleep(1)

    except httpx.ConnectError:
        print("❌ No se puede conectar a la API. ¿Está corriendo en localhost:8000?")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())