"""Set or change the password for the site editor.

Usage (from this folder):  python3 set_admin_password.py
"""
import getpass
import sys

from werkzeug.security import generate_password_hash

from app import set_setting

password = getpass.getpass("New editor password: ")
if len(password) < 8:
    sys.exit("Please use at least 8 characters. Nothing was changed.")
if getpass.getpass("Type it again: ") != password:
    sys.exit("Those didn't match. Nothing was changed.")

set_setting("admin_password_hash", generate_password_hash(password))
print("Password saved.")
