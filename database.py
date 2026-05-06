import supabase
import time
import logging
from datetime import datetime
from config import SUPABASE_URL, SUPABASE_KEY, SOURCE

logging.basicConfig(filename='scraper_errors.log', level=logging.ERROR)


class DatabaseService:
    def __init__(self):
        self.client = supabase.create_client(SUPABASE_URL, SUPABASE_KEY)
        self.batch_size = 50
        print("DatabaseService initialized")

    def generate_product_id(self, product_url: str) -> str:
        if "/product/" in product_url:
            url_part = product_url.split("/product/")[-1].split("?")[0]
        else:
            url_part = product_url.split("/")[-1].split("?")[0]
        return f"{SOURCE}-{url_part}"

    def format_additional_images(self, images: list) -> str:
        if not images:
            return None
        return " , ".join(images)

    def format_categories(self, categories: list) -> str:
        if not categories:
            return None
        return ", ".join(categories)

    def prepare_product_data(self, product: dict, is_new: bool = False, image_changed: bool = False) -> dict:
        metadata = product.get("metadata", {})
        
        price = product.get("price")
        sale = product.get("sale")
        
        data = {
            "id": self.generate_product_id(product["product_url"]),
            "source": SOURCE,
            "product_url": product["product_url"],
            "affiliate_url": product.get("affiliate_url"),
            "image_url": product.get("image_url"),
            "brand": product.get("brand", "Eme Studios"),
            "title": product.get("title"),
            "description": product.get("description"),
            "category": product.get("category"),
            "gender": product.get("gender"),
            "metadata": str(metadata) if metadata else None,
            "size": product.get("size"),
            "second_hand": False,
            "price": price,
            "sale": sale,
            "additional_images": self.format_additional_images(product.get("additional_images", [])),
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        if is_new:
            data["created_at"] = datetime.utcnow().isoformat()
        
        if is_new or image_changed:
            data["image_embedding"] = product.get("image_embedding")
            data["info_embedding"] = product.get("info_embedding")
        
        return data

    def get_existing_products(self, product_urls: list[str]) -> dict:
        if not product_urls:
            return {}
        
        all_existing = {}
        chunk_size = 100
        
        for i in range(0, len(product_urls), chunk_size):
            chunk = product_urls[i:i + chunk_size]
            try:
                result = self.client.table("products").select(
                    "id, product_url, title, price, image_url, compressed_image_url, category, metadata, additional_images"
                ).in_("product_url", chunk).execute()
                
                for p in result.data:
                    all_existing[p["product_url"]] = p
            except Exception as e:
                logging.warning(f"Error fetching chunk {i//chunk_size + 1}: {e}")
                continue
        
        return all_existing

    def has_changed(self, existing: dict, new_product: dict) -> bool:
        if not existing:
            return True
        
        existing_title = existing.get("title") or ""
        new_title = new_product.get("title") or ""
        if existing_title != new_title:
            return True
            
        if existing.get("price") != new_product.get("price"):
            return True
        if existing.get("image_url") != new_product.get("image_url"):
            return True
        if existing.get("category") != new_product.get("category"):
            return True
        existing_addl = existing.get("additional_images") or ""
        new_addl = self.format_additional_images(new_product.get("additional_images", [])) or ""
        if existing_addl != new_addl:
            return True
        return False

    def batch_upsert(self, products: list[dict]) -> dict:
        results = {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
        
        for i in range(0, len(products), self.batch_size):
            batch = products[i:i + self.batch_size]
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    batch_data = [p for p in batch if p is not None]
                    if not batch_data:
                        continue
                        
                    result = self.client.table("products").upsert(
                        batch_data, 
                        on_conflict="id",
                        ignore_duplicates=False
                    ).execute()
                    
                    if result.data:
                        results["inserted"] += len([p for p in batch if p.get("_is_new", False)])
                        results["updated"] += len([p for p in batch if not p.get("_is_new", True) and p.get("_changed", False)])
                        results["skipped"] += len([p for p in batch if not p.get("_changed", True) and not p.get("_is_new", True)])
                    break
                    
                except Exception as e:
                    retry_count += 1
                    error_msg = str(e)
                    if retry_count >= max_retries:
                        results["failed"] += len(batch)
                        results["errors"].append(f"Batch {i // self.batch_size + 1} failed: {error_msg}")
                        logging.error(f"Batch insert failed: {error_msg}")
                    else:
                        time.sleep(1 * retry_count)
        
        return results

    def delete_stale_products(self, seen_product_urls: list[str]) -> dict:
        if not seen_product_urls:
            return {"deleted": 0}
        
        try:
            result = self.client.table("products").select("product_url, metadata").eq("source", SOURCE).execute()
            all_products = result.data or []
            
            stale_urls = []
            for p in all_products:
                product_url = p.get("product_url")
                if product_url not in seen_product_urls:
                    meta = p.get("metadata") or {}
                    if isinstance(meta, str):
                        import ast
                        try:
                            meta = ast.literal_eval(meta)
                        except:
                            meta = {}
                    
                    miss_count = meta.get("consecutive_misses", 0) + 1
                    if miss_count >= 2:
                        stale_urls.append(product_url)
                    else:
                        self.client.table("products").update({
                            "metadata": str({**meta, "consecutive_misses": miss_count})
                        }).eq("product_url", product_url).execute()
            
            deleted_count = 0
            for i in range(0, len(stale_urls), 100):
                chunk = stale_urls[i:i + 100]
                if chunk:
                    try:
                        delete_result = self.client.table("products").delete().in_("product_url", chunk).execute()
                        deleted_count += len(chunk)
                    except Exception as e:
                        logging.warning(f"Error deleting stale chunk: {e}")
                        continue
            
            return {"deleted": deleted_count}
            
        except Exception as e:
            logging.error(f"Error deleting stale products: {e}")
            return {"deleted": 0, "error": str(e)}

    def process_products(self, products: list[dict]) -> dict:
        seen_urls = [p["product_url"] for p in products]
        existing_products = self.get_existing_products(seen_urls)
        
        products_to_upsert = []
        
        for product in products:
            product_url = product["product_url"]
            existing = existing_products.get(product_url)
            
            is_new = existing is None
            image_changed = existing and existing.get("image_url") != product.get("image_url")
            changed = self.has_changed(existing, product)
            
            if is_new:
                product["_is_new"] = True
                product["_changed"] = True
                prepared = self.prepare_product_data(product, is_new=True, image_changed=True)
            elif changed:
                product["_is_new"] = False
                product["_changed"] = True
                prepared = self.prepare_product_data(product, is_new=False, image_changed=image_changed)
            else:
                product["_is_new"] = False
                product["_changed"] = False
                prepared = self.prepare_product_data(product, is_new=False, image_changed=False)
            
            products_to_upsert.append(prepared)
        
        insert_results = self.batch_upsert(products_to_upsert)
        
        delete_results = self.delete_stale_products(seen_urls)
        
        return {
            "new": insert_results["inserted"],
            "updated": insert_results["updated"],
            "skipped": insert_results["skipped"],
            "failed": insert_results["failed"],
            "stale_deleted": delete_results.get("deleted", 0),
            "errors": insert_results["errors"]
        }