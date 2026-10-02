"""Entry point for the heartbeat command line: python -m jarvis.heartbeat_cli"""
import sys
from .heartbeat_cli import main

if __name__ == "__main__":
    sys.exit(main())
