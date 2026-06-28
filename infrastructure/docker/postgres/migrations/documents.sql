-- Run against the rag schema. Adds the column the new file storage layer
-- writes to (app/services/storage/file_storage.py).
ALTER TABLE rag.documents ADD COLUMN IF NOT EXISTS file_path VARCHAR(1000);