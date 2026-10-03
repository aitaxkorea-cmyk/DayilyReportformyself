import os
from datetime import datetime
import feedparser
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from google import genai

# 1. 환경 설정 (GitHub Secrets에서 자동 로드)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 2. 데이터 수집 모듈
def get_macro_indicators():
    tickers = {
        "S&P 500": "^GSPC",
        "나스닥": "^IXIC",
        "필라델피아 반도체": "^SOX",
        "미 10년물 국채금리": "^TNX",
        "원/달러 환율": "KRW=X",
        "코스피": "^KS11"
    }
    summary = []
    for name, symbol in tickers.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                last_close = hist['Close'].iloc[-1]
                change_pct = ((last_close - prev_close) / prev_close) * 100
                summary.append(f"- {name}: {last_close:,.2f} ({change_pct:+.2f}%)")
        except Exception:
            continue
    return "\n".join(summary)

def get_economic_news():
    rss_urls = [
        ("한경 증권/시황", "https://www.hankyung.com/feed/finance"),
        ("한경 국제/글로벌마켓", "https://www.hankyung.com/feed/international"),
        ("매경 증권", "https://www.mk.co.kr/rss/50200011/")
    ]
    news_list = []
    for source_name, url in rss_urls:
        feed = feedparser.parse(url)
        for entry in feed.entries[:12]:
            title = entry.get("title", "")
            desc = entry.get("description", "")[:150]
            news_list.append(f"[{source_name}] {title} - {desc}")
    return "\n".join(news_list)

def get_naver_market_reports():
    url = "https://finance.naver.com/research/market_info_list.naver"
    headers = {"User-Agent": "Mozilla/5.0"}
    reports = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        rows = soup.select("table.type_1 tr")
        for row in rows:
            cols = row.select("td")
            if len(cols) >= 3:
                title = cols[0].get_text(strip=True)
                broker = cols[1].get_text(strip=True)
                date = cols[2].get_text(strip=True)
                if title:
                    reports.append(f"- [{broker}] {title} ({date})")
                if len(reports) >= 10:
                    break
    except Exception as e:
        reports.append(f"리포트 수집 오류: {e}")
    return "\n".join(reports)

# 3. AI 리포트 생성 모듈 (작동 가능한 최신 Gemini 모델 자동 탐색)
def generate_hunter_report(macro_data, news_data, report_data):
    client = genai.Client(api_key=GEMINI_API_KEY)
    today_str = datetime.now().strftime("%Y년 %m월 %d일")

    prompt = f"""
당신은 65만 구독자를 보유한 인기 주식·경제 분석가 '경제사냥꾼'입니다.
단순히 뉴스를 나열하지 말고, 투자자들이 가장 궁금해하는 '표면적 뉴스 이면의 진짜 이유(Why)', '월가와 외국인 수급의 속내', '국내 증시(코스피/주도 섹터)에 미칠 파급력'을 날카롭고 이해하기 쉽게 브리핑해 주세요.

[오늘 날짜]: {today_str}

[1. 글로벌 매크로 및 지수 현황]
{macro_data}

[2. 국내외 주요 증권/경제 뉴스 헤드라인]
{news_data}

[3. 오늘 자 국내 증권사 시황 리포트 목록]
{report_data}

---
위 데이터를 종합 분석하여 아래 양식으로 일일 경제사냥꾼 심층 리포트를 작성해 주세요:

## 🎯 1. 오늘의 핵심 헤드라인 3선 (호기심 및 핵심 찌르기)
- (예: "월가가 지금 '이 섹터'를 조용히 쓸어담는 진짜 이유" 형태로 오늘 가장 중요한 이슈 3가지를 한 줄 요약)

## 🌍 2. 월가 & 글로벌 매크로 속내 분석
- 간밤 미국 증시(빅테크/반도체 등)와 금리·환율 움직임의 핵심 배경
- 표면적인 뉴스 뒤에 숨겨진 기관/월가의 진짜 시선 해설

## 🔥 3. 오늘 한국 증시(KOSPI) 주도 섹터 & 수급 포인트
- 글로벌 이슈가 국내 주요 섹터(반도체, 원전, 로봇, 방산, 밸류업/우선주 등 오늘 뉴스에 등장한 핵심 테마)에 미치는 연결고리 분석
- 투자자가 오늘 장에서 주목해야 할 수급 포인트

## 📅 4. 투자자가 꼭 알아야 할 오늘의 체크리스트 & 실전 전략
- 초보 투자자도 흔들리지 않도록 오늘 취해야 할 핵심 대응 포인트 3가지 정리
"""

    # 우선 시도할 최신 모델 목록
    candidate_models = [
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-3-pro-preview",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
    ]

    # 내 API 키에서 실제 지원하는 모델 목록을 조회해 후보에 자동 추가
    try:
        for m in client.models.list():
            name = (getattr(m, "name", "") or "").replace("models/", "")
            if name.startswith("gemini-") and not any(
                skip in name for skip in [
                    "gemini-2.5-flash", "2.0", "1.5", "embedding",
                    "tts", "image", "audio", "veo", "robotics", "computer"
                ]
            ):
                if name not in candidate_models:
                    candidate_models.append(name)
    except Exception as e:
        print(f"모델 목록 조회 참고: {e}")

    # 작동하는 모델이 나올 때까지 순서대로 실행
    last_error = None
    for model_name in candidate_models:
        try:
            print(f"모델 호출 시도 중: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            if response and response.text:
                print(f"리포트 생성 성공 (사용된 모델: {model_name})")
                return response.text
        except Exception as e:
            print(f"{model_name} 건너뜀: {e}")
            last_error = e

    raise RuntimeError(f"사용 가능한 모델을 찾지 못했습니다. 마지막 오류: {last_error}")

# 4. 텔레그램 발송 모듈
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunk_size = 3800
    for i in range(0, len(text), chunk_size):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text[i:i+chunk_size]
        }
        requests.post(url, data=payload)

def main():
    macro_data = get_macro_indicators()
    news_data = get_economic_news()
    report_data = get_naver_market_reports()
    report = generate_hunter_report(macro_data, news_data, report_data)
    send_telegram_message(report)
    print("보고서 생성 및 텔레그램 전송 완료!")

if __name__ == "__main__":
    main()
