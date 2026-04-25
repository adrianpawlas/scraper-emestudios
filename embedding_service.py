import torch
import numpy as np
from PIL import Image
from transformers import AutoProcessor, AutoModel
import httpx
from io import BytesIO
from config import EMBEDDING_MODEL, EMBEDDING_DIMENSION


class EmbeddingService:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = AutoProcessor.from_pretrained(EMBEDDING_MODEL)
        self.model = AutoModel.from_pretrained(EMBEDDING_MODEL)
        self.model.to(self.device)
        self.model.eval()
        print(f"EmbeddingService initialized with {EMBEDDING_MODEL} on {self.device}")

    def load_image_from_url(self, url: str) -> Image.Image:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGB")

    def get_image_embedding(self, image_url: str) -> list:
        try:
            image = self.load_image_from_url(image_url)
            inputs = self.processor(images=image, return_tensors="pt")
            
            if 'pixel_values' not in inputs:
                return [0.0] * EMBEDDING_DIMENSION
                
            pixel_values = inputs['pixel_values'].to(self.device)
            
            with torch.no_grad():
                outputs = self.model.vision_model(pixel_values=pixel_values)
                pooled = outputs.last_hidden_state[:, 0]
                embedding = pooled.cpu().numpy().flatten()

            if len(embedding) > EMBEDDING_DIMENSION:
                embedding = embedding[:EMBEDDING_DIMENSION]
            elif len(embedding) < EMBEDDING_DIMENSION:
                embedding = np.pad(embedding, (0, EMBEDDING_DIMENSION - len(embedding)))

            return embedding.tolist()
        except Exception as e:
            print(f"Error getting image embedding from {image_url}: {e}")
            return [0.0] * EMBEDDING_DIMENSION

    def get_text_embedding(self, text: str) -> list:
        try:
            text = text[:500] if len(text) > 500 else text
            
            inputs = self.processor(text=text, return_tensors="pt", padding=True, truncation=True, max_length=128)
            
            if 'input_ids' not in inputs:
                return [0.0] * EMBEDDING_DIMENSION
                
            input_ids = inputs['input_ids'].to(self.device)
            attention_mask = inputs.get('attention_mask', torch.ones_like(input_ids)).to(self.device)

            with torch.no_grad():
                outputs = self.model.text_model(input_ids=input_ids, attention_mask=attention_mask)
                pooled = outputs.last_hidden_state[:, 0]
                embedding = pooled.cpu().numpy().flatten()

            if len(embedding) > EMBEDDING_DIMENSION:
                embedding = embedding[:EMBEDDING_DIMENSION]
            elif len(embedding) < EMBEDDING_DIMENSION:
                embedding = np.pad(embedding, (0, EMBEDDING_DIMENSION - len(embedding)))

            return embedding.tolist()
        except Exception as e:
            print(f"Error getting text embedding: {e}")
            return [0.0] * EMBEDDING_DIMENSION