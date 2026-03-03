"""
AWS Lambda function for Serverless AI Image Editing
====================================================
Invokes Amazon Bedrock Titan Image Generator v2 for Inpainting/Outpainting.

Architecture:
  API Gateway (REST) → Lambda (this file) → Amazon Bedrock (Titan Image Generator v2)

This handler is hardened to:
  1. Always return valid CORS headers (even on uncaught exceptions)
  2. Validate the incoming payload before calling Bedrock
  3. Build a Titan v2-compliant JSON schema for INPAINTING and OUTPAINTING
  4. Return clear, structured error messages to the frontend
"""

import json
import logging
import base64
import os
import traceback

import boto3
from botocore.exceptions import ClientError

# ─── Configuration ───────────────────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# IMPORTANT: Titan Image Generator v2 is only available in specific regions
# Supported regions: us-east-1, us-west-2, eu-west-1, ap-southeast-1, ap-northeast-1
# NOT supported in: ap-south-2 (Hyderabad)
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "amazon.titan-image-generator-v2:0")

# CORS headers — attached to EVERY response, including errors
CORS_HEADERS = {
    "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}

bedrock_runtime = boto3.client(
    service_name="bedrock-runtime",
    region_name=BEDROCK_REGION,
)


# ─── Helper: Build a consistent HTTP response ───────────────────────────────
def build_response(status_code: int, body: dict) -> dict:
    """Always includes CORS headers — safe for both success and error paths."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


# ─── Payload Validation ─────────────────────────────────────────────────────
def validate_request(body: dict) -> list[str]:
    """
    Validates the incoming request body from the frontend.
    Expected shape:
    {
        "prompt": { "text": "...", "mode": "INPAINTING" | "OUTPAINTING" },
        "base_image": "<base64 data-url or raw base64>",
        "mask": "<base64 data-url or raw base64>"   # required for INPAINTING
    }
    """
    errors = []

    prompt = body.get("prompt")
    if not prompt or not isinstance(prompt, dict):
        errors.append("'prompt' object is required")
    else:
        if not prompt.get("text", "").strip():
            errors.append("'prompt.text' is required and cannot be empty")
        if prompt.get("mode") not in ("INPAINTING", "OUTPAINTING"):
            errors.append("'prompt.mode' must be 'INPAINTING' or 'OUTPAINTING'")

    if not body.get("base_image"):
        errors.append("'base_image' (base64) is required")

    mode = prompt.get("mode") if prompt else None
    if mode == "INPAINTING" and not body.get("mask"):
        errors.append("'mask' (base64) is required for INPAINTING mode")

    return errors


# ─── Strip data-URL prefix from base64 strings ──────────────────────────────
def strip_data_url(data: str) -> str:
    """
    The frontend sends base64 images as data URLs:
      data:image/png;base64,iVBORw0KGgo...
    Bedrock expects raw base64 without the prefix.
    """
    if data and "," in data:
        return data.split(",", 1)[1]
    return data


# ─── Get image dimensions from base64 ────────────────────────────────────────
def get_image_dimensions(base64_data: str) -> tuple:
    """
    Decode base64 image and get its dimensions from PNG/JPEG headers.
    Returns (width, height) or None if unable to determine.
    """
    try:
        import struct
        
        # Decode base64 to bytes
        image_bytes = base64.b64decode(base64_data)
        
        # Check PNG signature
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            # PNG: width and height are at bytes 16-24 in IHDR chunk
            width = struct.unpack('>I', image_bytes[16:20])[0]
            height = struct.unpack('>I', image_bytes[20:24])[0]
        # Check JPEG signature
        elif image_bytes[:2] == b'\xff\xd8':
            # JPEG: need to find SOF0 marker
            i = 2
            while i < len(image_bytes) - 9:
                if image_bytes[i] == 0xFF:
                    marker = image_bytes[i + 1]
                    if marker in (0xC0, 0xC1, 0xC2):  # SOF markers
                        height = struct.unpack('>H', image_bytes[i + 5:i + 7])[0]
                        width = struct.unpack('>H', image_bytes[i + 7:i + 9])[0]
                        break
                    elif marker == 0xD9:  # EOI
                        break
                    else:
                        # Skip to next marker
                        length = struct.unpack('>H', image_bytes[i + 2:i + 4])[0]
                        i += 2 + length
                else:
                    i += 1
            else:
                return None
        else:
            logger.warning("Unknown image format")
            return None
        
        # Titan requires dimensions to be multiples of 64 and within limits
        # Min: 256, Max: 1408
        orig_width, orig_height = width, height
        width = max(256, min(1408, (width // 64) * 64))
        height = max(256, min(1408, (height // 64) * 64))
        
        logger.info(f"Original image: {orig_width}x{orig_height}, adjusted to: {width}x{height}")
        return (width, height)
        
    except Exception as e:
        logger.warning(f"Could not determine image dimensions: {e}")
        return None


# ─── Build Titan v2 Request Body ────────────────────────────────────────────
def prepare_titan_request(body: dict) -> dict:
    """
    Builds a Bedrock Titan Image Generator v2 compliant request.

    ┌─────────────────────────────────────────────────────────────────────┐
    │  Titan v2 INPAINTING Schema                                       │
    │  https://docs.aws.amazon.com/bedrock/latest/userguide/            │
    │         model-parameters-titan-image.html                         │
    │                                                                   │
    │  {                                                                │
    │    "taskType": "INPAINTING",                                      │
    │    "inPaintingParams": {                                          │
    │      "text": "prompt text",                                       │
    │      "negativeText": "optional negative prompt",                  │
    │      "image": "<base64 raw>",                                     │
    │      "maskPrompt": "text-based mask" OR "maskImage": "<base64>",  │
    │    },                                                             │
    │    "imageGenerationConfig": {                                     │
    │      "numberOfImages": 1,                                         │
    │      "height": 512,                                               │
    │      "width": 512,                                                │
    │      "cfgScale": 8.0                                              │
    │    }                                                              │
    │  }                                                                │
    │                                                                   │
    │  OUTPAINTING uses "outPaintingParams" with the same fields        │
    │  plus optional "outPaintingMode": "DEFAULT" | "PRECISE"           │
    └─────────────────────────────────────────────────────────────────────┘
    """
    mode = body["prompt"]["mode"]  # "INPAINTING" or "OUTPAINTING"
    prompt_text = body["prompt"]["text"]
    base_image = strip_data_url(body["base_image"])
    mask_image = strip_data_url(body.get("mask", "")) if body.get("mask") else None

    # Get actual image dimensions (or use defaults if unable to detect)
    dimensions = get_image_dimensions(base_image)
    if dimensions:
        width, height = dimensions
    else:
        width, height = 512, 512
        logger.warning("Using default dimensions 512x512")
    
    logger.info(f"Using dimensions: {width}x{height} for Titan request")

    # --- Image generation config (shared) ---
    image_generation_config = {
        "numberOfImages": int(body.get("numberOfImages", 1)),
        "height": height,
        "width": width,
        "cfgScale": float(body.get("cfgScale", 8.0)),
    }

    if mode == "INPAINTING":
        titan_body = {
            "taskType": "INPAINTING",
            "inPaintingParams": {
                "text": prompt_text,
                "image": base_image,
            },
            "imageGenerationConfig": image_generation_config,
        }
        # Use maskImage (binary mask from user drawing), not maskPrompt
        if mask_image:
            titan_body["inPaintingParams"]["maskImage"] = mask_image

    elif mode == "OUTPAINTING":
        titan_body = {
            "taskType": "OUTPAINTING",
            "outPaintingParams": {
                "text": prompt_text,
                "image": base_image,
                "outPaintingMode": "DEFAULT",
            },
            "imageGenerationConfig": image_generation_config,
        }
        if mask_image:
            titan_body["outPaintingParams"]["maskImage"] = mask_image

    else:
        raise ValueError(f"Unsupported mode: {mode}")

    return titan_body


# ─── Lambda Handler ──────────────────────────────────────────────────────────
def lambda_handler(event, context):
    """
    HARDENED handler — every code path returns CORS headers.

    Success response shape (what the frontend expects):
    {
        "images": ["<base64_image_1>", "<base64_image_2>", ...]
    }

    Error response shape:
    {
        "error": "Human-readable error message",
        "code": "ERROR_CODE",
        "images": []          # ← Safe fallback so frontend never crashes
    }
    """
    try:
        # ── Handle CORS preflight (OPTIONS) ──
        http_method = event.get("httpMethod", "")
        if http_method == "OPTIONS":
            return build_response(200, {"message": "CORS preflight OK"})

        # ── Parse request body ──
        raw_body = event.get("body", "{}")
        if isinstance(raw_body, str):
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in request body: {e}")
                return build_response(400, {
                    "error": f"Invalid JSON in request body: {str(e)}",
                    "code": "INVALID_JSON",
                    "images": [],  # Safe fallback
                })
        else:
            body = raw_body  # Already parsed (e.g., Lambda test console)

        logger.info(f"Received request with mode: {body.get('prompt', {}).get('mode')}")

        # ── Validate ──
        validation_errors = validate_request(body)
        if validation_errors:
            logger.warning(f"Validation failed: {validation_errors}")
            return build_response(400, {
                "error": "Validation failed: " + "; ".join(validation_errors),
                "code": "VALIDATION_ERROR",
                "images": [],  # Safe fallback
            })

        # ── Build Titan v2 request ──
        titan_body = prepare_titan_request(body)
        logger.info(f"Calling Bedrock model: {MODEL_ID}")
        logger.info(f"Task type: {titan_body['taskType']}")

        # ── Invoke Bedrock ──
        response = bedrock_runtime.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(titan_body),
        )

        # ── Parse Bedrock response ──
        response_body = json.loads(response["body"].read())
        logger.info(f"Bedrock response keys: {list(response_body.keys())}")

        # Titan v2 returns: { "images": ["<base64>", ...] }
        images = response_body.get("images", [])

        if not images:
            logger.warning("Bedrock returned empty images array")
            # Check if there's an error message from Bedrock
            if "error" in response_body:
                return build_response(502, {
                    "error": f"Bedrock error: {response_body['error']}",
                    "code": "BEDROCK_ERROR",
                    "images": [],
                })
            return build_response(200, {
                "images": [],
                "warning": "Model returned no images. Try a different prompt.",
            })

        logger.info(f"Successfully generated {len(images)} image(s)")
        return build_response(200, {
            "images": images,
        })

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(f"Bedrock ClientError: {error_code} - {error_message}")
        logger.error(traceback.format_exc())

        status_code = 500
        if error_code == "ValidationException":
            status_code = 400
        elif error_code == "AccessDeniedException":
            status_code = 403
        elif error_code == "ThrottlingException":
            status_code = 429
        elif error_code == "ServiceUnavailableException":
            status_code = 503

        return build_response(status_code, {
            "error": f"Bedrock API error: {error_message}",
            "code": error_code,
            "images": [],  # Safe fallback
        })

    except ValueError as e:
        logger.error(f"Value error: {e}")
        return build_response(400, {
            "error": str(e),
            "code": "VALUE_ERROR",
            "images": [],
        })

    except Exception as e:
        # ── CATCH-ALL: guarantees CORS headers even on unexpected errors ──
        logger.error(f"Unhandled exception: {e}")
        logger.error(traceback.format_exc())
        return build_response(500, {
            "error": "Internal server error. Please try again.",
            "code": "INTERNAL_ERROR",
            "images": [],  # Safe fallback — frontend will never crash
        })
