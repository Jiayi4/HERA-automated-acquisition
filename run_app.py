import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from hera_app.app import main

if __name__ == "__main__":
    main()
