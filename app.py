import streamlit as st
import requests
import pandas as pd
import html
import re
from google import genai

st.set_page_config(
    page_title="아침 뉴스 프레임 브리핑",
    page_icon="📰",
    layout="wide"
)

st.title("📰 아침 뉴스 프레임 브리핑")
st.caption("네이버 뉴스 검색 API와 Gemini API를 활용한 언론사 그룹별 뉴스 프레임 비교 MVP입니다.")

TARGET_MEDIA = {
    "progressive": ["한겨레", "경향신문", "오마이뉴스"],
    "conservative": ["조선일보", "중앙일보", "동아일보"],
    "center": ["연합뉴스", "한국일보", "서울신문", "뉴스1", "뉴시스"]
}

def clean_text(text):
    text = html.unescape(str(text))
    text = re.sub(r"<.*?>", "", text)
    return text.strip()

def search_naver_news(query, display=3, sort="date"):
    naver_client_id = st.secrets["NAVER_CLIENT_ID"]
    naver_client_secret = st.secrets["NAVER_CLIENT_SECRET"]

    url = "https://openapi.naver.com/v1/search/news.json"

    headers = {
        "X-Naver-Client-Id": naver_client_id,
        "X-Naver-Client-Secret": naver_client_secret,
    }

    params = {
        "query": query,
        "display": display,
        "start": 1,
        "sort": sort
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        st.error(f"네이버 API 오류: {response.status_code}")
        st.code(response.text)
        return pd.DataFrame()

    data = response.json()
    rows = []

    for item in data.get("items", []):
        rows.append({
            "title": clean_text(item.get("title", "")),
            "description": clean_text(item.get("description", "")),
            "link": item.get("link", ""),
            "originallink": item.get("originallink", ""),
            "pubDate": item.get("pubDate", "")
        })

    return pd.DataFrame(rows)

def collect_news_by_media_group(base_query, display_per_media=3):
    all_rows = []

    for group, media_list in TARGET_MEDIA.items():
        for media in media_list:
            search_query = f"{base_query} {media}"
            temp_df = search_naver_news(search_query, display=display_per_media)

            if temp_df.empty:
                continue

            temp_df["group"] = group
            temp_df["target_media"] = media
            temp_df["search_query"] = search_query

            all_rows.append(temp_df)

    if not all_rows:
        return pd.DataFrame()

    result_df = pd.concat(all_rows, ignore_index=True)
    result_df = result_df.drop_duplicates(subset=["link"])

    return result_df

def summarize_with_gemini(df, base_query):
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=gemini_api_key)

    grouped_news_text = ""

    for group in ["progressive", "conservative", "center"]:
        group_df = df[df["group"] == group]
        grouped_news_text += f"\n\n### {group} 그룹\n"

        if group_df.empty:
            grouped_news_text += "- 수집된 뉴스 없음\n"
            continue

        for _, row in group_df.iterrows():
            grouped_news_text += f"""
- 언론사 검색 기준: {row["target_media"]}
- 제목: {row["title"]}
- 요약: {row["description"]}
- 링크: {row["link"]}
"""

    prompt = f"""
너는 뉴스 프레임 비교 에이전트다.

검색 주제: {base_query}

아래 뉴스 목록은 사용자가 설정한 언론사 그룹별로 수집된 뉴스 검색 결과다.
기사 본문 전문이 아니라 제목과 요약문만 제공되었다.

원칙:
- 제목과 요약문에 근거해서만 분석하라.
- 기사에 없는 사실을 만들어내지 말라.
- 단정적인 표현을 피하라.
- progressive, conservative, center는 사용자가 설정한 비교 그룹명이다.
- 정치적 판단이 아니라 보도 프레임, 강조점, 표현 차이를 비교하라.

출력 형식:

## 오늘의 주요 이슈

## 공통적으로 확인되는 내용

## progressive 그룹 보도 경향

## conservative 그룹 보도 경향

## center 그룹 보도 경향

## 프레임 차이

## 근거 부족 또는 주의할 점

## 참고 기사 링크

뉴스 목록:
{grouped_news_text}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return response.text

with st.sidebar:
    st.header("검색 설정")

    base_query = st.text_input("분석할 주제", value="돌봄")

    display_per_media = st.slider(
        "언론사별 가져올 뉴스 수",
        min_value=1,
        max_value=5,
        value=3
    )

    run_button = st.button("뉴스 수집 및 프레임 비교")

    st.markdown("---")
    st.markdown("### 비교 그룹")
    st.write("progressive:", ", ".join(TARGET_MEDIA["progressive"]))
    st.write("conservative:", ", ".join(TARGET_MEDIA["conservative"]))
    st.write("center:", ", ".join(TARGET_MEDIA["center"]))

if run_button:
    with st.spinner("뉴스를 수집하는 중입니다."):
        df = collect_news_by_media_group(base_query, display_per_media)

    if df.empty:
        st.error("수집된 뉴스가 없습니다. 검색어를 바꿔보세요.")
    else:
        st.subheader("수집 결과")
        st.dataframe(
            df[["group", "target_media", "title", "description", "pubDate", "link"]],
            use_container_width=True
        )

st.subheader("AI 프레임 비교 브리핑")

with st.spinner("Gemini가 프레임 차이를 분석하는 중입니다."):
    try:
        summary = summarize_with_gemini(df, base_query)
        st.markdown(summary)

    except Exception as e:
        st.warning("뉴스 수집은 완료되었지만, AI 프레임 비교 생성 중 오류가 발생했습니다.")

        st.markdown("""
### 가능한 원인
- Gemini API 서버의 일시적 오류
- 특정 검색어에서 생성된 뉴스 목록이 너무 길거나 불안정함
- Gemini API 사용량 제한 또는 일시적 응답 실패
- 검색 결과가 서로 다른 이슈로 많이 섞여 요약 요청이 불안정해짐

### 바로 해볼 조치
1. 검색어를 더 구체적으로 바꿔보세요.  
   예: `저출산` → `저출산 대책`, `저출생 정책`, `출산율 정책`

2. 언론사별 가져올 뉴스 수를 1로 줄여보세요.

3. 잠시 후 다시 실행해보세요.
""")

        st.caption(f"오류 유형: {type(e).__name__}")
else:
    st.info("왼쪽에서 분석할 주제를 입력하고 버튼을 눌러주세요.")
