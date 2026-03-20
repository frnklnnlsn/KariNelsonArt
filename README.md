# Kari Nelson Art — Gallery Website & Admin System

A self-hosted artist portfolio website built with Hugo, backed by a custom Python/Flask admin interface for managing artwork without touching any code.

## How It Works

The project has two parts that work together:

1. **Hugo static site** — the public-facing gallery website, fast and lightweight
2. **Flask admin app** (`app.py`) — a private web interface for uploading, editing, and deleting artwork

When artwork is added or changed through the admin panel, the app automatically:
- Saves the image to the gallery folder
- Updates a SQLite database
- Re-exports the database to `gallery.csv`
- Triggers a Hugo rebuild to regenerate the live site

## Tech Stack

- **Python / Flask** — admin backend and contact form handling
- **Hugo** — static site generation
- **SQLite** — artwork metadata storage
- **SMTP / Gmail API** — contact form email delivery
- **HTML / CSS / JavaScript** — frontend templates and styling

## Project Structure
```
├── app.py              # Flask admin app (upload, edit, delete, contact)
├── init_db.py          # Database setup script
├── hugo.toml           # Hugo site configuration
├── assets/             # CSS, JS, and generated gallery.csv
├── content/            # Hugo page content (markdown)
├── layouts/            # Custom Hugo HTML templates
├── static/gallery/     # Uploaded artwork images
└── templates/          # Flask HTML templates (admin UI)
```

## Features

- Upload artwork with title, date, description, category, and artist statement
- Edit or replace existing artwork
- Delete artwork (removes image file and database entry)
- Auto-rebuilds the live Hugo site on every change
- Contact form with email notification to the artist

## Setup

1. Install dependencies:
```bash
pip install flask
```

2. Set environment variables:
```bash
export GMAIL_USER="your@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export FLASK_SECRET="your-secret-key"
```

3. Initialize the database:
```bash
python init_db.py
```

4. Run the admin app:
```bash
python app.py
```

The admin panel runs on `http://localhost:5000` and is intended to be kept private (not public-facing).

---

Built for [Kari Nelson](https://karinelsonart.com) — painter and artist.
