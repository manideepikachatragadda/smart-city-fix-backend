from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base

from routers import auth, users, complaints, dashboard, admin, notifications


@asynccontextmanager
async def lifespan(app: FastAPI):
    # This block runs exactly once when the server boots up
    async with engine.begin() as conn:
        # We use run_sync to safely execute the synchronous table creation inside our async loop
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Anything after 'yield' runs when the server shuts down (e.g., closing connections)
    await engine.dispose()


app = FastAPI(
    title="Smart Public Service Feedback API", 
    version="2.0",
    lifespan=lifespan  # Hook the lifespan manager into app
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(complaints.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(notifications.router)

@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "healthy", "service": "Smart Feedback API"}