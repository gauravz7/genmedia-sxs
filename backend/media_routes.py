"""Health check and the authenticated GCS media proxy.

Raw gs:// URLs are never handed to the browser; everything goes through
/api/media, which is also the SSRF choke point."""


from fastapi import (APIRouter, HTTPException,
                     Query, Request)
from fastapi.responses import Response, StreamingResponse

from util.gcs_utils import get_upload_client, https_to_gs

router = APIRouter()


@router.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Project Pulse Backend"}


@router.get("/api/media")
async def get_media_proxy(url: str = Query(...), request: Request = None):

    try:
        # Fix malformed gs:/ URLs (single slash instead of double)
        fixed_url = url
        if fixed_url.startswith("gs:/") and not fixed_url.startswith("gs://"):
            fixed_url = "gs://" + fixed_url[4:]

        gs_uri = https_to_gs(fixed_url)
        # SSRF guard: only proxy Google Cloud Storage objects (gs:// or the
        # GCS HTTPS host). Reject arbitrary hosts so this endpoint can't be
        # used as an open proxy.
        if not gs_uri.startswith("gs://"):
            raise HTTPException(status_code=400, detail="Only GCS URLs are allowed")

        parts = gs_uri.replace("gs://", "").split("/")
        bucket_name = parts[0]
        blob_name = "/".join(parts[1:])

        client = get_upload_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.reload()  # get metadata (size)

        total_size = blob.size
        ct = "image/jpeg"
        url_lower = url.lower()
        if ".png" in url_lower:
            ct = "image/png"
        elif ".mp4" in url_lower:
            ct = "video/mp4"
        elif ".html" in url_lower:
            ct = "text/html"

        # Handle Range requests for video seeking
        range_header = request.headers.get("range") if request else None
        if range_header and total_size:
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else total_size - 1
            end = min(end, total_size - 1)
            length = end - start + 1

            # GCS download_as_bytes end param is exclusive
            data = blob.download_as_bytes(start=start, end=end + 1)
            return Response(
                content=data,
                status_code=206,
                media_type=ct,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(len(data)),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=3600",
                },
            )

        # Stream full file in chunks
        def stream_blob():
            with blob.open("rb") as f:
                while True:
                    chunk = f.read(2 * 1024 * 1024)  # 2MB chunks
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            stream_blob(),
            media_type=ct,
            headers={
                "Content-Length": str(total_size) if total_size else "",
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
            },
        )
    except HTTPException:
        raise  # preserve SSRF-guard 400 and other explicit statuses
    except Exception as e:
        print(f"Error proxying media {url}: {e}")
        raise HTTPException(status_code=404, detail="Failed to load media")
