import os
import sys
from PIL import Image

# Add root to sys.path to import x_uploader
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import x_uploader

def create_dummy_image(path):
    img = Image.new('RGB', (100, 100), color = 'red')
    img.save(path)

def test_x_api():
    test_image_path = "test_x_image.png"
    create_dummy_image(test_image_path)
    
    print("Testing Image Upload (v1.1)...")
    media_id = x_uploader.upload_image_to_x(test_image_path)
    
    if media_id:
        print(f"Success! Media ID: {media_id}")
        print("Testing Tweet Post (v2) with Media...")
        success = x_uploader.post_tweet(
            text="Probando conexión de API para @Stunning_Rev (Generado automáticamente) 🚀",
            media_id=media_id
        )
        if success:
            print("Tweet posted successfully!")
        else:
            print("Failed to post tweet.")
    else:
        print("Failed to upload image.")
        
    if os.path.exists(test_image_path):
        os.remove(test_image_path)

if __name__ == "__main__":
    test_x_api()
