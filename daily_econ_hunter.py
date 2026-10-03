import os
import urllib.request
from urllib.parse import quote
from datetime import datetime
import feedparser
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from google import genai

# ==========================================
# 1. 환경 설정 (GitHub Secrets에서 자동 로드)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ==========================================
# 2. 관심 종목 설정 (네비우스 그룹 포함)
# ==========================================
WATCHLIST = {
    "삼성전자우": "005935.KS",
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "엠케이전자": "033160.KQ",
    "네비우스 그룹": "NBIS"
}

MACRO_TICKERS = {
    "S&P 500": "^GSPC",
    "나스닥": "^IXIC",
    "필라델피아 반도체": "^SOX",
    "미 10년물 금리": "^TNX",
    "원/달러 환율": "KRW=X",
    "코스피": "^KS11"
}

# ==========================================
# 3. 한글 폰트 설정 (차트/표 한글 깨짐 방지)
# ==========================================
def setup_korean_font():
    font_path = "NanumGothic-Bold.ttf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf"
            urllib.request.urlretrieve(url, font_path)
        except Exception as e:
            print(f"폰트 다운로드 건너뜀: {e}")
    if os.path.exists(font_path):
        fm.fontManager.addfont(font_path)
        font_name = fm.FontProperties(fname=font_path).get_name()
        plt.rc("font", family=font_name)
    plt.rcParams["axes.unicode_minus"] = False

# ==========================================
# 4. 매크로 및 관심 종목 지표 계산 모듈
# ==========================================
def get_macro_data():
    macro_list = []
    macro_text = []
    for name, symbol in MACRO_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist) >= 2:
                prev = hist["Close"].iloc[-2]
                curr = hist["Close"].iloc[-1]
                chg = ((curr - prev) / prev) * 100
                macro_list.append({"name": name, "close": curr, "change": chg})
                macro_text.append(f"- {name}: {curr:,.2f} ({chg:+.2f}%)")
        except Exception:
            continue
    return macro_list, "\n".join(macro_text)

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_watchlist_data():
    stock_rows = []
    stock_text = []
    for name, symbol in WATCHLIST.items():
        try:
            hist = yf.Ticker(symbol).history(period="6mo")
            if len(hist) < 20:
                continue
            close_s = hist["Close"]
            curr = close_s.iloc[-1]
            prev = close_s.iloc[-2]
            chg_1d = ((curr - prev) / prev) * 100
            chg_5d = ((curr - close_s.iloc[-6]) / close_s.iloc[-6]) * 100 if len(close_s) >= 6 else 0.0

            rsi_val = calculate_rsi(close_s).iloc[-1]
            ma20 = close_s.rolling(20).mean().iloc[-1]
            ma120 = close_s.rolling(120).mean().iloc[-1] if len(close_s) >= 120 else ma20

            is_krw = symbol.endswith(".KS") or symbol.endswith(".KQ")
            price_str = f"{curr:,.0f}원" if is_krw else f"${curr:,.2f}"
            ma120_status = "120일선 위" if curr >= ma120 else "120일선 아래"
            ma20_status = "20일선 위" if curr >= ma20 else "20일선 아래"

            stock_rows.append({
                "name": name,
                "price_str": price_str,
                "chg_1d": chg_1d,
                "chg_5d": chg_5d,
                "rsi": rsi_val,
                "trend": f"{ma20_status} / {ma120_status}"
            })
            stock_text.append(
                f"- {name}({symbol}): 현재가 {price_str} | 전일대비 {chg_1d:+.2f}% | "
                f"5일수익률 {chg_5d:+.2f}% | RSI(14): {rsi_val:.1f} | 위치: {ma20_status}, {ma120_status}"
            )
        except Exception as e:
            print(f"{name} 데이터 조회 오류: {e}")
    return stock_rows, "\n".join(stock_text)

# ==========================================
# 5. 뉴스 및 증권사 리포트 수집 모듈
# ==========================================
def get_economic_news():
    rss_urls = [
        ("한경 증권", "https://www.hankyung.com/feed/finance"),
        ("한경 글로벌마켓", "https://www.hankyung.com/feed/international"),
        ("매경 증권", "https://www.mk.co.kr/rss/50200011/")
    ]
    news_list = []
    for source_name, url in rss_urls:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            desc = entry.get("description", "")[:120]
            news_list.append(f"[{source_name}] {title} - {desc}")
    return "\n".join(news_list)

def get_watchlist_news():
    watchlist_news = []
    for name in WATCHLIST.keys():
        clean_name = name.split("(")[0]
        rss_url = f"https://news.google.com/rss/search?q={quote(clean_name)}+주식&hl=ko&gl=KR&ceid=KR:ko"
        try:
            feed = feedparser.parse(rss_url)
            titles = [entry.title for entry in feed.entries[:2]]
            if titles:
                watchlist_news.append(f"[{clean_name}] " + " / ".join(titles))
        except Exception:
            continue
    return "\n".join(watchlist_news)

def get_naver_reports():
    headers = {"User-Agent": "Mozilla/5.0"}
    results = []

    # 1) 시황정보 리포트
    try:
        res = requests.get("https://finance.naver.com/research/market_info_list.naver", headers=headers, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        for row in soup.select("table.type_1 tr"):
            cols = row.select("td")
            if len(cols) >= 3 and cols[0].get_text(strip=True):
                results.append(f"[시황-{cols[1].get_text(strip=True)}] {cols[0].get_text(strip=True)}")
            if len(results) >= 7:
                break
    except Exception:
        pass

    # 2) 종목분석 리포트
    try:
        res2 = requests.get("https://finance.naver.com/research/company_list.naver", headers=headers, timeout=10)
        res2.encoding = "euc-kr"
        soup2 = BeautifulSoup(res2.text, "html.parser")
        count = 0
        for row in soup2.select("table.type_1 tr"):
            cols = row.select("td")
            if len(cols) >= 5 and cols[0].get_text(strip=True):
                stock_name = cols[0].get_text(strip=True)
                report_title = cols[1].get_text(strip=True)
                broker = cols[2].get_text(strip=True)
                results.append(f"[종목리포트-{broker}] {stock_name}: {report_title}")
                count += 1
            if count >= 10:
                break
    except Exception:
        pass

    return "\n".join(results)

# ==========================================
# 6. 차트 & 요약 표 대시보드 이미지 생성 모듈
# ==========================================
def create_dashboard_image(macro_list, stock_rows):
    setup_korean_font()
    fig = plt.figure(figsize=(12, 12), facecolor="#121826")
    gs = fig.add_gridspec(2, 1, height_ratios=[1.1, 1.3], hspace=0.32)

    today_str = datetime.now().strftime("%Y-%m-%d")
    fig.suptitle(f"⛏️ [곡괭이] 모닝 마켓 차트 & 관심종목 스코어보드 ({today_str})",
                 fontsize=18, fontweight="bold", color="#F8FAFC", y=0.96)

    # [상단] 글로벌 지수 + 관심종목 등락률 가로 막대 차트
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor("#1E293B")

    labels = [m["name"] for m in macro_list[:4]] + [s["name"] for s in stock_rows]
    changes = [m["change"] for m in macro_list[:4]] + [s["chg_1d"] for s in stock_rows]
    colors = ["#EF4444" if c >= 0 else "#3B82F6" for c in changes]

    bars = ax1.barh(labels[::-1], changes[::-1], color=colors[::-1], height=0.6)
    ax1.axvline(0, color="#94A3B8", linewidth=1, linestyle="--")
    ax1.set_title("주요 지수 및 관심 종목 일간 등락률 (%)", fontsize=13, color="#E2E8F0", pad=10, fontweight="bold")
    ax1.tick_params(colors="#E2E8F0", labelsize=10)
    for spine in ax1.spines.values():
        spine.set_color("#334155")

    for bar, val in zip(bars, changes[::-1]):
        x_pos = bar.get_width()
        offset = 0.15 if val >= 0 else -0.15
        ha = "left" if val >= 0 else "right"
        ax1.text(x_pos + offset, bar.get_y() + bar.get_height()/2, f"{val:+.2f}%",
                 va="center", ha=ha, color="#F8FAFC", fontsize=9, fontweight="bold")

    if changes:
        min_c, max_c = min(changes), max(changes)
        ax1.set_xlim(min(min_c - 2.5, -2.0), max(max_c + 2.5, 2.0))

    # [하단] 관심 종목 지표 요약 표
    ax2 = fig.add_subplot(gs[1])
    ax2.axis("off")
    ax2.set_title("관심 종목 핵심 지표 요약 표 (현재가 / 등락률 / RSI / 이평선 위치)",
                  fontsize=13, color="#E2E8F0", pad=12, fontweight="bold")

    col_labels = ["종목명", "현재가", "전일 대비", "5일 수익률", "RSI (14일)", "이평선 추세"]
    table_data = []
    cell_colors = []

    for s in stock_rows:
        rsi_status = f"{s['rsi']:.1f}"
        if s["rsi"] <= 35:
            rsi_status += " (과매도)"
        elif s["rsi"] >= 70:
            rsi_status += " (과열)"

        row = [
            s["name"],
            s["price_str"],
            f"{s['chg_1d']:+.2f}%",
            f"{s['chg_5d']:+.2f}%",
            rsi_status,
            s["trend"]
        ]
        table_data.append(row)

        chg_color = "#3B1D2E" if s["chg_1d"] >= 0 else "#172554"
        rsi_color = "#14532D" if s["rsi"] <= 35 else ("#7F1D1D" if s["rsi"] >= 70 else "#1E293B")
        cell_colors.append(["#1E293B", "#1E293B", chg_color, "#1E293B", rsi_color, "#1E293B"])

    if table_data:
        table = ax2.table(
            cellText=table_data,
            colLabels=col_labels,
            cellColours=cell_colors,
            colColours=["#334155"] * len(col_labels),
            loc="center",
            cellLoc="center"
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9.5)
        table.scale(1, 1.7)

        for (row_idx, col_idx), cell in table.get_celld().items():
            cell.set_edgecolor("#475569")
            cell.set_text_props(color="#F8FAFC", fontweight="bold" if row_idx == 0 or col_idx == 0 else "normal")

    img_path = "pickaxe_dashboard.png"
    plt.savefig(img_path, dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return img_path

# ==========================================
# 7. AI '곡괭이' 리포트 생성 모듈
# ==========================================
def generate_pickaxe_report(macro_text, stock_text, news_data, watchlist_news, report_data):
    client = genai.Client(api_key=GEMINI_API_KEY)
    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    watchlist_names_str = ", ".join(WATCHLIST.keys())

    prompt = f"""당신은 시장의 소음 속에서 금맥처럼 진짜 돈이 되는 투자 맥락과 수급의 속내를 파헤치는 전문 경제·주식 브리핑 채널 **'곡괭이'**의 수석 애널리스트입니다.
단순 뉴스 나열을 피하고, **'표면적 뉴스 이면의 진짜 이유(Why)'**, **'월가와 외국인·기관 수급의 이동 경로'**, **'관심 종목의 기술적·모멘텀 진단'**을 날카롭고 명쾌하게 브리핑해 주세요.

[오늘 날짜]: {today_str}

[1. 글로벌 매크로 및 지수 현황]
{macro_text}

[2. 내 관심 종목 주가 및 기술적 지표 현황 (RSI, 이평선)]
{stock_text}

[3. 관심 종목별 최신 뉴스]
{watchlist_news}

[4. 국내외 주요 증권/경제 뉴스 헤드라인]
{news_data}

[5. 오늘 자 국내 증권사 시황 및 종목 분석 리포트]
{report_data}

---
위 데이터를 종합하여 아래 양식으로 **⛏️ [곡괭이] 일일 경제·증시 심층 보고서**를 작성해 주세요.
(텔레그램 모바일 화면에서 가독성이 높도록 기호를 깔끔하게 정리하고, 표는 반드시 코드블록 ``` 을 사용해 줄 맞춤이 깨지지 않게 작성해 주세요.)

⛏️ **[곡괭이 모닝 브리핑] {today_str}**

🎯 **1. 오늘의 금맥 헤드라인 3선**
- (오늘 가장 중요한 핵심 이슈 3가지를 한 줄 요약)

📊 **2. 한눈에 보는 매크로 & 관심 종목 요약 표**
- 아래 항목을 모바일에서 보기 편한 고정폭 표(``` 코드블록 활용)로 깔끔하게 정리해 주세요:
  1) 글로벌 핵심 지표 요약 표 (지수명 / 현재치 / 등락률 / 한줄 해석)
  2) 관심 종목 스코어보드 표 (종목명 / 등락률 / RSI상태 / 핵심 모멘텀 한줄요약)

🌍 **3. 월가 & 글로벌 매크로 속내 파헤치기**
- 간밤 미국 증시(반도체·AI빅테크 등)와 금리·환율 움직임의 진짜 배경
- 오늘 한국 증시(KOSPI) 주도 섹터와 외국인 수급 연결고리

🔍 **4. [곡괭이 레이더] 관심 종목 집중 분석**
- 수집된 관심 종목({watchlist_names_str})을 섹터별(반도체·AI인프라 / 원전·전력기기 / 로봇)로 묶어 분석해 주세요.
- 각 종목의 **최신 뉴스·증권사 리포트 모멘텀**과 **현재 기술적 지표(RSI 과매도·과열 여부, 20일·120일선 위치)**를 결합해 구체적인 투자 포인트를 짚어주세요.

📅 **5. 오늘 장 실전 체크리스트 3가지**
- 오늘 장 시작 전·후로 투자자가 반드시 확인해야 할 핵심 대응 기준 3가지
"""

    candidate_models = [
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-3-pro-preview",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
    ]

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
    except Exception:
        pass

    last_error = None
    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e

    raise RuntimeError(f"사용 가능한 모델을 찾지 못했습니다: {last_error}")

# ==========================================
# 8. 텔레그램 이미지 + 텍스트 전송 모듈
# ==========================================
def send_telegram_photo(image_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as img:
        files = {"photo": img}
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}
        requests.post(url, data=data, files=files)

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
    print("1. 글로벌 매크로 및 관심 종목 데이터 수집 중...")
    macro_list, macro_text = get_macro_data()
    stock_rows, stock_text = get_watchlist_data()

    print("2. 뉴스 및 증권사 리포트(시황+종목) 수집 중...")
    news_data = get_economic_news()
    watchlist_news = get_watchlist_news()
    report_data = get_naver_reports()

    print("3. '곡괭이' 차트 & 요약 표 대시보드 이미지 생성 중...")
    img_path = create_dashboard_image(macro_list, stock_rows)
    send_telegram_photo(
        img_path,
        caption=f"⛏️ [곡괭이] {datetime.now().strftime('%Y-%m-%d')} 모닝 마켓 차트 & 관심종목 요약 표"
    )

    print("4. '곡괭이' 심층 분석 리포트 생성 및 전송 중...")
    report = generate_pickaxe_report(macro_text, stock_text, news_data, watchlist_news, report_data)
    send_telegram_message(report)
    print("전체 프로세스 완료!")

if __name__ == "__main__":
    main()
