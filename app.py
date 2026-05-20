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
    "오늘", "주요", "최근", "개편", "방안", "추진"
}

AI_MODEL_OPTIONS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash"
]


# =============================
# 유틸 함수
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


def unique_list(values):
    return list(dict.fromkeys([v for v in values if v]))


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

    return unique_list(required), unique_list(optional)


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

    return required_hit, score, ", ".join(unique_list(matched))


def filter_relevant_news(raw_df, base_query):
    if raw_df.empty:
        return raw_df

    required_keywords, optional_keywords = get_topic_rule(base_query)

    df = raw_df.copy()

    if not required_keywords:
        df["required_hit"] = True
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

    filtered_df = df[
        (df["required_hit"] == True) &
        (df["relevance_score"] >= 2)
    ].copy()

    filtered_df = filtered_df.sort_values(
        by=["group", "target_media", "relevance_score"],
        ascending=[True, True, False]
    )

    return filtered_df


def build_search_query(base_query, media, strict_phrase=False):
    if strict_phrase:
        return f'"{base_query}" {media}'
    return f"{base_query} {media}"


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


def collect_news_by_media_group(base_query, display_per_media=3, sort="sim", strict_phrase=False):
    all_rows = []

    fetch_per_media = max(10, display_per_media * 5)

    for group, media_list in TARGET_MEDIA.items():
        for media in media_list:
            search_query = build_search_query(base_query, media, strict_phrase=strict_phrase)

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
            .sort_values(
                by=["group", "target_media", "relevance_score"],
                ascending=[True, True, False]
            )
            .groupby(["group", "target_media"], as_index=False, group_keys=False)
            .head(display_per_media)
        )

    return filtered_df, raw_df


# =============================
# AI 입력 및 대체 브리핑
# =============================

def build_ai_input(df, max_per_group=4):
    compact_news_text = ""

    for group in ["progressive", "conservative", "center"]:
        group_df = df[df["group"] == group].head(max_per_group)
        compact_news_text += f"\n[{group}]\n"

        if group_df.empty:
            compact_news_text += "관련 기사 없음\n"
            continue

        for _, row in group_df.iterrows():
            media = str(row.get("target_media", ""))[:20]
            title = str(row.get("title", ""))[:90]
            description = str(row.get("description", ""))[:120]
            matched_keywords = str(row.get("matched_keywords", ""))[:80]

            compact_news_text += (
                f"- {media} | 키워드: {matched_keywords} | "
                f"제목: {title} | 요약: {description}\n"
            )

    return compact_news_text


def make_fallback_briefing(df, base_query, error=None):
    text = f"""
## 간이 프레임 브리핑

AI 요약 생성이 불안정하여, 수집된 기사 제목과 키워드를 기준으로 간이 브리핑을 표시합니다.

### 검색 주제
- {base_query}

### 그룹별 수집 현황
"""

    for group in ["progressive", "conservative", "center"]:
        group_df = df[df["group"] == group]
        text += f"\n#### {group}\n"

        if group_df.empty:
            text += "- 관련 기사 없음\n"
            continue

        keywords = []
        for value in group_df["matched_keywords"].dropna().tolist():
            for keyword in str(value).split(","):
                keyword = keyword.strip()
                if keyword:
                    keywords.append(keyword)

        top_keywords = unique_list(keywords)[:8]

        if top_keywords:
            text += "- 주요 관련 키워드: " + ", ".join(top_keywords) + "\n"

        for _, row in group_df.head(3).iterrows():
            media = row.get("target_media", "")
            title = row.get("title", "")
            text += f"- {media}: {title}\n"

    text += """

### 해석상 주의
- 이 내용은 AI가 생성한 정밀한 프레임 분석이 아니라, 수집된 기사 제목·요약·키워드 기반의 간이 정리입니다.
- 특정 그룹의 기사 수가 적으면 프레임 차이를 단정하기 어렵습니다.
- 더 정확한 비교를 위해서는 검색어를 구체화하는 것이 좋습니다.
"""

    if error is not None:
        text += f"\n오류 유형: `{type(error).__name__}`\n"

    return text


def generate_ai_briefing(df, base_query, preferred_model):
    gemini_api_key = get_secret("GEMINI_API_KEY")

    if not gemini_api_key:
        return """
## AI 프레임 비교 생성 실패

Gemini API 키가 설정되지 않았습니다.  
Streamlit Secrets에서 `GEMINI_API_KEY` 값을 확인하세요.
""", None, None

    client = genai.Client(api_key=gemini_api_key)

    compact_news_text = build_ai_input(df, max_per_group=4)

    prompt = f"""
너는 뉴스 제목과 요약문만 보고 보도 경향을 비교하는 분석 도우미다.

검색 주제: {base_query}

자료의 한계:
- 기사 본문 전문은 제공되지 않았다.
- 제목과 요약문만 제공되었다.
- progressive, conservative, center는 사용자가 설정한 비교 그룹명이다.

분석 원칙:
- 제목과 요약문에 있는 내용만 사용한다.
- 기사에 없는 사실을 만들지 않는다.
- 단정하지 않는다.
- 각 그룹의 표현, 강조점, 문제 정의 방식만 비교한다.
- 근거가 부족하면 부족하다고 쓴다.
- 서로 다른 이슈가 섞여 있으면 억지로 하나의 결론으로 묶지 않는다.

출력은 반드시 아래 형식으로만 작성한다.

## 핵심 이슈
- 

## 그룹별 보도 경향
### progressive
- 

### conservative
- 

### center
- 

## 프레임 차이
- 

## 해석상 주의할 점
- 

뉴스 목록:
{compact_news_text}
"""

    model_candidates = unique_list([preferred_model] + AI_MODEL_OPTIONS)
    last_error = None

    for model_name in model_candidates:
        for attempt in range(2):
            try:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config={
                            "temperature": 0.1,
                            "max_output_tokens": 1200,
                        }
                    )
                except TypeError:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )

                text = getattr(response, "text", None)

                if text and text.strip():
                    return text, model_name, None

            except Exception as e:
                last_error = e
                time.sleep(1.5)

    fallback = make_fallback_briefing(df, base_query, error=last_error)
    return fallback, None, last_error


# =============================
# 화면 구성
# =============================

with st.sidebar:
    st.header("검색 설정")

    base_query = st.text_input(
        "분석할 주제",
        value="돌봄 공백"
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

    strict_phrase = st.checkbox(
        "검색어를 따옴표로 묶어 엄격 검색",
        value=False
    )

    preferred_model = st.selectbox(
        "AI 모델",
        options=AI_MODEL_OPTIONS,
        index=0
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
        required_keywords, optional_keywords = get_topic_rule(base_query)

        with st.spinner("언론사 그룹별 뉴스를 수집하고 관련성 필터링을 적용하는 중입니다."):
            df, raw_df = collect_news_by_media_group(
                base_query=base_query,
                display_per_media=display_per_media,
                sort=sort,
                strict_phrase=strict_phrase
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

            with st.spinner("AI가 프레임 차이를 분석하는 중입니다."):
                summary, used_model, ai_error = generate_ai_briefing(
                    df=df,
                    base_query=base_query,
                    preferred_model=preferred_model
                )

            if used_model:
                st.caption(f"사용된 AI 모델: {used_model}")
            else:
                st.warning("AI 모델 응답이 실패하여 간이 브리핑을 표시합니다.")

            st.markdown(summary)

            st.subheader("참고 기사 링크")

            for group in ["progressive", "conservative", "center"]:
                group_df = df[df["group"] == group]

                if group_df.empty:
                    continue

                st.markdown(f"### {group}")

                for _, row in group_df.iterrows():
                    media = row.get("target_media", "")
                    title = row.get("title", "")
                    link = row.get("link", "")
                    st.markdown(f"- **{media}**: [{title}]({link})")

else:
    st.info("왼쪽에서 분석할 주제를 입력하고 버튼을 눌러주세요.")
