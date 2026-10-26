services:
  - type: web
    name: gold-scalper-backend
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn main:app
    plan: free
