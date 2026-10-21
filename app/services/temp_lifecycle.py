import os
import shutil
import time
import structlog
from app.core.config import settings
from app.models.job import ProcessingJob

logger = structlog.get_logger(__name__)

class DiskSpaceError(Exception):
    pass

class TempLifecycleService:
    @classmethod
    def get_base_dir(cls) -> str:
        base_dir = getattr(settings, 'YOUTUBE_MEDIA_TEMP_DIR', './tmp/lecture-notes')
        os.makedirs(base_dir, exist_ok=True)
        return base_dir

    @classmethod
    def create_job_dir(cls, job_id: str) -> str:
        base = cls.get_base_dir()
        job_dir = os.path.join(base, str(job_id))
        
        os.makedirs(os.path.join(job_dir, "video"), exist_ok=True)
        os.makedirs(os.path.join(job_dir, "audio"), exist_ok=True)
        os.makedirs(os.path.join(job_dir, "frames"), exist_ok=True)
        os.makedirs(os.path.join(job_dir, "intermediate"), exist_ok=True)
        
        return job_dir

    @classmethod
    def cleanup_job_dir(cls, job_id: str) -> None:
        job_dir = os.path.join(cls.get_base_dir(), str(job_id))
        if os.path.exists(job_dir):
            try:
                shutil.rmtree(job_dir)
                logger.info("Cleaned up job temp directory", job_id=str(job_id))
            except Exception as e:
                logger.warning("Failed to clean up job temp directory", job_id=str(job_id), error=str(e))

    @classmethod
    def cleanup_stale_dirs(cls, db_session) -> None:
        base = cls.get_base_dir()
        if not os.path.exists(base):
            return
            
        retention_minutes = getattr(settings, 'TEMP_FILE_RETENTION_MINUTES', 120)
        cutoff_time = time.time() - (retention_minutes * 60)
        
        for entry in os.listdir(base):
            dir_path = os.path.join(base, entry)
            if not os.path.isdir(dir_path):
                continue
                
            try:
                # Treat the directory name as job_id
                job = db_session.query(ProcessingJob).filter(ProcessingJob.id == entry).first()
                
                # Active jobs are IMMUNE to age-based deletion
                if job and job.status in ["queued", "processing"]:
                    continue
                    
                # For non-active jobs or directories not mapping to any job, check age
                mtime = os.path.getmtime(dir_path)
                if mtime < cutoff_time:
                    shutil.rmtree(dir_path)
                    logger.info("Cleaned up stale temp directory", dir_name=entry, age_hours=round((time.time()-mtime)/3600, 1))
            except Exception as e:
                logger.warning("Failed during stale directory cleanup", dir_name=entry, error=str(e))

    @classmethod
    def check_app_storage(cls) -> None:
        """Checks if aggregate temp directory size exceeds MAX_TEMP_STORAGE_GB."""
        base = cls.get_base_dir()
        if not os.path.exists(base):
            return
            
        total_size = 0
        for dirpath, _, filenames in os.walk(base):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
                    
        total_gb = total_size / (1024 ** 3)
        max_gb = getattr(settings, 'MAX_TEMP_STORAGE_GB', 10.0)
        
        if total_gb > max_gb:
            raise DiskSpaceError(f"App temp storage usage ({total_gb:.2f} GB) exceeds limit ({max_gb} GB)")

    @classmethod
    def check_machine_disk(cls) -> None:
        """Checks if machine has minimum free disk space available."""
        base = cls.get_base_dir()
        min_free_gb = getattr(settings, 'MIN_FREE_DISK_GB', 5.0)
        
        total, used, free = shutil.disk_usage(base)
        free_gb = free / (1024 ** 3)
        
        if free_gb < min_free_gb:
            raise DiskSpaceError(f"Insufficient machine disk space. Free: {free_gb:.2f} GB, Required: {min_free_gb} GB")
