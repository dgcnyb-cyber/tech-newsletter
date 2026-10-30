import os
import urllib.request
import socket
from datetime import datetime, timezone, timedelta
import feedparser
import trafilatura
from google import genai
import resend

# 1. 환경 변수 및 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "dgcnyb@gmail.com").strip()

# 전체 네트워크 요청 타임아웃 7초로 강제 제한 (10분 멈춤 방지)
socket.setdefaulttimeout(7)

resend.api_key = RESEND_API_KEY
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 2. 도료·코팅 전문 매체, 원료사, 특허 RSS 소스 (응답 빠른 안정적 소스 위주)
RSS_FEEDS = [
    {"source": "Coatings World", "type": "산업동향", "url": "https://www.coatingsworld.com/rss/all"},
    {"source": "PCI Magazine", "type": "도료기술", "url": "https://www.pcimag.com/rss/articles"},
    {"source": "European Coatings", "type": "도료기술", "url": "https://www.european-coatings.com/rss/news"},
    {"source": "ScienceDirect (Coatings)", "type": "학술/논문", "url": "https://rss.sciencedirect.com/publication/science/03009440"},
    {"source": "BASF News", "type": "원료사동향", "url": "https://www.basf.com/global/en/media/news-releases.rss"},
    {"source": "Evonik News", "type": "원료사동향", "url": "https://corporate.evonik.com/en/media/press-releases.rss"},
    {
        "source": "Google Patents (Road Marking & Coating)",
        "type": "특허",
        "url": "https://patents.google.com/feeds/search?q=(road+marking+paint+OR+traffic+paint)+AND+coating&sort=new&num=5"
    }
]

# 3. 도료 및 고분자 연구 핵심 필터링 키워드
TARGET_KEYWORDS = [
    "coating", "paint", "road marking", "traffic paint", "pavement",
    "architectural", "protective coating", "waterborne", "solvent-free",
    "anti-corrosion", "anti-icing", "weatherability", "retroreflectivity",
    "polymer", "resin", "binder", "emulsion", "polyurethane", "acrylic", 
    "epoxy", "crosslinker", "encapsulat", "nanocomposite", "dispersion",
    "additive", "curing", "functional polymer", "silane"
]

def is_relevant_article(title, summary):
    text_to_check = f"{title} {summary}".lower()
    return any(keyword in text_to_check for keyword in TARGET_KEYWORDS)

def safe_fetch_text(url, default_text=""):
    """타임아웃을 엄격히 적용하여 웹페이지 본문을 가져옵니다."""
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8', errors='ignore')
            extracted = trafilatura.extract(html)
            return extracted[:2500] if extracted else default_text[:1200]
    except Exception:
        # 응답이 늦거나 차단되면 기다리지 않고 RSS 기본 요약문으로 즉시 대체
        return default_text[:1200]

def fetch_articles(limit_per_feed=2, max_total=6):
    articles = []
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            count = 0
            for entry in feed.entries:
                if count >= limit_per_feed:
                    break
                    
                title = entry.get("title", "제목 없음")
                link = entry.get("link", "")
                rss_summary = entry.get("summary", "")
                
                if feed_info["type"] != "특허" and not is_relevant_article(title, rss_summary):
                    continue

                # 타임아웃 안전 장치 적용 본문 추출
                text_content = safe_fetch_text(link, default_text=rss_summary)

                articles.append({
                    "source": feed_info["source"],
                    "category": feed_info["type"],
                    "title": title,
                    "link": link,
                    "content": text_content if text_content else title
                })
                count += 1
                
                if len(articles) >= max_total:
                    return articles
        except Exception as e:
            print(f"[{feed_info['source']}] 피드 수집 스킵: {e}")
            continue

    return articles

def summarize_with_gemini(article):
    prompt = f"""
    당신은 도료·코팅 및 고분자 화학 분야의 R&D 수석 연구원입니다.
    아래 기술 정보(분류: {article['category']})를 분석하여 동료 연구원들을 위한 브리핑을 작성해 주세요.

    [자료 제목]: {article['title']}
    [본문 내용]: {article['content']}

    [작성 가이드]:
    - 한국어로 전문적이고 간결하게 작성할 것
    - 분류가 '특허'인 경우: 핵심 기술 구성(바인더/첨가제/경화계) 및 해결 과제 명시
    - 분류가 '원료사동향' 또는 '도료기술'인 경우: 수지/바인더 특성, 물성 개선 효과(내구성, 내후성 등)와 배합 처방 관점의 의의 기술
    - 글머리 기호(-)로 2~3줄 요약
    - 불필요한 인사말이나 서두는 생략
    """
    try:
        response = ai_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt
        )
        return response.text.replace("\n", "<br>")
    except Exception as e:
        print(f"Gemini 요약 실패 ({article['title']}): {e}")
        return "기술 요약을 생성하지 못했습니다."

def build_html_email(summarized_articles, today_str):
    category_colors = {
        "특허": {"bg": "#fee2e2", "text": "#b91c1c"},
        "원료사동향": {"bg": "#fef3c7", "text": "#b45309"},
        "도료기술": {"bg": "#e0f2fe", "text": "#0369a1"},
        "학술/논문": {"bg": "#f3e8ff", "text": "#7e22ce"},
        "산업동향": {"bg": "#f1f5f9", "text": "#475569"}
    }

    cards_html = ""
    for item in summarized_articles:
        cat = item.get("category", "도료기술")
        colors = category_colors.get(cat, {"bg": "#e0f2fe", "text": "#0369a1"})

        cards_html += f"""
        <div style="margin-bottom: 22px; padding: 18px; border-radius: 8px; background-color: #f8fafc; border: 1px solid #e2e8f0;">
            <div style="margin-bottom: 8px;">
                <span style="font-size: 11px; font-weight: 700; color: {colors['text']}; background-color: {colors['bg']}; padding: 3px 8px; border-radius: 4px; margin-right: 6px;">
                    {cat}
                </span>
                <span style="font-size: 11px; color: #64748b; font-weight: 600;">
                    {item['source']}
                </span>
            </div>
            <h3 style="margin: 0 0 12px 0; font-size: 16px; line-height: 1.45; color: #0f172a;">
                <a href="{item['link']}" target="_blank" style="color: #0f172a; text-decoration: none; font-weight: 600;">
                    {item['title']} &rarr;
                </a>
            </h3>
            <div style="font-size: 13.5px; line-height: 1.65; color: #334155;">
                {item['summary']}
            </div>
        </div>
        """

    if not cards_html:
        cards_html = "<p style='color: #64748b; font-size: 14px;'>금일 모니터링된 신규 기술 기사가 없습니다.</p>"

    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head><meta charset="UTF-8"></head>
    <body style="margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', Pretendard, Roboto, sans-serif; background-color: #ffffff; color: #0f172a;">
        <div style="max-width: 650px; margin: 0 auto;">
            <header style="border-bottom: 2px solid #0f172a; padding-bottom: 14px; margin-bottom: 24px;">
                <div style="font-size: 11px; font-weight: 700; color: #0284c7; letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 4px;">R&D Intelligence Briefing</div>
                <h2 style="margin: 0; font-size: 21px; color: #0f172a;">🧪 도료·코팅 & 고분자 재료 기술 동향</h2>
                <p style="margin: 6px 0 0 0; color: #64748b; font-size: 13px;">{today_str} | 특허·원료사·노면표지·기능성 바인더 동향</p>
            </header>
            
            {cards_html}
            
            <footer style="margin-top: 36px; border-top: 1px solid #e2e8f0; padding-top: 16px; font-size: 12px; color: #94a3b8; text-align: center;">
                도료 및 기능성 재료 R&D 자동 모니터링 시스템 (GitHub Actions & Gemini API)
            </footer>
        </div>
    </body>
    </html>
    """
    return html

def main():
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime("%Y년 %m월 %d일")
    
    print(f"[{today_str}] 수집 시작...")
    articles = fetch_articles(limit_per_feed=2, max_total=5)
    print(f"수집 완료: 총 {len(articles)}개 항목")
    
    summarized_articles = []
    for art in articles:
        print(f"[{art['category']}] 요약 중: {art['title']}")
        art["summary"] = summarize_with_gemini(art)
        summarized_articles.append(art)
        
    html_content = build_html_email(summarized_articles, today_str)
    
    target_email = RECIPIENT_EMAIL if "@" in RECIPIENT_EMAIL else "dgcnyb@gmail.com"
    print(f"{target_email} 메일 발송 중...")
    
    params = {
        "from": "R&D Coatings Brief <onboarding@resend.dev>",
        "to": [target_email],
        "subject": f"[R&D 브리핑] {today_str} 도료 특허·원료사·기능성 코팅 기술 동향",
        "html": html_content,
    }
    
    response = resend.Emails.send(params)
    print("메일 발송 완료:", response)

if __name__ == "__main__":
    main()
