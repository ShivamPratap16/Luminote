from fastapi import APIRouter
from app.api.v1.endpoints import health, lectures, jobs, lecture_data

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(lectures.router, prefix="/lectures", tags=["lectures"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(lecture_data.router, prefix="/lectures", tags=["lecture-data"])
