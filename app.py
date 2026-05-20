import os
import time
import html
import re
import requests
import pandas as pd
import streamlit as st
from google import genai


# =============================
# 기본 화면 설정
# =============================

st.set_page_config(
    page_title="아침 뉴스 프레임 브리핑",
    page_icon="📰",
    layout="wide"
)

st.title("📰 아침 뉴스 프레임 브리핑")
st.caption("네이버 뉴스 검색 API와 Gemini API를 활용한 언론사 그룹별 뉴스 프레임 비교 MVP입니다.")


# =============================
# 비교 그룹 설정
# =============================

TARGET_MEDIA = {
    "progressive": ["한겨레", "경향신문", "오마이뉴스"],
    "conservative": ["조선일보", "중앙일보", "동아일보"],
    "center": ["연합뉴스", "한국일보", "서울신문", "뉴스1", "뉴시스"]
}


# =============================
# 주제별 관련 키워드 설정
# =============================

TOPIC_KEYWORDS = {
    "저출산": [
        "저출산", "저출생", "출산율", "출생률", "합계출산율",
        "인구", "인구절벽", "인구소멸", "육아", "양육", "보육",
        "돌봄", "난임", "출산", "출생", "아이", "아동", "청년"
    ],
    "저출생": [
        "저출산", "저출생", "출산율", "출생률", "합계출산율",
        "인구", "인구절벽", "인구소멸", "육아", "양육", "보육",
        "돌봄", "난임", "출산", "출생", "아이", "아동", "청년"
    ],
    "출산율": [
        "저출산", "저출생", "출산율", "출생률", "합계출산율",
        "인구", "육아", "양육", "보육", "돌봄", "출산", "출생"
    ],
    "국민연금": [
        "국민연금", "연금", "보험료율", "소득대체율",
        "노후소득", "기금", "연금개혁", "재정안정", "노후"
    ],
    "연금": [
        "국민연금", "연금", "보험료율", "소득대체율",
        "노후소득", "기금", "연금개혁", "재정안정", "노후"
    ],
    "의료개혁": [
        "의료개혁", "의대", "의사", "전공의", "병원",
        "건강보험", "필수의료", "의료", "응급실", "수가"
    ],
    "의료": [
        "의료개혁", "의대", "의사", "전공의", "병원",
        "건강보험", "필수의료", "의료", "응급실", "수가"
    ],
    "돌봄": [
        "돌봄", "요양", "간병", "보육", "육아",
        "장기요양", "사회서비스", "복지", "가족돌봄", "돌봄공백"
    ],
    "복지": [
        "복지", "사회보장", "급여", "수급", "취약계층",
        "사회서비스", "지원", "보장", "복지정책"
    ],
    "사회보장": [
        "사회보장", "복지", "급여", "수급", "취약계층",
        "사회서비스", "지원", "보장", "보장제도"
    ],
    "부동산": [
        "부동산", "집값", "주택", "전세", "월세",
        "청약", "공급", "재건축", "재개발", "아파트"
    ],
    "노동": [
        "노동", "근로", "임금", "노조", "고용",
        "일자리", "근로시간", "노동시간", "최저임금"
    ]
}

GENERIC_WORDS = {
    "정책", "대책", "문제", "이슈", "뉴스", "관련", "현안",
    "논란", "분석", "전망", "정부", "국회", "사회", "경제",
    "오늘", "주요", "최근"
}


# =============================
# 유틸 함수
# =============================

def clean_text(text):
    text = html.unescape(str(text))
    text = re.sub(r"<.*?>", "", text)
    return text.strip()


def get_secret(name):
    """
    Streamlit Cloud에서는 st.secrets에서 읽고,
    로컬 실행 시에는 환경변수에서 읽는다.
    """
    try:
        value = st.secrets[name]
        if value:
            return str(value)
    except Exception:
        pass

    return os.getenv(name, "")


def get_relevance_keywords(base_query):
    """
    사용자가 입력한 검색어와 미리 정의한 주제별 키워드를 합쳐
    관련성 필터링에 사용할 키워드 목록을 만든다.
    """
    keywords = []

    # 사용자가 입력한 단어 중 너무 일반적인 단어는 제외
    for word in base_query.replace(",", " ").split():
        word = word.strip()
        if len(word) >= 2 and word not in GENERIC_WORDS:
            keywords.append(word)

    # 주제별 관련 키워드 추가
    for topic, topic_words in TOPIC_KEYWORDS.items():
        if topic in base_query:
            keywords.extend(topic_words)

    # 중복 제거
    keywords = list(dict.fromkeys(keywords))

    return keywords


def relevance_score(row, keywords):
    """
    제목과 요약문 안에 관련 키워드가 몇 개 들어 있는지 계산한다.
    """
    text = f"{row.get('title', '')} {row.get('description', '')}"

    score = 0
    for keyword in keywords:
        if keyword in text:
            score += 1

    return score


def filter_relevant_news(df, base_query):
    """
    검색 주제와 관련성이 낮은 기사를 제거한다.
    단, 너무 엄격하게 걸러져서 아무 기사도 남지 않으면 원래 결과를 반환한다.
    """
    if df.empty:
        return df

    keywords = get_relevance_keywords(base_query)

    if not keywords:
        df["relevance_score"] = 0
        return df

    df = df.copy()
    df["relevance_score"] = df.apply(lambda row: relevance_score(row, keywords), axis=1)

    filtered_df = df[df["relevance_score"] > 0].copy()

    # 관련 기사만 먼저 정렬
    filtered_df = filtered_df.sort_values(
        by=["group", "target_media", "relevance_score"],
        ascending=[True, True, False]
    )

    # 전부 걸러지면 원래 결과 반환
    if filtered_df.empty:
        return df

    return filtered_df


# =============================
# 네이버 뉴스 검색
# =============================

def search_naver_news(query, display=3, sort="date"):
    naver_client_id = get_secret("NAVER_CLIENT_ID")
    naver_client_secret = get_secret("NAVER_CLIENT_SECRET")

    if not naver_client_id or not naver_client_secret:
        st.error("네이버 API 키가 설정되지 않았습니다. Streamlit Secrets를 확인하세요.")
        return pd.DataFrame()

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

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=15
        )
    except Exception as e:
        st.error(f"네이버 API 요청 중 오류가 발생했습니다: {type(e).__name__}")
        return pd.DataFrame()

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
    """
    검색어 + 언론사명 조합으로 그룹별 뉴스를 수집한다.
    예: 저출산 정책 한겨레, 저출산 정책 조선일보, 저출산 정책 연합뉴스
    """
    all_rows = []

    for group, media_list in TARGET_MEDIA.items():
        for media in media_list:
            search_query = f"{base_query} {media}"

            temp_df = search_naver_news(
                query=search_query,
                display=display_per_media,
                sort="date"
            )

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

    # 관련성 필터 적용
    result_df = filter_relevant_news(result_df, base_query)

    return result_df


# =============================
# Gemini 요약
# =============================

def summarize_with_gemini(df, base_query):
    gemini_api_key = get_secret("GEMINI_API_KEY")

    if not gemini_api_key:
        return """
## AI 프레임 비교 생성 실패

Gemini API 키가 설정되지 않았습니다.  
Streamlit Secrets에서 `GEMINI_API_KEY` 값을 확인하세요.
"""

    client = genai.Client(api_key=gemini_api_key)

    max_articles_per_group = 3
    grouped_news_text = ""

    for group in ["progressive", "conservative", "center"]:
        group_df = df[df["group"] == group].head(max_articles_per_group)
        grouped_news_text += f"\n\n### {group} 그룹\n"

        if group_df.empty:
            grouped_news_text += "- 수집된 뉴스 없음\n"
            continue

        for _, row in group_df.iterrows():
            title = str(row.get("title", ""))[:120]
            description = str(row.get("description", ""))[:220]
            link = str(row.get("link", ""))
            target_media = str(row.get("target_media", ""))

            grouped_news_text += f"""
- 언론사 검색 기준: {target_media}
- 제목: {title}
- 요약: {description}
- 링크: {link}
"""

    prompt = f"""
너는 뉴스 프레임 비교 에이전트다.

검색 주제: {base_query}

아래 뉴스 목록은 사용자가 설정한 언론사 그룹별 뉴스 검색 결과다.
기사 본문 전문이 아니라 제목과 요약문만 제공되었다.

분석 원칙:
- 제목과 요약문에 근거해서만 분석한다.
- 기사에 없는 사실은 만들지 않는다.
- 단정적 표현을 피한다.
- progressive, conservative, center는 사용자가 설정한 비교 그룹명이다.
- 정치적 판단이 아니라 보도 강조점, 표현, 프레임 차이를 비교한다.
- 같은 이슈가 섞여 있으면 그 한계를 밝힌다.
- 특정 그룹에 관련 기사가 부족하면 부족하다고 명시한다.

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

    last_error = None

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            if response.text:
                return response.text

            return """
## AI 프레임 비교 생성 실패

Gemini가 빈 응답을 반환했습니다.  
검색어를 조금 더 구체적으로 바꿔 다시 시도하세요.
"""

        except Exception as e:
            last_error = e
            time.sleep(2)

    return f"""
## AI 프레임 비교 생성 실패

뉴스 수집은 정상적으로 완료되었지만, Gemini 요약 생성 단계에서 오류가 발생했습니다.

### 현재 상태
- 네이버 뉴스 수집: 정상
- 뉴스 목록 표시: 정상
- Gemini 요약 생성: 실패

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

### 오류 유형
`{type(last_error).__name__}`
"""


# =============================
# 화면 구성
# =============================

with st.sidebar:
    st.header("검색 설정")

    base_query = st.text_input(
        "분석할 주제",
        value="돌봄"
    )

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
    if not base_query.strip():
        st.warning("분석할 주제를 입력해주세요.")
    else:
        keywords = get_relevance_keywords(base_query)

        with st.spinner("언론사 그룹별 뉴스를 수집하는 중입니다."):
            df = collect_news_by_media_group(
                base_query=base_query,
                display_per_media=display_per_media
            )

        if df.empty:
            st.error("수집된 뉴스가 없습니다. 검색어를 바꿔보세요.")
        else:
            st.subheader("수집된 뉴스 목록")

            if keywords:
                st.caption("관련성 필터 키워드: " + ", ".join(keywords))

            display_columns = [
                "group",
                "target_media",
                "title",
                "description",
                "pubDate",
                "link"
            ]

            if "relevance_score" in df.columns:
                display_columns.insert(2, "relevance_score")

            st.dataframe(
                df[display_columns],
                use_container_width=True
            )

            st.subheader("AI 프레임 비교 브리핑")

            with st.spinner("Gemini가 프레임 차이를 분석하는 중입니다."):
                summary = summarize_with_gemini(df, base_query)
                st.markdown(summary)

else:
    st.info("왼쪽에서 분석할 주제를 입력하고 버튼을 눌러주세요.")
