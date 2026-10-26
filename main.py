import os
from datetime import datetime, timezone, timedelta
import feedparser
import trafilatura
from google import genai
import resend

# 1. 환경 변수 및 클라이언트 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "dgcnyb@gmail.com")

resend.api_key = RESEND_API_KEY
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 2. 도료·코팅 전문 매체, 글로벌 원료사, 특허 모니터링 RSS 소스
RSS_FEEDS = [
    # [코팅 & 도료 전문 저널]
    {"source": "Coatings World", "type": "산업동향", "url": "https://www.coatingsworld.com/rss/all"},
    {"source": "PCI Magazine", "type": "도료기술", "url": "https://www.pcimag.com/rss/articles"},
    {"source": "European Coatings", "type": "도료기술", "url": "https://www.european-coatings.com/rss/news"},
    {"source": "Progress in Organic Coatings", "type": "학술/논문", "url": "https://rss.sciencedirect.com/publication/science/03009440"},

    # [글로벌 화학·원료사 뉴스룸]
    {"source": "BASF News", "type": "원료사동향", "url": "https://www.basf.com/global/en/media/news-releases.rss"},
    {"source": "Dow Newsroom", "type": "원료사동향", "url": "https://corporate.dow.com/en-us/news/press-releases.rss"},
    {"source": "Evonik News", "type": "원료사동향", "url": "https://corporate.evonik.com/en/media/press-releases.rss"},

    # [글로벌 특허 모니터링 (Google Patents Atom Feed)]
    {
        "source": "Google Patents (Road Marking)",
        "type": "특허",
        "url": "https://patents.google.com/feeds/search?q=(road+marking+paint+OR+traffic+paint)+AND+coating&sort=new&num=10"
    },
    {
        "source": "Google Patents (Functional Coating & Binder)",
        "type": "특허",
        "url": "https://patents.google.com/feeds/search?q=(anti-icing+OR+anti-corrosion+OR+self-healing)+AND+(coating+OR+binder)&sort=new&num=10"
    }
]

# 3. 도료 및 고분자 연구 핵심 필터링 키워드
TARGET_KEYWORDS = [
    # 도료/코팅 및 노면표지
    "coating", "paint", "road marking", "traffic paint", "pavement",
    "architectural", "protective coating", "waterborne", "solvent-free",
    "anti-corrosion", "anti-icing", "weatherability", "retroreflectivity",
    
    # 바인더, 수지 및 첨가제 원료 기술
    "polymer", "resin", "binder", "emulsion", "polyurethane", "acrylic", 
    "epoxy", "crosslinker", "encapsulat", "nanocomposite", "dispersion",
    "additive", "curing", "functional polymer", "silane"
]

def is_relevant_article(title, summary):
    """제목 및 요약문에서 도료/고분자 키워드를 대소문자 구분 없이 필터링합니다."""
    text_to_check = f"{title} {summary}".lower()
    return any(keyword in text_to_check for keyword in TARGET_KEYWORDS)

def fetch_articles(limit_per_feed=3, max_total=7):
    """각 RSS 피드에서 관련 기사 및 최신 특허를 수집합니다."""
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
                
                # 특허 피드는 이미 검색 쿼리가 걸려있으므로 바로 통과, 일반 피드는 키워드 필터링
                if feed_info["type"] != "특허" and not is_relevant_article(title, rss_summary):
                    continue

                # 본문 텍스트 추출 (특허 사이트나 일반 뉴스 페이지 대응)
                downloaded = trafilatura.fetch_url(link)
                text_content = trafilatura.extract(downloaded) if downloaded else ""
                
                if not text_content:
                    text_content = rss_summary[:1200]
                else:
                    text_content = text_content[:2500]

                articles.append({
                    "source": feed_info["source"],
                    "category": feed_info["type"],
                    "title": title,
                    "link": link,
                    "content": text_content
                })
                count += 1
                
                if len(articles) >= max_total:
                    return articles
        except Exception as e:
            print(f"[{feed_info['source']}] 피드 수집 실패: {e}")
            continue

    return articles

def summarize_with_gemini(article):
    """도료/고분자 화학 수석 연구원 관점에서 특허 및 기술을 정밀 분석합니다."""
    prompt = f"""
    당신은 도료·코팅 및 고분자 화학 분야의 R&D 수석 연구원입니다.
    아래 기술 정보(분류: {article['category']})를 분석하여 동료 연구원들을 위한 브리핑을 작성해 주세요.

    [자료 제목]: {article['title']}
    [본문 내용]: {article['content']}

    [작성 가이드]:
    - 한국어로 전문적이고 명확하게 작성할 것
    - 분류가 '특허'인 경우: 주요 청구 특징/핵심 기술 구성(바인더, 첨가제, 경화 방식) 및 해결하고자 한 종래 기술의 과제를 명시
    - 분류가 '원료사동향' 또는 '도료기술'인 경우: 수지/바인더 특성, 물성 개선 효과(내구성, 내후성, 친환경 수용화 등)와 배합 처방 관점의 의의 기술
    - 글머리 기호(-)를 활용해 2~3줄로 작성
    - 불필요한 서두나 결론 인사말은 완전히 생략하고 내용만 출력
    """
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text.replace("\n", "<br>")
    except Exception as e:
        print(f"Gemini 요약 실패 ({article['title']}): {e}")
        return "기술 요약을 생성하지 못했습니다."

def build_html_email(summarized_articles, today_str):
    """카테고리 뱃지(특허, 원료사동향, 도료기술)가 적용된 전문 R&D HTML 메일 템플릿"""
    category_colors = {
        "특허": {"bg": "#fee2e2", "text": "#b91c1c"},      # 레드/버건디 계열
        "원료사동향": {"bg": "#fef3c7", "text": "#b45309"},  # 앰버/오렌지 계열
        "도료기술": {"bg": "#e0f2fe", "text": "#0369a1"},    # 블루 계열
        "학술/논문": {"bg": "#f3e8ff", "text": "#7e22ce"},   # 퍼플 계열
        "산업동향": {"bg": "#f1f5f9", "text": "#475569"}     # 그레이 계열
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
        cards_html = "<p style='color: #64748b; font-size: 14px;'>금일 모니터링된 신규 특허 및 원료/도료 기술 기사가 없습니다.</p>"

    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head><meta charset="UTF-8"></head>
    <body style="margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', Pretendard, Roboto, sans-serif; background-color: #ffffff; color: #0f172a;">
        <div style="max-width: 650px; margin: 0 auto;">
            <header style="border-bottom: 2px solid #0f172a; padding-bottom: 14px; margin-bottom: 24px;">
                <div style="font-size: 11px; font-weight: 700; color: #0284c7; letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 4px;">R&D Intelligence Briefing</div>
                <h2 style="margin: 0; font-size: 21px; color: #0f172a;">🧪 도료·코팅 & 고분자 재료 기술 동향</h2>
                <p style="margin: 6px 0 0 0; color: #64748b; font-size: 13px;">{today_str} | 특허·원료사(BASF/Dow/Evonik)·노면표지·기능성 바인더 동향</p>
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
    
    print(f"[{today_str}] 특허, 원료사, 도료 기술 기사 통합 수집 시작...")
    articles = fetch_articles(limit_per_feed=3, max_total=7)
    print(f"수집 완료: 총 {len(articles)}개 항목")
    
    summarized_articles = []
    for art in articles:
        print(f"[{art['category']}] 분석 및 요약 중: {art['title']}")
        art["summary"] = summarize_with_gemini(art)
        summarized_articles.append(art)
        
    html_content = build_html_email(summarized_articles, today_str)
    
    print(f"{RECIPIENT_EMAIL} 주소로 발송 중...")
    params = {
        "from": "R&D Coatings Brief <onboarding@resend.dev>",
        "to": [RECIPIENT_EMAIL],
        "subject": f"[R&D 브리핑] {today_str} 도료 특허·원료사·기능성 코팅 기술 동향",
        "html": html_content,
    }
    
    response = resend.Emails.send(params)
    print("메일 발송 성공:", response)

if __name__ == "__main__":
    main()
