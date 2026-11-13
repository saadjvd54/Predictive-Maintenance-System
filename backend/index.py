import os
import sys

# Ensure backend root directory is on the Python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import create_app

# Canonical Flask WSGI entrypoint for Vercel
app = create_app(os.getenv("FLASK_ENV", "staging"))

