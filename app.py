from flask import (
    Flask, Response, abort, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from werkzeug.security import check_password_hash
from werkzeug.utils import safe_join
import os
import csv
import json
import re
import secrets
import threading
import time
import sqlite3
import smtplib
import ssl
from html import escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import uuid
import subprocess

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
GALLERY_DIR = os.path.join(BASE_DIR, "static", "gallery")
DB_FILE     = os.path.join(BASE_DIR, "gallery.db")

SITE_DATA   = os.path.join(BASE_DIR, "data", "site.json")
HUGO_BIN    = os.environ.get("HUGO_BIN", "/usr/bin/hugo")
OUTPUT_DIR  = os.environ.get("SITE_OUTPUT_DIR", "/var/www/html")

# Gmail credentials — set as environment variables on the server, never hardcode.
#   export GMAIL_USER="yourgmail@gmail.com"
#   export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
#   export CONTACT_RECIPIENT="karinelson@gmail.com"
GMAIL_USER        = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
CONTACT_RECIPIENT  = os.environ.get("CONTACT_RECIPIENT", GMAIL_USER)

app = Flask(__name__, static_folder="admin_static", static_url_path="/_admin/assets")
app.config.update(
    MAX_CONTENT_LENGTH=60 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("ADMIN_HTTPS_ONLY") == "1",
)

publish_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def export_csv():
    """Re-export the database to gallery.csv so Hugo can rebuild."""
    csv_file = os.path.join(BASE_DIR, "assets", "gallery.csv")
    artworks = load_artworks()
    fields = ["filename", "title", "date", "description", "category", "artist_statement"]
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(artworks)



def get_db():
    """Open a database connection with row_factory so rows act like dicts."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_setting(key):
    with get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS admin_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute("SELECT value FROM admin_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key, value):
    get_setting(key)  # makes sure the table exists
    with get_db() as conn:
        conn.execute(
            "INSERT INTO admin_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def session_secret():
    """FLASK_SECRET if set, otherwise a random key generated once and kept in the database."""
    env_value = os.environ.get("FLASK_SECRET", "")
    if env_value and env_value != "change-me-in-production":
        return env_value
    stored = get_setting("flask_secret")
    if not stored:
        stored = secrets.token_hex(32)
        set_setting("flask_secret", stored)
    return stored


app.secret_key = session_secret()


def load_artworks():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM artworks ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_artwork(filename):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM artworks WHERE filename = ?", (filename,)
        ).fetchone()
    return dict(row) if row else None


def insert_artwork(artwork):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO artworks (filename, title, date, description, category, artist_statement)
            VALUES (:filename, :title, :date, :description, :category, :artist_statement)
        """, artwork)
        conn.commit()


def update_artwork(artwork):
    with get_db() as conn:
        conn.execute("""
            UPDATE artworks
               SET filename         = :filename,
                   title            = :title,
                   date             = :date,
                   description      = :description,
                   category         = :category,
                   artist_statement = :artist_statement
             WHERE filename = :original_filename
        """, artwork)
        conn.commit()


def delete_artwork(filename):
    with get_db() as conn:
        conn.execute("DELETE FROM artworks WHERE filename = ?", (filename,))
        conn.commit()


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
def read_site_text():
    if os.path.exists(SITE_DATA):
        with open(SITE_DATA, encoding="utf-8") as f:
            return json.load(f)
    return {}


def write_site_text(values):
    os.makedirs(os.path.dirname(SITE_DATA), exist_ok=True)
    tmp = SITE_DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, SITE_DATA)


def rebuild_site():
    """Rebuild the public site. Returns True if it worked."""
    try:
        subprocess.run(
            [HUGO_BIN, "-s", BASE_DIR, "-d", OUTPUT_DIR, "--cleanDestinationDir"],
            check=True, capture_output=True, text=True, timeout=900,
            env={**os.environ, "HUGO_NUMWORKERMULTIPLIER": "1"},
        )
        return True
    except (subprocess.SubprocessError, OSError) as e:
        print("Error rebuilding Hugo site:", e, getattr(e, "stderr", ""))
        return False


IMAGE_SIGNATURES = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF8", "gif"))


def image_extension(file):
    """Work out the real image type from the file's contents. None if it isn't one we accept."""
    head = file.stream.read(16)
    file.stream.seek(0)
    for signature, ext in IMAGE_SIGNATURES:
        if head.startswith(signature):
            return ext
    return None


def save_image(file, ext):
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
    file.save(os.path.join(GALLERY_DIR, filename))
    return filename


def contact_recipient():
    """Where contact form messages go: the editor's setting, else the server default."""
    return get_setting("contact_recipient") or CONTACT_RECIPIENT


def send_contact_email(sender_name, sender_email, phone, message_body):
    recipient = contact_recipient()
    if not GMAIL_USER or not GMAIL_APP_PASSWORD or not recipient:
        raise RuntimeError("Email isn't configured. Set GMAIL_USER and GMAIL_APP_PASSWORD.")

    msg = MIMEMultipart("alternative")
    msg["Subject"]  = f"New message from {sender_name} — Kari Nelson Art"
    msg["From"]     = GMAIL_USER
    msg["To"]       = recipient
    msg["Reply-To"] = sender_email

    phone_line = f"Phone:   {phone}\n" if phone else ""
    plain = (
        f"Name:    {sender_name}\n"
        f"Email:   {sender_email}\n"
        f"{phone_line}\n"
        f"Message:\n{message_body}"
    )
    safe_name, safe_email, safe_phone = escape(sender_name), escape(sender_email), escape(phone)
    safe_body = escape(message_body).replace(chr(10), "<br>")
    phone_html = f"<p><strong>Phone:</strong> {safe_phone}</p>" if phone else ""
    html = f"""
    <html><body>
      <h2>New contact form submission</h2>
      <p><strong>Name:</strong> {safe_name}</p>
      <p><strong>Email:</strong> <a href="mailto:{safe_email}">{safe_email}</a></p>
      {phone_html}
      <hr>
      <p>{safe_body}</p>
    </body></html>
    """
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, recipient, msg.as_string())


ARTWORK_FIELDS = ("title", "date", "description", "category", "artist_statement")
TEXT_KEY = re.compile(r"^[a-z0-9_]{1,80}$")
SAFE_URL = re.compile(r"^(https?://|mailto:|/|#)", re.I)
NUMBER_LIMITS = {"all_works_columns": (1, 8), "all_works_gap": (0, 80)}
EMAIL_ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


def clean_artwork(data):
    """Keep only the known fields, as trimmed strings."""
    art = {field: str(data.get(field) or "").strip() for field in ARTWORK_FIELDS}
    if not art["date"]:
        art["date"] = datetime.now().strftime("%Y")
    return art


def error(message, status=400):
    return jsonify(ok=False, error=message), status


# ---------------------------------------------------------------------------
# Password protection: everything is locked unless listed here
# ---------------------------------------------------------------------------
PUBLIC_ENDPOINTS = {"login", "contact_submit"}
MAX_FAILURES = 8
FAILURE_WINDOW = 300
login_failures = {}


@app.before_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not session.get("admin"):
        if request.path.startswith("/_admin/api/"):
            return error("You have been signed out. Please sign in again.", 401)
        return redirect(url_for("login"))
    if request.method == "POST":
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
        if not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(403)
    return None


def recent_failures(ip):
    now = time.time()
    failures = [t for t in login_failures.get(ip, []) if now - t < FAILURE_WINDOW]
    login_failures[ip] = failures
    return failures


@app.route("/_admin/login", methods=["GET", "POST"])
def login():
    password_hash = get_setting("admin_password_hash")
    message = None
    if request.method == "POST" and password_hash:
        ip = request.remote_addr
        if len(recent_failures(ip)) >= MAX_FAILURES:
            message = "Too many tries. Please wait a few minutes and try again."
        elif check_password_hash(password_hash, request.form.get("password", "")):
            login_failures.pop(ip, None)
            session.clear()
            session.permanent = True
            session["admin"] = True
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect("/")
        else:
            login_failures[ip].append(time.time())
            message = "That password didn't match. Please try again."
    return render_template("login.html", message=message, ready=bool(password_hash))


@app.route("/_admin/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Editor actions
# ---------------------------------------------------------------------------
@app.route("/_admin/api/publish", methods=["POST"])
def api_publish():
    try:
        changes = json.loads(request.form.get("changes", "{}"))
        text = changes.get("text", {})
        art_changes = changes.get("art", {})
        assert isinstance(text, dict) and isinstance(art_changes, dict)
    except (ValueError, AssertionError, AttributeError):
        return error("Those changes couldn't be read. Please reload and try again.")

    for key, value in text.items():
        if not TEXT_KEY.match(key) or not isinstance(value, str) or len(value) > 20000:
            return error("One of the text changes wasn't valid.")
        if key in NUMBER_LIMITS:
            low, high = NUMBER_LIMITS[key]
            if not value.isdigit() or not low <= int(value) <= high:
                return error("That spacing or row number is out of range.")
        if key.endswith("_url") and value.strip() and not SAFE_URL.match(value.strip()):
            return error("Links need to start with https:// (for example https://facebook.com/yourpage).")

    with publish_lock:
        updates = []
        for filename, data in art_changes.items():
            existing = get_artwork(filename)
            if not existing or not isinstance(data, dict):
                return error("One of those artworks no longer exists. Please reload.")
            art = clean_artwork(data)
            if not art["title"]:
                return error("Every artwork needs a title.")
            upload = request.files.get(data.get("file") or "")
            ext = None
            if upload:
                ext = image_extension(upload)
                if not ext:
                    return error(f"The new image for “{art['title']}” must be a JPG, PNG or GIF.")
            updates.append((filename, art, upload, ext))

        old_files = []
        for filename, art, upload, ext in updates:
            art["original_filename"] = filename
            art["filename"] = filename
            if upload:
                art["filename"] = save_image(upload, ext)
                old_files.append(filename)
            update_artwork(art)

        if text:
            saved = read_site_text()
            saved.update({key: value.strip() for key, value in text.items()})
            write_site_text(saved)

        if updates:
            export_csv()
        if not rebuild_site():
            return error("Your changes were saved, but the website couldn't update..", 500)

        for filename in old_files:
            path = os.path.join(GALLERY_DIR, filename)
            if os.path.exists(path):
                os.remove(path)
    return jsonify(ok=True)


@app.route("/_admin/api/artwork", methods=["POST"])
def api_add_artwork():
    upload = request.files.get("image")
    if not upload:
        return error("Please choose an image first.")
    ext = image_extension(upload)
    if not ext:
        return error("Please choose a JPG, PNG or GIF image.")
    art = clean_artwork(request.form)
    if not art["title"]:
        return error("Please give the artwork a title.")

    with publish_lock:
        art["filename"] = save_image(upload, ext)
        insert_artwork(art)
        export_csv()
        if not rebuild_site():
            return error("The artwork was saved, but the website couldn't update..", 500)
    return jsonify(ok=True, filename=art["filename"])


@app.route("/_admin/api/artwork/delete", methods=["POST"])
def api_delete_artwork():
    filename = request.form.get("filename", "")
    if not get_artwork(filename):
        return error("That artwork no longer exists. Please reload.", 404)

    with publish_lock:
        delete_artwork(filename)
        path = os.path.join(GALLERY_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
        export_csv()
        if not rebuild_site():
            return error("The artwork was removed, but the website couldn't update..", 500)
    return jsonify(ok=True)


@app.route("/_admin/api/contact-recipient", methods=["POST"])
def api_contact_recipient():
    address = request.form.get("email", "").strip()
    if not EMAIL_ADDRESS.match(address) or len(address) > 254:
        return error("Please enter one complete email address.")
    set_setting("contact_recipient", address)
    if request.form.get("test") != "1":
        return jsonify(ok=True)
    try:
        send_contact_email("Website test", GMAIL_USER or address, "", "This is a test from your website's contact form. It's working!")
    except RuntimeError:
        return error("Saved, but the server's email account isn't set up yet, so messages can't be sent.", 500)
    except (smtplib.SMTPException, OSError) as e:
        print("Contact test email error:", e)
        return error("Saved, but the test email couldn't be sent. The server's email login may need fixing.", 500)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# The editor: the real built site, plus the editing tools
# ---------------------------------------------------------------------------
def asset_version(name):
    return int(os.path.getmtime(os.path.join(app.static_folder, name)))


def editor_tags():
    config = json.dumps({
        "csrf": session["csrf"], "saved": read_site_text(), "recipient": contact_recipient(),
    }).replace("<", "\\u003c")
    return (
        f'<link rel="stylesheet" href="/_admin/assets/editor.css?v={asset_version("editor.css")}">'
        f"<script>window.KN_ADMIN = {config};</script>"
        f'<script src="/_admin/assets/editor.js?v={asset_version("editor.js")}"></script>'
    )


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def site_page(path):
    full = safe_join(OUTPUT_DIR, path)
    if full is None:
        abort(404)
    if os.path.isdir(full):
        if path and not path.endswith("/"):
            return redirect("/" + path + "/")
        path = os.path.join(path, "index.html")
        full = os.path.join(full, "index.html")
    if not os.path.isfile(full):
        abort(404)
    if not full.endswith(".html"):
        return send_from_directory(OUTPUT_DIR, path)

    with open(full, encoding="utf-8") as f:
        page = f.read()
    head, marker, tail = page.rpartition("</body>")
    page = head + editor_tags() + marker + tail if marker else page + editor_tags()
    return Response(page, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.errorhandler(413)
def too_large(_):
    return error("That image is too large. Please use one under 60 MB.", 413)


# ---------------------------------------------------------------------------
# Public contact form endpoint
# ---------------------------------------------------------------------------
@app.route("/contact-submit", methods=["POST"])
def contact_submit():
    if request.form.get("website"):  # hidden field only spam bots fill in
        return redirect("/thank-you/")

    name    = " ".join(request.form.get("name", "").split())[:200]
    email   = request.form.get("email", "").strip()
    phone   = " ".join(request.form.get("phone", "").split())[:40]
    message = request.form.get("message", "").strip()[:10000]

    if not name or not message or not EMAIL_ADDRESS.match(email) or len(email) > 254:
        return redirect("/contact/?error=missing-fields")

    try:
        send_contact_email(name, email, phone, message)
        return redirect("/thank-you/")
    except Exception as e:
        print("Contact email error:", e)
        return redirect("/contact/?error=send-failed")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(
        host=os.environ.get("ADMIN_HOST", "0.0.0.0"),
        port=int(os.environ.get("ADMIN_PORT", "5000")),
        threaded=True,
    )
