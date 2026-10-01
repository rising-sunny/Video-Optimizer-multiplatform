import os
import json
import logging
from dotenv import load_dotenv
from requests_oauthlib import OAuth1Session

# Set up logging
logger = logging.getLogger("x_uploader")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('[X Uploader] %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

load_dotenv()

# API Keys
CONSUMER_KEY = os.getenv("TWITTER_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("TWITTER_CONSUMER_SECRET")
ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

def get_oauth_session():
    """Returns an authenticated OAuth1Session."""
    if not all([CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
        logger.error("Missing Twitter API keys in .env")
        return None
        
    return OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        resource_owner_key=ACCESS_TOKEN,
        resource_owner_secret=ACCESS_TOKEN_SECRET,
    )

def upload_image_to_x(image_path):
    """
    Uploads an image to X using the v1.1 API and returns the media_id_string.
    """
    oauth = get_oauth_session()
    if not oauth:
        return None
        
    if not os.path.exists(image_path):
        logger.error(f"Image not found: {image_path}")
        return None

    url = "https://upload.twitter.com/1.1/media/upload.json"
    
    logger.info(f"Uploading image to X: {image_path}")
    try:
        with open(image_path, "rb") as image_file:
            files = {"media": image_file}
            response = oauth.post(url, files=files)
            
            if response.status_code == 200:
                media_id = response.json().get("media_id_string")
                logger.info(f"Image uploaded successfully. Media ID: {media_id}")
                return media_id
            else:
                logger.error(f"Failed to upload image. Status: {response.status_code}")
                logger.error(response.text)
                return None
    except Exception as e:
        logger.error(f"Error uploading image: {e}")
        return None

def post_tweet(text, media_id=None):
    """
    Posts a tweet using the v2 API, optionally attaching a media_id.
    """
    oauth = get_oauth_session()
    if not oauth:
        return False
        
    url = "https://api.twitter.com/2/tweets"
    
    payload = {"text": text}
    if media_id:
        payload["media"] = {"media_ids": [media_id]}
        
    logger.info("Posting tweet...")
    try:
        response = oauth.post(url, json=payload)
        
        if response.status_code == 201:
            tweet_data = response.json().get("data", {})
            tweet_id = tweet_data.get("id")
            logger.info(f"Tweet posted successfully! ID: {tweet_id}")
            return True
        else:
            logger.error(f"Failed to post tweet. Status: {response.status_code}")
            logger.error(response.text)
            return False
    except Exception as e:
        logger.error(f"Error posting tweet: {e}")
        return False

if __name__ == "__main__":
    # Test block
    print("This module provides functions to upload to X.")
