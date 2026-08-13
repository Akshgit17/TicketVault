import hashlib
import cv2
import numpy as np
import logging

def decode_qr(image_bytes: bytes) -> str:
    """Decode QR code using zxing-cpp with OpenCV fallback."""
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        logging.error("Could not decode image from bytes.")
        raise ValueError("Could not decode image from bytes.")

    # 1. Try using zxingcpp (extremely fast and robust)
    try:
        import zxingcpp
        results = zxingcpp.read_barcodes(img)
        if results:
            for result in results:
                if result.text:
                    return result.text
    except Exception as e:
        logging.warning(f"zxingcpp decoding failed: {e}")

    # Resize image if it's too large to prevent OpenCV from hanging
    h, w = img.shape[:2]
    max_dim = 1024
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # 2. Fallback to OpenCV default QRCodeDetector
    detector = cv2.QRCodeDetector()
    data, bbox, straight_qrcode = detector.detectAndDecode(img)

    # Fallback: try grayscale if color fails
    if not data:
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        data, bbox, straight_qrcode = detector.detectAndDecode(img_gray)

    # Fallback: try detectAndDecodeMulti (OpenCV >= 4.5.2)
    if not data and hasattr(detector, "detectAndDecodeMulti"):
        try:
            retval, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
            if retval and decoded_info:
                data = decoded_info[0]
        except Exception as e:
            logging.error(f"detectAndDecodeMulti failed: {e}")

    if not data:
        logging.error("No QR code detected in image.")
        raise ValueError("No QR code detected in image.")

    return data


def generate_fingerprint(qr_data: str) -> str:
    """SHA-256 of raw QR data — deterministic, collision-resistant."""
    return hashlib.sha256(qr_data.encode("utf-8")).hexdigest()

