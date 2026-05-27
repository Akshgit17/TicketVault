import uuid
from app.database import supabase

BUCKET = "ticket-qrs"


def upload_qr_image(image_bytes: bytes, content_type: str = "image/png") -> str:
    """Upload QR image to Supabase private Storage. Returns storage path."""
    file_name = f"{uuid.uuid4()}.png"
    path = f"qrs/{file_name}"
    supabase.storage.from_(BUCKET).upload(
        path=path,
        file=image_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return path


def get_signed_url(path: str, expires_in: int = 3600) -> str:
    """Generate a temporary signed URL for a QR image (default: 1 hour)."""
    result = supabase.storage.from_(BUCKET).create_signed_url(
        path, expires_in=expires_in
    )
    return result.get("signedURL", "")
