"""Start the local API: python run.py   (set RECON_DATA_DIR to point at another dataset folder)."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    # Local demonstration only. Use a production WSGI server for deployment.
    app.run(debug=False)
