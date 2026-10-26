services:
  - type: web
    name: gold-scalper-backend
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python main.py
    plan: free
