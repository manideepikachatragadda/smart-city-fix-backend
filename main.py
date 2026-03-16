from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base

from routers import auth, users, complaints, dashboard, admin, notifications

app = FastAPI(title="Smart Public Service Feedback API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create all tables (ensure clean DB if schema changed)
Base.metadata.create_all(bind=engine)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(complaints.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(notifications.router)

@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "healthy", "service": "Smart Feedback API"}
