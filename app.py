import streamlit as st
import requests
import google.generativeai as genai
import os
os.environ["CURL_CA_BUNDLE"] = ""

# 🔑 Gemini API 연결
genai.configure(api_key="AIzaSyDgwMFFY796NE_reQ9gO3p-rWQkNLV6KIE")

# 💬 Gemini 프롬프트 → KDC 추천 함수
def recommend_kdc(title, author):
    prompt = f"""도서 제목: {title}
저자: {author}
이 책에 가장 적절한 한국십진분류(KDC) 번호 1개를 추천해줘.
정확한 숫자만 아래 형식처럼 간결하게 말해줘:
KDC: 813.7"""
    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        lines = response.text.strip().splitlines()
        for line in lines:
            if line.startswith("KDC:"):
                return line.replace("KDC:", "").strip()
    except Exception as e:
        return "000"  # 실패 시 기본값
    return "000"

# 📚 알라딘 API 키
TTB_KEY = "ttbdawn63091003001"

# 📖 도서 정보 조회 + MARC 생성 함수
def fetch_book_data_from_aladin(isbn):
    url = f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?ttbkey={TTB_KEY}&itemIdType=ISBN&ItemId={isbn}&output=js&Version=20131101"
    response = requests.get(url, verify=False)
    if response.status_code != 200:
        return None
    data = response.json()
    if "item" not in data or not data["item"]:
        return None

    item = data["item"][0]
    title = item.get("title", "제목없음")
    author = item.get("author", "저자미상")
    publisher = item.get("publisher", "출판사미상")
    pubdate = item.get("pubDate", "2025")[:4]
    kdc = recommend_kdc(title, author)

    marc = f"""=001  {isbn}
=245  10$a{title} /$c{author}
=260  \\$a서울 :$b{publisher},$c{pubdate}.
=020  \\$a{isbn}
=056  \\$a{kdc}$26"""
    return marc

# 🌐 Streamlit 앱 시작
st.set_page_config(page_title="📚 ISBN to MARC + KDC", page_icon="🔖")
st.title("📚 ISBN to MARC 변환기 + KDC 자동 추천")

isbn_list = []

# 단일 입력
st.subheader("🔹 단일 ISBN 입력")
single_isbn = st.text_input("ISBN을 입력하세요", placeholder="예: 9788936434267")

# 파일 업로드
st.subheader("📁 [파일반입] .txt 업로드")
uploaded_file = st.file_uploader("한 줄에 하나씩 ISBN이 적힌 .txt 파일을 업로드하세요", type="txt")

# ISBN 리스트 수집
if uploaded_file is not None:
    content = uploaded_file.read().decode("utf-8")
    isbn_list = [line.strip() for line in content.splitlines() if line.strip()]
    st.success(f"{len(isbn_list)}개의 ISBN을 불러왔습니다.")
elif single_isbn.strip():
    isbn_list = [single_isbn.strip()]

# 결과 출력
if isbn_list:
    st.subheader("📄 변환 결과")
    marc_results = []
    for isbn in isbn_list:
        marc = fetch_book_data_from_aladin(isbn)
        if marc:
            st.code(marc, language="text")
            marc_results.append(marc)
        else:
            st.error(f"❌ ISBN {isbn} 정보를 불러올 수 없습니다.")

    full_text = "\n\n".join(marc_results)
    st.download_button("📥 모든 MARC 다운로드", data=full_text, file_name="marc_output.txt", mime="text/plain")
else:
    st.info("📌 ISBN을 입력하거나 txt 파일을 업로드해 주세요.")
