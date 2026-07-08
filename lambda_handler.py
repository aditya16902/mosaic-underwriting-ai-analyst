"""
Lambda entry point for the MosAIc FastAPI backend.

Mangum wraps the FastAPI ASGI app so API Gateway can invoke it as a
Lambda function. Nothing inside the app changes — routes, pipeline,
LLM chain, and agent all work exactly as they do under uvicorn locally.

Local dev: still uses main.py + uvicorn, completely unaffected.
Lambda:    API Gateway → this handler → FastAPI app.
"""
from mangum import Mangum
from backend.api.routes import app

# Mangum translates API Gateway's event/context format into the
# ASGI scope FastAPI expects, and converts FastAPI's response back
# into the dict API Gateway expects in return.
handler = Mangum(app, lifespan="off")
