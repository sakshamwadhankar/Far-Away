import argparse

import uvicorn

from komvos.api.main import app


def main():
    parser = argparse.ArgumentParser(description="Komvos API server")
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Host IP to bind to"
    )
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args, unknown = parser.parse_known_args()

    # Pass the app object directly to avoid issues with string resolution in PyInstaller
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    # Workaround for multiprocessing in PyInstaller if needed
    import multiprocessing

    multiprocessing.freeze_support()
    main()
