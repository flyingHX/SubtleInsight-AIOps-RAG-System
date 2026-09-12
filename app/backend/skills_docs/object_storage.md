# Object Storage

## Description
File and media storage integration via ObjectStorage. Covers upload/download presigned URLs, bucket management, database object_key storage pattern, and web-sdk client.storage APIs for managing files, images, and videos.

## Guide

### ObjectStorage Integration
- [Critical] When object information needs to be saved in the database table
  - Generate the object_key of the object
  - Get the upload presigned URL through object_key using web-sdk `client.storage.getUploadUrl({ bucket_name, object_key })` (or use `client.storage.upload(...)`)
  - The frontend uploads the object through the upload presigned URL, and ONLY saves the object_key and visibility(public/private) into the database table, DON't save upload/download presigned URL.
  - An `object_key` stored in a database table is not a preview URL. For previews, resolve it with `client.storage.getDownloadUrl({ bucket_name, object_key })` and use `response.data.download_url`; use `client.storage.download(...)` only for explicit downloads.
- The ObjectStorage implemented inside the `backend/routers/storage.py` and `backend/services/storage.py`. Don't Modify these files.
- Use web-sdk Storage Module `client.storage.*` to call storage APIs. For methods that return an HTTP response wrapper, use `response.data` to access the response body, for example `response.data.download_url`.
- `client.storage.upload(...)` is an exception: it returns the upload result directly. Access it with `response.object_key`, not `response.data.object_key`.
- Strictly follow the route, request and response format of the ObjectStorage API Endpoints
  - Using a download presigned URL through the object_key, open the save file dialog and allow the user to save the file locally
- Before using any `bucket_name` in frontend code or business routers, create the bucket or verify that it already exists as part of setup, then confirm it is usable in the same app context with a `getUploadUrl` / upload-path check or equivalent bucket-read check.
- Keep frontend and backend bucket names consistent for the same feature. If file upload is part of the core requirement, bucket provisioning or verification must appear in `todo.md` / setup steps before the task is considered complete.

#### web-sdk Storage APIs
- Notes: `?` optional; `visibility`: 'public'|'private'; `object_key`: path string; `overwrite_key`: bool overwrite target; `size`: bytes; `*_at/last_modified`: 'YYYY-MM-DD HH:mm:ss'; `etag`: ETag; `file`: browser File; `accept`: input accept
- `createBucket({ bucket_name, visibility })` -> `{ bucket_name, visibility, created_at }`
- `listBuckets()` -> `{ buckets: [{ bucket_name, visibility }] }`
- `listObjects({ bucket_name })` -> `{ objects: [{ object_key, size, last_modified, etag }] }`
- `getObjectInfo({ bucket_name, object_key })` -> `{ object_key, size, last_modified, etag }`
- `renameObject({ bucket_name, source_key, target_key, overwrite_key })` -> `{ success }`
- `getUploadUrl({ bucket_name, object_key })` -> `{ upload_url, expires_at }`
- `getDownloadUrl({ bucket_name, object_key })` -> `{ download_url, expires_at }`
- `upload({ bucket_name, object_key?, file?, accept? })` auto `getUploadUrl` + upload -> `{ bucket_name, file_name, object_key, size }`
- `download({ bucket_name, object_key })` auto `getDownloadUrl` + trigger browser download (returns downloadUrl)
