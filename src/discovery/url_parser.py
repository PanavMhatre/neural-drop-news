import json
import logging
import subprocess
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.models.schemas import RawStory

logger = logging.getLogger(__name__)

class UrlParser:
    """Parses arbitrary URLs into RawStory objects."""
    
    @staticmethod
    def parse_url(url: str) -> Optional[RawStory]:
        """Determine URL type and parse it."""
        logger.info(f"Parsing direct URL: {url}")
        
        # Check if it's a video/social platform that yt-dlp can handle
        social_domains = ["youtube.com", "youtu.be", "twitter.com", "x.com", "instagram.com", "tiktok.com"]
        
        if any(domain in url.lower() for domain in social_domains):
            return UrlParser._parse_with_ytdlp(url)
        else:
            return UrlParser._parse_with_bs4(url)

    @staticmethod
    def _parse_with_ytdlp(url: str) -> Optional[RawStory]:
        """Extract metadata using yt-dlp."""
        try:
            result = subprocess.run(
                ["yt-dlp", "--dump-json", "--no-warnings", url],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                logger.error(f"yt-dlp failed: {result.stderr}")
                return None
                
            data = json.loads(result.stdout)
            
            title = data.get("title", "Video")
            description = data.get("description", "")
            uploader = data.get("uploader", "Unknown")
            
            content = f"{title}\n\n{description}"
            
            return RawStory(
                title=title[:150],
                url=url,
                source_name=uploader,
                snippet=description[:300] if description else title,
                content=content,
                published_at=datetime.now() # yt-dlp has upload_date but format varies
            )
            
        except Exception as e:
            logger.error(f"Failed to parse video URL: {e}")
            return None

    @staticmethod
    def _parse_with_bs4(url: str) -> Optional[RawStory]:
        """Extract article text using BeautifulSoup."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Get Title
            title = soup.title.string if soup.title else "Web Article"
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text(strip=True)
                
            # Get main content
            # Try to find common article containers
            article = soup.find('article')
            if article:
                paragraphs = article.find_all('p')
            else:
                paragraphs = soup.find_all('p')
                
            text_blocks = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
            content = "\n\n".join(text_blocks)
            
            if not content:
                content = title # Fallback
                
            # Get source name from meta or domain
            domain = url.split("//")[-1].split("/")[0]
            source_name = domain.replace("www.", "")
            
            meta_site_name = soup.find('meta', property='og:site_name')
            if meta_site_name:
                source_name = meta_site_name.get('content', source_name)
                
            return RawStory(
                title=title[:150],
                url=url,
                source_name=source_name,
                snippet=content[:300] if content else title,
                content=content,
                published_at=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Failed to scrape article URL: {e}")
            return None
