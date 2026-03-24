# Diogo2 Branch

# Bristol Regional Food Network

## DESD Group Project – Django + Docker

## 🧪 Development

This section explains how to set up and run the project in the development environment.

All team members must follow this setup to ensure consistency.

---

## 📦 Tech Stack

- **Django** (Backend)
- **PostgreSQL** (Database)
- **Docker & Docker Compose**
- **Git** (Feature-branch workflow)

---

## 📁 Project Structure

```bash
repo/
│
├── backend/               # Django application
│ ├── manage.py
│ ├── config/              # Project configuration (settings, urls, wsgi)
│ ├── accounts/
│ ├── catalog/
│ ├── cart/
│ ├── orders/
│ ├── payments/
│ └── community/
│
├── docker-compose.yml
├── .env.example
└── README.md
```

### Structure Explanation

- `backend/` → Entire Django web application  
- `config/` → Global configuration (settings, routing)  
- Feature modules are separated into individual Django apps to reduce merge conflicts  

---

## 🌿 Git Workflow

We use the following branch strategy:

- `main` → Final stable version (submission-ready)
- `develop` → Integration branch
- `feature/<feature-name>` → Individual feature branches

### Rules

- Do **not** push directly to `main`
- Do **not** push directly to `develop`
- Always branch from `develop`
- Merge changes via Pull Request

---

## 🚀 First-Time Setup

### 1️⃣ Clone the repository

```bash
git clone <repo-url>
cd <repo-name> 
```

### 2️⃣ Switch to develop branch

```bash
git checkout develop
git pull origin develop
```
## 🔐 Environment Configuration

You will receive a .env file separately.
Place the .env file in the project root (same level as docker-compose.yml).

## ⚠️ Do NOT commit the .env file.

---

## 🐳 Running the Development Environment

Make sure Docker Desktop is running.
From the project root:
```bash
docker compose up --build
```

In a new terminal:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Access:
 - Application → http://localhost:8000
 - Admin Panel → http://localhost:8000/admin

## 🔄 Live Development Mode

The Docker setup includes:

```yaml
volumes:
  - ./backend:/app 
```

This means:
 - Local code changes are reflected immediately inside the container
 - Django automatically reloads on file changes
 - No rebuild is required for normal development
If you update dependencies (requirements.txt), rebuild the containers:

```bash
docker compose up --build
```

## 🛠 Working on a Feature

### Step 1 – Pull latest develop

```bash
git checkout develop
git pull origin develop
```

### Step 2 – Create a feature branch

```bash
git checkout -b feature/<your-feature-name>
```

### Step 3 – Develop inside your assigned app

### Step 4 – Commit and push

```bash
git add .
git commit -m "feat: short description"
git push -u origin feature/<your-feature-name>
```
### Step 5 – Open Pull Request to develop

## ⚠️ Migration Policy

To avoid conflicts:
 - Only one person should generate migrations per app at a time
 - Always pull latest develop before creating migrations
 - Coordinate before modifying shared models

Run migrations using:

```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

## 👥 Suggested App Ownership

To reduce conflicts:
 - Member A → accounts
 - Member B → catalog
 - Member C → cart + orders
 - Member D → payments + community

Each app should have a primary owner responsible for models and migrations.

## 🧹 Resetting the Environment

If something breaks:

```bash
docker compose down
docker compose up --build
```

To reset the database:

```bash
docker compose down -v
docker compose up --build
```

## 📌 Development Rules
 - Do not hardcode secrets in settings.py
 - Do not commit .env
 - Do not modify another member’s app without discussion
 - Keep commits small and meaningful
 - Always work from a feature branch

---
