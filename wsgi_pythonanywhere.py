# +-----------------------------------------------------------------------+
# | WSGI Configuration Template untuk PythonAnywhere                      |
# +-----------------------------------------------------------------------+
import sys
import os

# Ganti 'USERNAME' dengan username akun PythonAnywhere Anda
USERNAME = os.environ.get("USER", "USERNAME")
project_home = f'/home/{USERNAME}/finance-kepin'

if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Muat environment variable dari .env
from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, '.env'))

# Set flag agar bot berjalan via Webhook efisien di cloud
os.environ["USE_WEBHOOK"] = "true"

from app import app as application
