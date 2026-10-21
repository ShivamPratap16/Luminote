#!/usr/bin/env python3
import os
import sys
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.visual_event import VisualEvent
from app.core.config import settings

def main():
    parser = argparse.ArgumentParser(description="Clean up unreferenced frame images.")
    parser.add_argument("--delete", action="store_true", help="Actually delete the files (default is dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        storage_dir = settings.STORAGE_LOCAL_PATH
        if not os.path.exists(storage_dir):
            print(f"Storage directory {storage_dir} does not exist.")
            return

        lectures_dir = os.path.join(storage_dir, "lectures")
        if not os.path.exists(lectures_dir):
            print(f"No lectures directory found at {lectures_dir}.")
            return

        # Fetch all frame_storage_keys that are actually referenced in the DB
        referenced_keys = db.query(VisualEvent.frame_storage_key).filter(VisualEvent.frame_storage_key.isnot(None)).all()
        referenced_keys = {key[0] for key in referenced_keys if key[0]}

        unreferenced_count = 0
        total_size_bytes = 0

        # Walk through storage/lectures/<id>/frames/
        for lecture_id in os.listdir(lectures_dir):
            frames_dir = os.path.join(lectures_dir, lecture_id, "frames")
            if not os.path.exists(frames_dir):
                continue

            for frame_file in os.listdir(frames_dir):
                file_path = os.path.join(frames_dir, frame_file)
                if not os.path.isfile(file_path):
                    continue

                # The key format in the database is typically: lectures/<lecture_id>/frames/<filename>
                key = f"lectures/{lecture_id}/frames/{frame_file}"
                
                if key not in referenced_keys:
                    unreferenced_count += 1
                    size = os.path.getsize(file_path)
                    total_size_bytes += size
                    
                    if args.delete:
                        os.remove(file_path)
                        print(f"DELETED: {key} ({size / 1024:.1f} KB)")
                    else:
                        print(f"DRY-RUN - Would delete: {key} ({size / 1024:.1f} KB)")

        total_mb = total_size_bytes / (1024 * 1024)
        print("-" * 50)
        if args.delete:
            print(f"Cleanup complete. Deleted {unreferenced_count} files recovering {total_mb:.2f} MB.")
        else:
            print(f"Dry-run complete. Found {unreferenced_count} unreferenced files ({total_mb:.2f} MB).")
            print("Run with --delete to permanently remove these files.")

    finally:
        db.close()

if __name__ == "__main__":
    main()
