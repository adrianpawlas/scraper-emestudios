"""Image and text embeddings using SigLIP (768-dim)."""
import io
from typing import List, Optional

import torch
from PIL import Image
from transformers import AutoProcessor, SiglipModel

from config import EMBEDDING_MODEL

_model: Optional[SiglipModel] = None
_processor: Optional[AutoProcessor] = None
_device: Optional[str] = None


def _get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_model():
    global _model, _processor, _device
    if _model is not None:
        return
    _device = _get_device()
    _processor = AutoProcessor.from_pretrained(EMBEDDING_MODEL)
    _model = SiglipModel.from_pretrained(EMBEDDING_MODEL).to(_device)
    _model.eval()


def image_embedding(image: Image.Image) -> List[float]:
    """Return 768-dim embedding for a single image."""
    _load_model()
    inputs = _processor(images=image, return_tensors="pt").to(_device)
    with torch.no_grad():
        feats = _model.get_image_features(**inputs)
    vec = feats[0].float().cpu().numpy()
    return vec.tolist()


def image_embedding_from_url(image_url: str) -> Optional[List[float]]:
    """Download image from URL and return 768-dim embedding, or None on failure."""
    import httpx
    try:
        resp = httpx.get(image_url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        return image_embedding(img)
    except Exception:
        return None


def text_embedding(text: str) -> List[float]:
    """Return 768-dim embedding for text. Uses padding token for empty input."""
    _load_model()
    if not (text or "").strip():
        text = " "
    inputs = _processor(text=[text], return_tensors="pt", padding=True, truncation=True).to(_device)
    with torch.no_grad():
        feats = _model.get_text_features(**inputs)
    vec = feats[0].float().cpu().numpy()
    return vec.tolist()


