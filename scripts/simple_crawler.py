#!/usr/bin/env python3
"""
簡單的 Python 爬蟲範例
使用 requests + beautifulsoup4

安裝依賴（如果還沒裝）：
uv add requests beautifulsoup4

用法：
uv run python scripts/simple_crawler.py https://example.com

會輸出頁面標題 + 前 10 個連結
"""

import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def simple_crawl(url: str, max_links: int = 10) -> dict:
    """抓取單一頁面，提取標題與連結。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SimpleCrawler/1.0; +https://example.com)"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"error": f"請求失敗: {e}"}
    
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # 標題
    title = soup.title.string.strip() if soup.title and soup.title.string else "無標題"
    
    # 收集連結（只取 http/https 開頭的）
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        
        # 轉成絕對 URL
        absolute = urljoin(url, href)
        parsed = urlparse(absolute)
        if parsed.scheme in ("http", "https"):
            text = a.get_text(strip=True) or "[無文字]"
            links.append({"text": text[:80], "url": absolute})
            if len(links) >= max_links:
                break
    
    return {
        "url": url,
        "title": title,
        "links": links,
        "status_code": resp.status_code,
    }


def main():
    if len(sys.argv) < 2:
        print("用法: uv run python scripts/simple_crawler.py <URL>")
        print("範例: uv run python scripts/simple_crawler.py https://news.ycombinator.com")
        sys.exit(1)
    
    target_url = sys.argv[1]
    print(f"開始爬取: {target_url}\n")
    
    result = simple_crawl(target_url)
    
    if "error" in result:
        print(result["error"])
        return
    
    print(f"標題: {result['title']}")
    print(f"狀態碼: {result['status_code']}")
    print(f"找到 {len(result['links'])} 個連結（前 {min(10, len(result['links']))} 個）：\n")
    
    for i, link in enumerate(result["links"], 1):
        print(f"{i}. {link['text']}")
        print(f"   {link['url']}\n")
    
    print("完成！這是極簡版本，實際爬蟲請注意：")
    print("- robots.txt")
    print("- 延遲 (time.sleep)")
    print("- 錯誤處理")
    print("- 不要對同一個網站太頻繁請求")


if __name__ == "__main__":
    main()
