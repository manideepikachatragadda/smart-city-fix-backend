# 🏙️ SmartCity Fix - Backend API

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon_Serverless-336791.svg)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0_Async-red.svg)

SmartCity Fix is a next-generation, AI-powered civic issue tracking system. This high-performance asynchronous REST API handles everything from citizen complaint ingestion and AI triage to worker assignment, media management, and automated SLA escalations.

## ✨ Key Features

- **⚡ Fully Asynchronous:** Built on FastAPI and SQLAlchemy 2.0 utilizing the `asyncpg` driver for blazing-fast, non-blocking database operations.
- **🧠 AI-Powered Triage:** Automatically analyzes citizen descriptions to determine the correct department, calculate priority scores, and assign strict SLA deadlines.
- **🎯 Smart Auto-Assignment:** Geolocation and department-aware logic routes new tickets to the most appropriate active city worker.
- **📧 Professional Communications:** Beautiful, responsive HTML email templates (Receipts, Alerts, OTPs, Resolutions) powered by a non-blocking `aiosmtplib` background queue.
- **📱 Multi-Channel Notifications:** Integrated push notifications and email alerts keep Workers and Managers perfectly synchronized.
- **☁️ Cloud Media Management:** Seamless integration with Cloudinary for handling citizen submission photos and worker resolution proofs via background tasks.
- **⏱️ SLA Escalation Engine:** Automated cron-ready endpoints to flag breached SLAs and alert city administrators.

---

## 🏗️ System Architecture

The following diagram illustrates the lifecycle of a SmartCity Fix report, from submission to final citizen feedback.

```mermaid
flowchart TD
    %% Define Styles
    classDef user fill:#3b82f6,stroke:#2563eb,stroke-width:2px,color:#fff;
    classDef api fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff;
    classDef db fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#fff;
    classDef external fill:#6366f1,stroke:#4f46e5,stroke-width:2px,color:#fff;

    %% Actors
    Citizen((Citizen)):::user
    Worker((City Worker)):::user
    Manager((Department Manager)):::user

    %% Core System
    API[FastAPI Backend]:::api
    DB[(Neon PostgreSQL)]:::db

    %% External Services
    AI[AI NLP Engine]:::external
    Cloudinary[Cloudinary CDN]:::external
    SMTP[Email Server]:::external

    %% The Flow
    Citizen -->|1. Submits form + Photo| API
    API -->|2. Analyzes Text| AI
    AI -->|Returns Category & SLA| API

    API -->|3. Saves Ticket| DB
    API -.->|4. Background Upload| Cloudinary

    API -->|5. Auto-Assigns & Alerts| Worker
    API -.->|6. Sends HTML Receipt| SMTP
    SMTP -.-> Citizen

    Worker -->|7. Submits Fix + Photo| API
    API -->|Updates Status to Resolved| DB

    Manager -->|8. Reviews & Approves| API
    API -.->|9. Sends Resolution Email| SMTP
    SMTP -.->|Contains Feedback Link| Citizen
```

---

## 🛠️ Tech Stack

- **Framework:** FastAPI
- **Database:** PostgreSQL (Hosted on Neon)
- **ORM:** SQLAlchemy 2.0 (Async) & Alembic
- **Authentication:** JWT (JSON Web Tokens) & Passlib (Bcrypt)
- **Media Storage:** Cloudinary
- **Email:** `aiosmtplib` with standard `email.message`

---

## 📂 Project Structure

```text
├── main.py                  # FastAPI application instance & CORS setup
├── database.py              # Async engine, session maker, and pooling config
├── models.py                # SQLAlchemy declarative models
├── config.py                # Pydantic BaseSettings environment validation
├── routers/
│   ├── auth.py              # Login, Registration, OTP generation
│   ├── complaints.py        # Core ticket lifecycle (Submit, Assign, Resolve)
│   ├── dashboard.py         # Analytics and metric aggregations
│   └── users.py             # User management and profile handling
└── utils/
    ├── email_service.py     # Async email sender & HTML template generator
    ├── notifications.py     # Push notification logic
    └── workflow.py          # AI integration and SLA calculators
```

---

## 🚀 Local Development Setup

### 1. Prerequisites

Ensure you have Python 3.12+ installed.

### 2. Clone and Install

```bash
# Clone the repository
git clone https://github.com/yourusername/smartcity-backend.git
cd smartcity-backend

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables

Create a `.env` file in the root directory and populate it with your credentials:

```env
# Database (Ensure you use postgresql+asyncpg://)
DATABASE_URL=postgresql+asyncpg://user:password@ep-cool-cloud.region.aws.neon.tech/dbname

# Security
SECRET_KEY=your_super_secret_jwt_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Email (SMTP)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=465
SENDER_EMAIL=your_city_email@gmail.com
SENDER_PASSWORD=your_app_password
ADMIN_EMAIL=admin@smartcity.gov

# Cloudinary
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# URLs
FRONTEND_URL=http://localhost:3000
```

### 4. Run the Server

```bash
uvicorn main:app --reload
```

API → `http://127.0.0.1:8000`
Docs → `http://127.0.0.1:8000/docs`

---

## ☁️ Deployment Notes

This application relies heavily on **FastAPI Background Tasks** for non-blocking I/O operations (like uploading large images to Cloudinary and dispatching rich HTML emails).

For production deployment, use container-based hosting (**Render**, **Railway**, or **AWS ECS**) instead of serverless platforms. Serverless environments terminate background tasks prematurely, causing failures in uploads and email delivery.

### ⏰ Recommended Cron Setup

To enable automated SLA escalations, trigger this endpoint every hour:

```bash
POST /complaints/trigger-escalations
```

You can use:

- GitHub Actions
- cron-job.org
- Your hosting provider’s scheduler

---

## 📌 Final Note

This backend is designed for **real-world scalability**, **AI-driven automation**, and **production-grade performance**. Plug in a frontend, and you’ve got a full smart governance system.

---
