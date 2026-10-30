import os
import urllib.request
from datetime import datetime, timezone, timedelta
import feedparser
from google import genai
import resend

# 1. 환경 변수 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

# 수신 주소를 리스트 안에 직접 명시하여 유효성 에러 원천 차단
TARGET_RECIPIENTS = ["dgcnyb@gmail.com"]

resend.api_key = RESEND_API_KEY
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 2. 도료/화학 RSS 소스
RSS_FEEDS = [
    {"source": "Coatings World", "type": "산업동향", "url": "https://www.coatingsworld.com/rss/all"},
    {"source": "PCI Magazine", "type": "도료기술", "url": "https://www.pcimag.com/rss/articles"},
    {"source": "European Coatings", "type": "도료기술", "url": "https://www.european-coatings.com/rss/news"},
]

# 3. 도료 및 고분자 연구 필터링 키워드
TARGET_KEYWORDS = [
    "coating", "paint", "road marking", "traffic paint", "pavement",
    "architectural", "protective coating", "waterborne", "solvent-free",
    "anti-corrosion", "anti-icing", "weatherability", "retroreflectivity",
    "polymer", "resin", "binder", "emulsion", "polyurethane", "acrylic", 
    "epoxy", "crosslinker", "encapsulat", "nanocomposite", "dispersion",
    "additive", "curing", "functional polymer", "silane"
]

def fetch_feed_safely(url, timeout=5):
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            return feedparser.parse(content)
    except Exception as e:
        print(f"[{url}] 수집 건너뜀: {e}")
        return None

def is_relevant(title, summary):
    text = f"{title} {summary}".lower()
    return any(k in text for k in TARGET_KEYWORDS)

def collect_articles(max_total=5):
    articles = []
    for f in RSS_FEEDS:
        feed = fetch_feed_safely(f["url"], timeout=4)
        if not feed or not feed.entries:
            continue
            
        for entry in feed.entries[:3]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", "").strip()
            
            if not summary:
                summary = title

            if is_relevant(title, summary) or len(articles) < 2:
                articles.append({
                    "source": f["source"],
                    "category": f["type"],
                    "title": title,
                    "link": link,
                    "content": summary[:1000]
                })
                
            if len(articles) >= max_total:
                return articles
    return articles

def summarize_with_gemini(article):
    prompt = f"""
    당신은 도료·코팅 및 고분자 재료 분야의 R&D 수석 연구원입니다.
    아래 기술/산업 정보를 바탕으로 동료 연구원들을 위한 브리핑을 작성해 주세요.

    [제목]: {article['title']}
    [내용]: {article['content']}

    [작성 규칙]:
    - 한국어로 작성할 것
    - 핵심 요약 2~3줄 (수지/바인더 특성, 도료 처방, 물성 개선 효과 등)
    - R&D 적용 시사점 1줄 (노면표지, 건축용, 특수 코팅 등 현업 적용 관점)
    - 글머리 기호(-) 사용, 불필요한 인사말 생략
    """
    try:
        response = ai_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt
        )
        return response.text.replace("\n", "<br>")
    except Exception as e:
        print(f"요약 실패: {e}")
        return "기술 요약을 생성하지 못했습니다."

def build_html_email(summarized_articles, today_str):
    category_colors = {
        "도료기술": {"bg": "#e0f2fe", "text": "#0369a1"},
        "산업동향": {"bg": "#f1f5f9", "text": "#475569"}
    }

    cards_html = ""
    for item in summarized_articles:
        cat = item.get("category", "도료기술")
        colors = category_colors.get(cat, {"bg": "#e0f2fe", "text": "#0369a1"})

        cards_html += f"""
        <div style="margin-bottom: 20px; padding: 18px; border-radius: 8px; background-color: #f8fafc; border: 1px solid #e2e8f0;">
            <div style="margin-bottom: 8px;">
                <span style="font-size: 11px; font-weight: 700; color: {colors['text']}; background-color: {colors['bg']}; padding: 3px 8px; border-radius: 4px; margin-right: 6px;">
                    {cat}
                </span>
                <span style="font-size: 11px; color: #64748b; font-weight: 600;">
                    {item['source']}
                </span>
            </div>
            <h3 style="margin: 0 0 10px 0; font-size: 16px; line-height: 1.45; color: #0f172a;">
                <a href="{item['link']}" target="_blank" style="color: #0369a1; text-decoration: none; font-weight: 600;">
                    {item['title']} &rarr;
                </a>
            </h3>
            <div style="font-size: 13.5px; line-height: 1.6; color: #334155;">
                {item['summary']}
            </div>
        </div>
        """

    if not cards_html:
        cards_html = "<p style='color: #64748b; font-size: 14px;'>금일 도료/고분자 기술 기사가 없습니다.</p>"

    return f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head><meta charset="UTF-8"></head>
    <body style="margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', Pretendard, sans-serif; background-color: #ffffff; color: #0f172a;">
        <div style="max-width: 650px; margin: 0 auto;">
            <header style="border-bottom: 2px solid #0284c7; padding-bottom: 12px; margin-bottom: 20px;">
                <h2 style="margin: 0; font-size: 20px; color: #0f172a;">🧪 도료·코팅 & 고분자 R&D 브리핑</h2>
                <p style="margin: 4px 0 0 0; color: #64748b; font-size: 13px;">{today_str} | 노면표지·건축·특수 코팅 및 바인더 기술 동향</p>
            </header>
            {cards_html}
            <footer style="margin-top: 32px; border-top: 1px solid #e2e8f0; padding-top: 14px; font-size: 12px; color: #94a3b8; text-align: center;">
                R&D Intelligence Briefing System
            </footer>
        </div>
    </body>
    </html>
    """

def main():
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime("%Y년 %m월 %d일")
    
    print(f"[{today_str}] 기사 수집 시작...")
    articles = collect_articles(max_total=5)
    print(f"수집 완료: {len(articles)}개")
    
    summarized = []
    for art in articles:
        print(f"요약 중: {art['title']}")
        art["summary"] = summarize_with_gemini(art)
        summarized.append(art)
        
    html_content = build_html_email(summarized, today_str)
    
    print("dgcnyb@gmail.com 메일 발송 중...")
    params = {
        "from": "R&D Coatings Brief <onboarding@resend.dev>",
        "to": TARGET_RECIPIENTS,
        "subject": f"[R&D 브리핑] {today_str} 도료·코팅 및 고분자 기술 동향",
        "html": html_content,
    }
    
    response = resend.Emails.send(params)
    print("메일 발송 완료:", response)

if __name__ == "__main__":
    main()
