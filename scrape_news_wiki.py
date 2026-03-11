"""
自動化英文新聞與維基百科抓取工具
Automated English News & Wikipedia Scraper

依賴安裝 (Dependencies):
    pip install newspaper3k lxml_html_clean requests beautifulsoup4

使用方式 (Usage):
    python scrape_news_wiki.py                  # 預設: 每個新聞源抓 5 篇 + 5 篇維基百科
    python scrape_news_wiki.py --news 10 --wiki 8   # 自訂數量
"""

import os
import re
import random
import time
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 常數設定
# ---------------------------------------------------------------------------
NEWS_SOURCES = [
    "https://www.cnn.com",
    "https://www.reuters.com",
    "https://www.bbc.com/news",
]

WIKI_RANDOM_URL = "https://en.wikipedia.org/wiki/Special:Random"

NEWS_DIR = "news_data"
WIKI_DIR = "wiki_data"

MAX_WORKERS = 8          # 同時最大執行緒數
REQUEST_TIMEOUT = 30     # 單一請求超時 (秒)

# 非法檔名字元
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


# ---------------------------------------------------------------------------
# 工具函式
# ---------------------------------------------------------------------------
def sanitize_filename(name: str, max_len: int = 20) -> str:
    """清理檔名：移除非法字元、截斷長度。"""
    clean = ILLEGAL_CHARS.sub("", name)
    clean = clean.strip().replace(" ", "_")
    # 移除連續底線
    clean = re.sub(r"_+", "_", clean)
    return clean[:max_len] if clean else "untitled"


def make_filename(title: str) -> str:
    """產生 [時間戳]_[標題前20字].txt 的檔名。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = sanitize_filename(title, max_len=20)
    return f"{timestamp}_{safe_title}.txt"


def ensure_dirs():
    """自動建立輸出資料夾。"""
    os.makedirs(NEWS_DIR, exist_ok=True)
    os.makedirs(WIKI_DIR, exist_ok=True)
    print(f"[INIT] Output directories ready: {NEWS_DIR}/, {WIKI_DIR}/")


def save_article(directory: str, title: str, body: str, meta: str = "") -> str:
    """將文章儲存為 UTF-8 純文字檔並回傳檔案路徑。"""
    fname = make_filename(title)
    filepath = os.path.join(directory, fname)

    # 避免同名衝突 (同一秒內可能產生)
    base, ext = os.path.splitext(filepath)
    counter = 1
    while os.path.exists(filepath):
        filepath = f"{base}_{counter}{ext}"
        counter += 1

    content_parts = []
    if title:
        content_parts.append(title)
        content_parts.append("=" * min(len(title), 60))
    if meta:
        content_parts.append(meta)
    if body:
        content_parts.append("")
        content_parts.append(body)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(content_parts))

    return filepath


# ---------------------------------------------------------------------------
# 新聞抓取 (使用 newspaper3k)
# ---------------------------------------------------------------------------
def _build_news_paper(source_url: str):
    """
    用 newspaper3k 建立 Source 物件並解析首頁連結。
    回傳 article URL 列表。
    """
    import newspaper

    paper = newspaper.build(
        source_url,
        memoize_articles=False,
        fetch_images=False,
        language="en",
        request_timeout=REQUEST_TIMEOUT,
    )
    urls = [a.url for a in paper.articles if a.url]
    return urls


def _download_news_article(url: str) -> dict | None:
    """下載並解析單篇新聞文章。回傳 dict 或 None。"""
    import newspaper

    try:
        article = newspaper.Article(url, language="en", request_timeout=REQUEST_TIMEOUT)
        article.download()
        article.parse()

        title = (article.title or "").strip()
        text = (article.text or "").strip()

        if not text or len(text) < 100:
            return None  # 內容太短，可能不是真正的文章

        pub_date = ""
        if article.publish_date:
            pub_date = f"Published: {article.publish_date.strftime('%Y-%m-%d')}"

        return {"title": title, "body": text, "meta": pub_date, "url": url}
    except Exception as e:
        print(f"  [SKIP] {url} — {e}")
        return None


def scrape_news(articles_per_source: int = 5):
    """
    從 CNN / Reuters / BBC 抓取新聞文章。
    每個來源隨機選取 articles_per_source 篇。
    """
    print("\n" + "=" * 60)
    print("  NEWS SCRAPING")
    print("=" * 60)

    all_results = []

    for source_url in NEWS_SOURCES:
        print(f"\n[SOURCE] {source_url}")
        try:
            urls = _build_news_paper(source_url)
            print(f"  Found {len(urls)} article links.")
        except Exception as e:
            print(f"  [ERROR] Failed to build source: {e}")
            continue

        if not urls:
            print("  No articles found, skipping.")
            continue

        # 隨機抽樣
        sample_size = min(articles_per_source, len(urls))
        sampled = random.sample(urls, sample_size)
        print(f"  Randomly selected {sample_size} articles to download.")

        # 多執行緒下載
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_download_news_article, u): u for u in sampled}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    filepath = save_article(NEWS_DIR, result["title"], result["body"], result["meta"])
                    print(f"  [SAVED] {os.path.basename(filepath)}")
                    all_results.append(filepath)

    print(f"\n[NEWS DONE] Saved {len(all_results)} articles to {NEWS_DIR}/")
    return all_results


# ---------------------------------------------------------------------------
# 維基百科抓取
# ---------------------------------------------------------------------------
def _fetch_random_wiki() -> dict | None:
    """抓取一篇隨機維基百科文章。"""
    try:
        resp = requests.get(
            WIKI_RANDOM_URL,
            headers={"User-Agent": "FileGuessr-Scraper/1.0 (educational project)"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        final_url = resp.url

        soup = BeautifulSoup(resp.text, "html.parser")

        # 標題
        title_tag = soup.find("h1", {"id": "firstHeading"})
        title = title_tag.get_text(strip=True) if title_tag else "Untitled"

        # 正文 — 取 <div id="mw-content-text"> 內的所有 <p>
        content_div = soup.find("div", {"id": "mw-content-text"})
        if not content_div:
            return None

        paragraphs = content_div.find_all("p")
        body_parts = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text:
                body_parts.append(text)

        body = "\n\n".join(body_parts)

        if len(body) < 100:
            return None  # 太短的頁面（消歧義頁等）

        return {"title": title, "body": body, "meta": f"Source: {final_url}", "url": final_url}
    except Exception as e:
        print(f"  [SKIP] Wikipedia random — {e}")
        return None


def scrape_wikipedia(count: int = 5):
    """
    抓取 count 篇隨機維基百科文章。
    因為 Special:Random 可能回傳太短的頁面，會多嘗試幾次。
    """
    print("\n" + "=" * 60)
    print("  WIKIPEDIA SCRAPING")
    print("=" * 60)

    results = []
    max_attempts = count * 3  # 最多嘗試 3 倍數量

    # 先批次取得文章
    print(f"  Target: {count} articles (max {max_attempts} attempts)")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(_fetch_random_wiki) for _ in range(max_attempts)]

        for future in as_completed(futures):
            if len(results) >= count:
                break
            result = future.result()
            if result:
                filepath = save_article(WIKI_DIR, result["title"], result["body"], result["meta"])
                print(f"  [SAVED] {os.path.basename(filepath)}")
                results.append(filepath)

    print(f"\n[WIKI DONE] Saved {len(results)} articles to {WIKI_DIR}/")
    return results


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Scrape English news & Wikipedia articles into plain text files."
    )
    parser.add_argument("--news", type=int, default=5,
                        help="Number of articles to scrape PER news source (default: 5)")
    parser.add_argument("--wiki", type=int, default=5,
                        help="Number of random Wikipedia articles to scrape (default: 5)")
    args = parser.parse_args()

    print("=" * 60)
    print("  News & Wikipedia Scraper")
    print(f"  Config: {args.news} articles/news-source, {args.wiki} wiki articles")
    print("=" * 60)

    ensure_dirs()

    start = time.time()

    news_files = scrape_news(articles_per_source=args.news)
    wiki_files = scrape_wikipedia(count=args.wiki)

    elapsed = time.time() - start

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  News articles saved : {len(news_files)}")
    print(f"  Wiki articles saved : {len(wiki_files)}")
    print(f"  Total time          : {elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
