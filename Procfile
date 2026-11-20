# Heroku / Render / Fly style process declaration.
# PORT is supplied by the platform; uvicorn must bind 0.0.0.0 to be reachable.
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers
