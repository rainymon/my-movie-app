import streamlit as st
import pandas as pd
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import plotly.express as px


# ---------------------------------------------------------
# 1. 스트림릿 페이지 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="어제의 박스오피스",
    page_icon="🎬",
    layout="wide",
)


# ---------------------------------------------------------
# 2. KOBIS 일별 박스오피스 데이터를 불러오는 함수
#
# 같은 날짜의 데이터를 계속 요청하지 않도록
# 1시간 동안 결과를 캐시에 저장합니다.
# ---------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_boxoffice_data(api_key: str, target_date: str) -> pd.DataFrame:
    # KOBIS 일별 박스오피스 공식 API 주소
    api_url = (
        "http://www.kobis.or.kr/kobisopenapi/webservice/rest/"
        "boxoffice/searchDailyBoxOfficeList.json"
    )

    # API에 전달할 요청 변수
    params = {
        "key": api_key,
        "targetDt": target_date,
    }

    try:
        # timeout을 설정해 서버 응답이 너무 오래 걸릴 경우 요청을 중단합니다.
        response = requests.get(
            api_url,
            params=params,
            timeout=15,
        )

        # 404, 500 등의 HTTP 오류가 발생하면 예외를 발생시킵니다.
        response.raise_for_status()

    except requests.exceptions.Timeout as error:
        raise RuntimeError(
            "KOBIS 서버의 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
        ) from error

    except requests.exceptions.ConnectionError as error:
        raise RuntimeError(
            "KOBIS 서버에 연결하지 못했습니다. "
            "인터넷 연결 상태를 확인한 뒤 다시 시도해 주세요."
        ) from error

    except requests.exceptions.HTTPError as error:
        raise RuntimeError(
            f"KOBIS API 요청 중 HTTP 오류가 발생했습니다. "
            f"오류 코드: {response.status_code}"
        ) from error

    except requests.exceptions.RequestException as error:
        raise RuntimeError(
            "KOBIS API 요청 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요."
        ) from error

    try:
        # 서버가 보낸 JSON 응답을 파이썬 딕셔너리로 변환합니다.
        result = response.json()

    except ValueError as error:
        raise RuntimeError(
            "KOBIS 서버에서 올바르지 않은 형식의 응답을 받았습니다."
        ) from error

    # 인증키 오류 등의 문제가 있으면 faultInfo가 전달될 수 있습니다.
    if "faultInfo" in result:
        fault_info = result.get("faultInfo", {})

        message = (
            fault_info.get("message")
            or fault_info.get("errorMessage")
            or "인증키 또는 요청 정보를 확인해 주세요."
        )

        raise RuntimeError(f"KOBIS API 오류: {message}")

    # 정상 응답에서 영화 목록을 꺼냅니다.
    boxoffice_result = result.get("boxOfficeResult", {})
    movie_list = boxoffice_result.get("dailyBoxOfficeList", [])

    if not movie_list:
        raise RuntimeError(
            "조회된 박스오피스 데이터가 없습니다. "
            "KOBIS 집계가 아직 완료되지 않았을 수 있습니다."
        )

    # 영화 목록을 판다스 데이터프레임으로 변환합니다.
    df = pd.DataFrame(movie_list)

    # 화면에 사용할 열만 선택합니다.
    required_columns = [
        "rank",
        "movieNm",
        "openDt",
        "audiCnt",
        "audiAcc",
        "scrnCnt",
    ]

    missing_columns = [
        column for column in required_columns if column not in df.columns
    ]

    if missing_columns:
        raise RuntimeError(
            "KOBIS 응답에 필요한 데이터가 포함되어 있지 않습니다. "
            f"누락 항목: {', '.join(missing_columns)}"
        )

    df = df[required_columns].copy()

    # KOBIS의 숫자는 문자열로 오기 때문에 실제 숫자 자료형으로 변환합니다.
    numeric_columns = [
        "rank",
        "audiCnt",
        "audiAcc",
        "scrnCnt",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        ).fillna(0).astype(int)

    # 순위 숫자를 기준으로 오름차순 정렬합니다.
    df = df.sort_values(
        by="rank",
        ascending=True,
    ).reset_index(drop=True)

    return df


# ---------------------------------------------------------
# 3. 한국 시간 기준으로 어제 날짜 계산
#
# 배포 서버의 시간이 UTC나 다른 국가 시간이어도
# 반드시 Asia/Seoul 시간을 기준으로 계산합니다.
# ---------------------------------------------------------
korea_timezone = ZoneInfo("Asia/Seoul")
korea_now = datetime.now(korea_timezone)
yesterday = korea_now.date() - timedelta(days=1)

# API 요청에 사용할 날짜: yyyymmdd
target_date = yesterday.strftime("%Y%m%d")

# 화면에 보여줄 날짜: yyyy년 mm월 dd일
display_date = yesterday.strftime("%Y년 %m월 %d일")


# ---------------------------------------------------------
# 4. 화면 제목
# ---------------------------------------------------------
st.title("🎬 어제의 박스오피스 분석 대시보드")
st.caption(
    f"한국 시간 기준 {display_date} 일별 박스오피스입니다. "
    "자료 출처: 영화진흥위원회 KOBIS"
)


# ---------------------------------------------------------
# 5. Streamlit Secrets에서 인증키 불러오기
# ---------------------------------------------------------
try:
    kobis_key = st.secrets["KOBIS_KEY"]

except KeyError:
    st.error(
        "KOBIS 인증키가 등록되지 않았습니다. "
        "Streamlit Cloud의 Secrets에 `KOBIS_KEY`를 등록해 주세요."
    )

    st.code(
        'KOBIS_KEY = "여기에_발급받은_인증키를_입력하세요"',
        language="toml",
    )

    st.stop()


# ---------------------------------------------------------
# 6. 박스오피스 데이터 불러오기
# ---------------------------------------------------------
try:
    with st.spinner("어제의 박스오피스 데이터를 불러오는 중입니다..."):
        boxoffice_df = load_boxoffice_data(
            api_key=kobis_key,
            target_date=target_date,
        )

except RuntimeError as error:
    st.error(str(error))
    st.info(
        "인증키가 올바르게 등록되었는지 확인하고, "
        "잠시 후 페이지를 새로고침해 주세요."
    )
    st.stop()

except Exception:
    # 예상하지 못한 오류의 세부 내용은 화면에 그대로 노출하지 않습니다.
    st.error(
        "데이터를 처리하는 중 예상하지 못한 문제가 발생했습니다. "
        "잠시 후 다시 시도해 주세요."
    )
    st.stop()


# ---------------------------------------------------------
# 7. 1위 영화 지표 카드
# ---------------------------------------------------------
number_one = boxoffice_df.iloc[0]

st.subheader("🏆 어제의 박스오피스 1위")

metric_column1, metric_column2, metric_column3, metric_column4 = st.columns(4)

with metric_column1:
    st.metric(
        label="영화명",
        value=number_one["movieNm"],
    )

with metric_column2:
    st.metric(
        label="어제 관객수",
        value=f"{number_one['audiCnt']:,}명",
    )

with metric_column3:
    st.metric(
        label="누적 관객수",
        value=f"{number_one['audiAcc']:,}명",
    )

with metric_column4:
    st.metric(
        label="스크린수",
        value=f"{number_one['scrnCnt']:,}개",
    )


st.divider()


# ---------------------------------------------------------
# 8. 관객수 상위 5편 막대그래프
# ---------------------------------------------------------
st.subheader("📊 관객수 상위 5편")

# 관객수가 많은 순서대로 정렬한 뒤 상위 5개만 선택합니다.
top5_df = (
    boxoffice_df.sort_values(
        by="audiCnt",
        ascending=False,
    )
    .head(5)
    .copy()
)

# 가로 막대그래프에서 관객수가 가장 많은 영화가 위에 오도록
# 다시 오름차순으로 정렬합니다.
top5_chart_df = top5_df.sort_values(
    by="audiCnt",
    ascending=True,
)

figure = px.bar(
    top5_chart_df,
    x="audiCnt",
    y="movieNm",
    orientation="h",
    text="audiCnt",
    labels={
        "audiCnt": "관객수",
        "movieNm": "영화명",
    },
    title=f"{display_date} 관객수 상위 5편",
)

# 막대 위의 숫자를 천 단위 쉼표 형식으로 표시합니다.
figure.update_traces(
    texttemplate="%{text:,}명",
    textposition="outside",
    hovertemplate=(
        "<b>%{y}</b><br>"
        "관객수: %{x:,}명"
        "<extra></extra>"
    ),
)

figure.update_layout(
    xaxis_tickformat=",",
    yaxis_title=None,
    xaxis_title="관객수",
    margin={
        "l": 20,
        "r": 50,
        "t": 60,
        "b": 20,
    },
)

st.plotly_chart(
    figure,
    use_container_width=True,
)


st.divider()


# ---------------------------------------------------------
# 9. 전체 박스오피스 순위 표
# ---------------------------------------------------------
st.subheader("📋 일별 박스오피스 전체 순위")

# 표에서 사용할 한글 열 이름으로 변경합니다.
table_df = boxoffice_df.rename(
    columns={
        "rank": "순위",
        "movieNm": "영화명",
        "openDt": "개봉일",
        "audiCnt": "관객수",
        "audiAcc": "누적관객",
        "scrnCnt": "스크린수",
    }
)

st.dataframe(
    table_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "순위": st.column_config.NumberColumn(
            "순위",
            format="%d위",
        ),
        "영화명": st.column_config.TextColumn(
            "영화명",
            width="large",
        ),
        "개봉일": st.column_config.TextColumn(
            "개봉일",
        ),
        "관객수": st.column_config.NumberColumn(
            "관객수",
            format="%,d명",
        ),
        "누적관객": st.column_config.NumberColumn(
            "누적관객",
            format="%,d명",
        ),
        "스크린수": st.column_config.NumberColumn(
            "스크린수",
            format="%,d개",
        ),
    },
)


# ---------------------------------------------------------
# 10. 하단 안내
# ---------------------------------------------------------
st.caption(
    "KOBIS 일별 박스오피스는 집계 상황에 따라 추후 일부 수치가 변경될 수 있습니다."
)
