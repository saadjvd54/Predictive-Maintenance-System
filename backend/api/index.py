import os
import sys

# Ensure backend root directory is on the Python path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import create_app

# Instantiate the Flask WSGI application instance.
# Defaults to 'staging' for cloud pre-production if FLASK_ENV is not explicitly set.
app = create_app(os.getenv("FLASK_ENV", "staging"))

if __name__ == "__main__":
    app.run(debug=True)

