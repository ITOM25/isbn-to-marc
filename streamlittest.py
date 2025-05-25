import streamlit as st
import requests
import json

# 💾 알라딘 API 키를 여기에 입력하세요!
ALADIN_API_KEY = 'ttbdawn63091003001'

# 📦 MARC 필드 생성 함수
def fetch_book_data_from_aladin(isbn):
    url = f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?ttbkey={ALADIN_API_KEY}&itemIdType=ISBN&ItemId={isbn}&output=js&Version=20131101"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    data = response.json()
    if "item" not in data or not data["item"]:
        return None
    item = data["item"][0]

    # 기본 MARC 구성 (일부 필드만)
    marc_data = []
    marc_data.append("=LDR  00000nam 2200000 c 4500")
    marc_data.append(f"=020  \\$a{isbn}")
    marc_data.append(f"=245  10$a{item.get('title', '')}")
    marc_data.append(f"=260  \\$b{item.get('publisher', '')}$c{item.get('pubDate', '')}")
    marc_data.append(f"=700  1\\$a{item.get('author', '')}")
    marc_data.append(f"=950  \\$a{item.get('priceSales', '')}")

    return "\n".join(marc_data)

# 🌐 Streamlit UI
st.title("📘 ISBN → MARC 변환기 (알라딘 API 전용)")
isbn_input = st.text_input("ISBN을 입력하세요", "")

if st.button("MARC 데이터 생성"):
    if isbn_input.strip() == "":
        st.warning("ISBN을 입력해 주세요.")
    else:
        marc_result = fetch_book_data_from_aladin(isbn_input)
        if marc_result:
            st.text_area("📄 생성된 MARC 데이터", marc_result, height=200)
            
            # 다운로드 버튼 추가
            st.download_button(
                label="📥 MARC 텍스트 파일 다운로드",
                data=marc_result,
                file_name=f"marc_{isbn_input}.txt",
                mime="text/plain"
            )
        else:
            st.error("도서 정보를 불러오지 못했습니다. ISBN을 확인해 주세요.")
