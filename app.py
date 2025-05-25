import streamlit as st
import requests

# 알라딘 TTBKey
TTB_KEY = "ttbdawn63091003001"

# 페이지 설정
st.set_page_config(page_title="📚 ISBN → MARC 변환기", page_icon="🔖", layout="centered")
st.title("📚 ISBN to MARC 변환기 (알라딘 API 연동)")

isbn_list = []

# 🔹 단일 ISBN 입력
st.subheader("🔹 단일 ISBN 입력")
single_isbn = st.text_input("ISBN을 입력하세요", placeholder="예: 9788936434267")

# 📁 파일 업로드
st.subheader("📁 [파일반입] .txt 업로드")
uploaded_file = st.file_uploader("한 줄에 하나씩 ISBN이 적힌 .txt 파일을 업로드하세요", type="txt")

# ISBN 수집
if uploaded_file is not None:
    content = uploaded_file.read().decode("utf-8")
    isbn_list = [line.strip() for line in content.splitlines() if line.strip()]
    st.success(f"총 {len(isbn_list)}개의 ISBN을 불러왔습니다.")
elif single_isbn.strip():
    isbn_list = [single_isbn.strip()]

# 🪄 알라딘 API를 이용한 도서 정보 → MARC 변환 함수
def fetch_book_data_from_aladin(isbn):
    url = f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?ttbkey={TTB_KEY}&itemIdType=ISBN&ItemId={isbn}&output=js&Version=20131101"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    
    data = response.json()
    if "item" not in data or not data["item"]:
        return None
    
    item = data["item"][0]
    title = item.get("title", "제목없음")
    author = item.get("author", "저자미상")
    publisher = item.get("publisher", "출판사미상")
    pubdate = item.get("pubDate", "2025")[:4]  # 연도만 추출

    # MARC 형식 구성
    marc = f"""=001  {isbn}
=245  10$a{title} /$c{author}
=260  \\$a서울 :$b{publisher},$c{pubdate}.
=020  \\$a{isbn}"""

    return marc

# 결과 처리 및 출력
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

    # 다운로드
    if marc_results:
        full_text = "\n\n".join(marc_results)
        st.download_button("📥 모든 MARC 다운로드", data=full_text, file_name="marc_output.txt", mime="text/plain")
else:
    st.info("ISBN을 입력하거나 파일을 업로드해 주세요.")
