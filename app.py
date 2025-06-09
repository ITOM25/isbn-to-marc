import streamlit as st
st.set_page_config(page_title="📚 ISBN to MARC + KDC", page_icon="🔖")

import os
import requests
import pandas as pd
import google.generativeai as genai

# ✅ 앱 시작 로그
st.write("✅ 앱 시작됨")

# ✅ Gemini API Key 로드
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    st.write("🔑 secrets 불러오기 성공")
except Exception as e:
    st.error(f"❌ [에러] secrets 불러오기 실패: {e}")
    raise e

# ✅ Gemini 설정
try:
    genai.configure(api_key=API_KEY)
    st.write("🧐 Gemini 설정 완료")
except Exception as e:
    st.error(f"❌ [에러] Gemini 모듈 문제: {e}")
    raise e

# 팔스코 KDC 추천 함수
def recommend_kdc(title, author):
    prompt = f"""도서 제목: {title}
저자: {author}
이 책에 가장 적절한 한국십진분류(KDC) 번호 1개를 추천해줘.
정확한 숫자만 아래 형식처럼 간결하게 말해줘:
KDC: 813.7"""
    try:
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
        response = model.generate_content(prompt)
        st.write("🧐 Gemini 응답 원문:", response.text)
        lines = response.text.strip().splitlines()
        for line in lines:
            if "KDC:" in line:
                return line.replace("KDC:", "").strip()
    except Exception as e:
        st.error(f"❌ Gemini 오류 발생: {e}")
        return "000"
    return "000"

# 타이프에 따른 MARC 생성
TTB_KEY = "ttbdawn63091003001"

def fetch_book_data_from_aladin(isbn, reg_mark="", reg_no="", copy_symbol=""):
    url = f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?ttbkey={TTB_KEY}&itemIdType=ISBN&ItemId={isbn}&output=js&Version=20131101"
    response = requests.get(url, verify=False)
    if response.status_code != 200:
        return None
    data = response.json()
    if "item" not in data or not data["item"]:
        return None

    item = data["item"][0]
    st.write("🔍 알라딘 응답 item 전체:", item)

    title = item.get("title", "제목없음")
    author = item.get("author", "저자미생")
    publisher = item.get("publisher", "출판사미생")
    pubdate = item.get("pubDate", "2025")[:4]
    price = item.get("priceStandard")
    series_title = item.get("seriesInfo", {}).get("seriesName", "").strip()
    kdc = recommend_kdc(title, author)

    # 020
    if price:
        marc = f"""=001  {isbn}
=245  10$a{title} /$c{author}
=260  \\$a서울 :$b{publisher},$c{pubdate}.
=020  \\$a{isbn}:$c\{price}"""
    else:
        marc = f"""=001  {isbn}
=245  10$a{title} /$c{author}
=260  \\$a서울 :$b{publisher},$c{pubdate}.
=020  \\$a{isbn}"""

    if kdc and kdc != "000":
        marc += f"\n=056  \\$a{kdc}$26"

    if series_title:
        marc += f"\n=490  10$a{series_title} ;$v"
        marc += f"\n=830  \\0$a{series_title} ;$v"

    if price:
        marc += f"\n=950  0\\$b\{price}"

    # 049
    if reg_mark or reg_no or copy_symbol:
        tag_049 = "=049  0\\"
        if reg_mark or reg_no:
            tag_049 += f"$I{reg_mark}{reg_no}"
        if copy_symbol:
            tag_049 += f"$f{copy_symbol}"
        marc += f"\n{tag_049}"

    return marc

# 프리스트티티 UI
st.title("📚 ISBN to MARC 변환기 + KDC + 보유정보")

isbn_list = []

# 단일 ISBN 입력
df_single = None
st.subheader("🔹 단일 ISBN 입력")
single_isbn = st.text_input("ISBN을 입력하세요", placeholder="예: 9788936434267")

if single_isbn.strip():
    isbn_list = [[single_isbn.strip(), "", "", ""]]

# CSV 받기
st.subheader("📁 [파일받기] .csv 업로드")
uploaded_file = st.file_uploader("ISBN, 등록기호, 등록번호, 별치기호 열이 있는 CSV 파일을 업로드하세요", type="csv")

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = {'ISBN', '등록기호', '등록번호', '별치기호'}
        if not required_cols.issubset(df.columns):
            st.error("❌ CSV에 'ISBN', '등록기호', '등록번호', '별치기호' 열이 포함되어야 합니다.")
        else:
            isbn_list = df[['ISBN', '등록기호', '등록번호', '별치기호']].dropna(subset=['ISBN']).values.tolist()
            st.success(f"{len(isbn_list)}개의 ISBN을 불러왔습니다.")
    except Exception as e:
        st.error(f"❌ CSV 파일 처리 중 오류: {e}")

# 결과 출력
if isbn_list:
    st.subheader("📄 변환 결과")
    marc_results = []
    for row in isbn_list:
        isbn, reg_mark, reg_no, copy_symbol = row
        marc = fetch_book_data_from_aladin(isbn, reg_mark, reg_no, copy_symbol)
        if marc:
            st.code(marc, language="text")
            marc_results.append(marc)
        else:
            st.error(f"❌ ISBN {isbn} 정보를 불러올 수 없습니다.")

    full_text = "\n\n".join(marc_results)
    st.download_button("📅 모든 MARC 다운로드", data=full_text, file_name="marc_output.txt", mime="text/plain")
else:
    st.info("📌 ISBN을 입력하거나 CSV 파일을 업로드해 주세요.")

import streamlit as st
import io  # 🔧 필수! StringIO를 사용하려면 반드시 필요함

# ✨ 예시 CSV 내용 만들기
csv_example = "ISBN,등록기호,등록번호,별치기호\n9791173473968,JUT,12345,TCH\n"

# ✨ 다운로드 버튼
st.download_button(
    label="📄 서식 파일 다운로드",
    data=io.StringIO(csv_example),  # ← 문자열을 파일처럼 다루기 위해 감쌈!
    file_name="isbn_template.csv",
    mime="text/csv"
)

