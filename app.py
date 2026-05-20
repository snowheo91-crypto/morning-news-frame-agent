import os
import time
import html
import re
import requests
import pandas as pd
import streamlit as st
from google import genai


# =============================
# 화면 설정
# =============================

st.set_page_config(
    page_title="아침 뉴스 프레임 브리핑",
    page_icon="📰",
    layout="wide"
)

st.title("📰 아침 뉴스 프레임 브리핑")
st.caption("네이버 뉴스 검색 API와 Gemini API를 활용한 언론사 그룹별 뉴스 프레임 비교 MVP입니다.")


# =============================
# 비교 그룹
# =============================

TARGET_MEDIA = {
    "progressive": ["한겨레", "경향신문", "오마이뉴스"],
    "conservative": ["조선일보", "중앙일보", "동아일보"],
    "center": ["연합뉴스", "한국일보", "서울신문", "뉴스1", "뉴시스"]
}


# =============================
# 주제별 관련성 규칙
# required: 반드시 제목/요약에 들어가야 하는 핵심어
# optional: 있으면 관련성 점수를 높이는 보조어
# =============================

TOPIC_RULES = {
    "저출산": {
        "required": ["저출산", "저출생", "출산율", "출생률", "합계출산율"],
        "optional": ["출산", "출생", "난임", "육아", "양육", "보육", "돌봄", "아동", "아이"]
    },
    "저출생": {
        "required": ["저출산", "저출생", "출산율", "출생률", "합계출산율"],
        "optional": ["출산", "출생", "난임", "육아", "양육", "보육", "돌봄", "아동", "아이"]
    },
    "출산율": {
        "required": ["저출산", "저출생", "출산율", "출생률", "합계출산율"],
        "optional": ["출산", "출생", "난임", "육아", "양육", "보육", "돌봄"]
    },
    "국민연금": {
        "required": ["국민연금", "연금개혁", "연금"],
        "optional": ["보험료율", "소득대체율", "기금", "노후소득", "재정안정", "수급"]
    },
    "연금": {
        "required": ["국민연금", "연금개혁", "연금"],
        "optional": ["보험료율", "소득대체율", "기금", "노후소득", "재정안정", "수급"]
    },
    "의료개혁": {
        "required": ["의료개혁", "의대", "전공의", "필수의료", "의료"],
        "optional": ["의사", "병원", "응급실", "건강보험", "수가", "진료", "의료계"]
    },
    "의료": {
        "required": ["의료개혁", "의대", "전공의", "필수의료", "의료"],
        "optional": ["의사", "병원", "응급실", "건강보험", "수가", "진료", "의료계"]
    },
    "돌봄": {
        "required": ["돌봄", "돌봄공백", "가족돌봄"],
        "optional": ["요양", "간병", "보육", "육아", "장기요양", "사회서비스", "복지"]
    },
    "복지": {
        "required": ["복지", "사회보장", "복지정책"],
        "optional": ["급여", "수급", "취약계층", "사회서비스", "지원", "보장"]
    },
    "사회보장": {
        "required": ["사회보장", "복지", "보장제도"],
        "optional": ["급여", "수급", "취약계층", "사회서비스", "지원"]
    },
    "부동산": {
        "required": ["부동산", "집값", "주택", "전세", "월세"],
        "optional": ["청약", "공급", "재건축", "재개발", "아파트", "임대"]
    },
    "노동": {
        "required": ["노동", "근로", "고용", "일자리"],
        "optional": ["임금", "노조", "근로시간", "노동시간", "최저임금"]
    }
}

GENERIC_WORDS = {
    "정책", "대책", "문제", "이슈", "뉴스", "관련", "현안",
    "논란", "분석", "전망", "정부", "국회", "사회", "경제",
    "오늘", "주요", "최근", "개편", "방안"
}


# =============================
# 유틸
# =============================

def clean_text(text):
    text = html.unescape(str(text))
    text = re.sub(r"<.*?>", "", text)
    return text.strip()


def get_secret(name):
    try:
        value = st.secrets[name]
        if value:
            return str(value)
    except Exception:
        pass

    return os.getenv(name, "")


def get_topic_rule(base_query):
    required = []
    optional = []

    for topic, rule in TOPIC_RULES.items():
        if topic in base_query:
            required.extend(rule["required"])
            optional.extend(rule["optional"])

    query_words = []
    for word in base_query.replace(",", " ").split():
        word = word.strip()
        if len(word) >= 2 and word not in GENERIC_WORDS:
            query_words.append(word)

    if required:
        required.extend(query_words)
    else:
        required = query_words

    required = list(dict.fromkeys(required))
    optional = list(dict.fromkeys(optional))

    return required, optional


def score_article(row, required_keywords, optional_keywords):
    title = str(row.get("title", ""))
    description = str(row.get("description", ""))
    text = f"{title} {description}"

    score = 0
    matched = []

    required_hit = False

    for keyword in required_keywords:
        if keyword in title:
            score += 3
            required_hit = True
            matched.append(keyword)
        elif keyword in description:
            score += 2
            required_hit = True
            matched.append(keyword)

    for keyword in optional_keywords:
        if keyword in title:
            score += 1
            matched.append(keyword)
        elif keyword in description:
            score += 0.5
            matched.append(keyword)

    matched = list(dict.fromkeys(matched))

    return required_hit, score, ", ".join(matched)


def filter_relevant_news(raw_df, base_query):
    if raw_df.empty:
        return raw_df

    required_keywords, optional_keywords = get_topic_rule(base_query)

    df = raw_df.copy()

    if not required_keywords:
        df["relevance_score"] = 0
        df["matched_keywords"] = ""
        return df

    results = df.apply(
        lambda row: score_article(row, required_keywords, optional_keywords),
        axis=1
    )

    df["required_hit"] = [r[0] for r in results]
    df["relevance_score"] = [r[1] for r in results]
    df["matched_keywords"] = [r[2] for r in results]

    # 핵심어가 제목/요약에 실제로 들어간 기사만 남김
    filtered_df = df[
        (df["required_hit"] == True) &
        (df["relevance_score"] >= 2)
    ].copy()

    filtered_df = filtered_df.sort_values(
        by=["group", "target_media", "relevance_score"],
        ascending=[True, True, False]
    )

    return filtered_df


# =============================
# 네이버 뉴스 검색
# =============================

def search_naver_news(query, display=10, sort="sim"):
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


def collect_news_by_media_group(base_query, display_per_media=3, sort="sim"):
    all_rows = []

    # 최종 표시 수보다 많이 가져온 뒤, 관련성 필터로 걸러냄
    fetch_per_media = max(10, display_per_media * 5)

    for group, media_list in TARGET_MEDIA.items():
        for media in media_list:
            search_query = f"{base_query} {media}"

            temp_df = search_naver_news(
                query=search_query,
                display=fetch_per_media,
                sort=sort
            )

            if temp_df.empty:
                continue

            temp_df["group"] = group
            temp_df["target_media"] = media
            temp_df["search_query"] = search_query

            all_rows.append(temp_df)

    if not all_rows:
        return pd.DataFrame(), pd.DataFrame()

    raw_df = pd.concat(all_rows, ignore_index=True)
    raw_df = raw_df.drop_duplicates(subset=["link"])

    filtered_df = filter_relevant_news(raw_df, base_query)

    if not filtered_df.empty:
        filtered_df = (
            filtered_df
            .sort_values(by=["group", "target_media", "relevance_score"], ascending=[True, True, False])
            .groupby(["group", "target_media"], as_index=False, group_keys=False)
            .head(display_per_media)
        )

    return filtered_df, raw_df


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

    grouped_news_text = ""

    for group in ["progressive", "conservative", "center"]:
        group_df = df[df["group"] == group].head(5)
        grouped_news_text += f"\n\n### {group} 그룹\n"

        if group_df.empty:
            grouped_news_text += "- 수집된 관련 뉴스 없음\n"
            continue

        for _, row in group_df.iterrows():
            title = str(row.get("title", ""))[:120]
            description = str(row.get("description", ""))[:220]
            link = str(row.get("link", ""))
            target_media = str(row.get("target_media", ""))
            matched_keywords = str(row.get("matched_keywords", ""))

            grouped_news_text += f"""
- 언론사 검색 기준: {target_media}
- 관련 키워드: {matched_keywords}
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
- 특정 그룹에 관련 기사가 부족하면 부족하다고 명시한다.
- 서로 다른 이슈가 섞여 있으면 무리하게 하나의 결론으로 묶지 않는다.

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
- 관련 기사 필터링: 정상
- Gemini 요약 생성: 실패

### 가능한 원인
- Gemini API 서버의 일시적 오류
- 특정 검색어에서 Gemini 응답이 실패함
- Gemini API 사용량 제한 또는 일시적 장애

### 바로 해볼 조치
1. 검색어를 더 구체적으로 바꿔보세요.
2. 잠시 후 다시 실행해보세요.
3. 다른 주제에서도 계속 실패하면 Gemini API 키 상태를 확인하세요.

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
        "언론사별 최종 표시 뉴스 수",
        min_value=1,
        max_value=5,
        value=3
    )

    sort_label = st.selectbox(
        "뉴스 검색 정렬 방식",
        options=["정확도순", "최신순"],
        index=0
    )

    sort = "sim" if sort_label == "정확도순" else "date"

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
        required_keywords, optional_keywords = get_topic_rule(base_query)

        with st.spinner("언론사 그룹별 뉴스를 수집하고 관련성 필터링을 적용하는 중입니다."):
            df, raw_df = collect_news_by_media_group(
                base_query=base_query,
                display_per_media=display_per_media,
                sort=sort
            )

        st.subheader("수집 및 필터링 결과")

        col1, col2, col3 = st.columns(3)
        col1.metric("전체 수집 기사 수", len(raw_df))
        col2.metric("관련 기사 수", len(df))
        col3.metric("검색 정렬", sort_label)

        if required_keywords:
            st.caption("필수 관련 키워드: " + ", ".join(required_keywords))
        if optional_keywords:
            st.caption("보조 관련 키워드: " + ", ".join(optional_keywords))

        if df.empty:
            st.warning("관련성 필터를 통과한 뉴스가 없습니다. 검색어를 더 구체적으로 바꾸거나 정렬 방식을 바꿔보세요.")

            with st.expander("필터링 전 원본 수집 결과 보기"):
                if raw_df.empty:
                    st.write("원본 수집 결과도 없습니다.")
                else:
                    st.dataframe(
                        raw_df[
                            [
                                "group",
                                "target_media",
                                "title",
                                "description",
                                "pubDate",
                                "link"
                            ]
                        ],
                        use_container_width=True
                    )

        else:
            st.subheader("관련성 필터를 통과한 뉴스 목록")

            st.dataframe(
                df[
                    [
                        "group",
                        "target_media",
                        "relevance_score",
                        "matched_keywords",
                        "title",
                        "description",
                        "pubDate",
                        "link"
                    ]
                ],
                use_container_width=True
            )

            st.subheader("AI 프레임 비교 브리핑")

            with st.spinner("Gemini가 프레임 차이를 분석하는 중입니다."):
                summary = summarize_with_gemini(df, base_query)
                st.markdown(summary)

else:
    st.info("왼쪽에서 분석할 주제를 입력하고 버튼을 눌러주세요.")
