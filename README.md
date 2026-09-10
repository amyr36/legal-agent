Run:
    python app.py        # serves on http://127.0.0.1:8000 (docs at /docs)

Endpoints:
    GET  /health                       -> liveness probe
    POST /analyze                      -> run A -> B comparison, return relations
