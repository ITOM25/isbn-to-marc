import streamlit as st
import requests
import pandas as pd
import openai
import xml.etree.ElementTree as ET
import re
import io
from collections import Counter

# ✅ API 키 (secrets.toml에서 불러오기)
openai_key = st.secrets["api_keys"]["openai_key"]
aladin_key = st.secrets["api_keys"]["aladin_key"]
nlk_key = st.secrets["api_keys"]["nlk_key"]

# 🔍 키워드 추출 (konlpy 없이)
def extract_keywords_from_text(text, top_n=7):
    words = re.findall(r'\b[\w가-힣]{2,}\b', text)
    filtered = [w for w in words if len(w) > 1]
    freq = Counter(filtered)
    return [kw for kw, _ in freq.most_common(top_n)]

# 📚 카테고리 키워드 추출
def extract_category_keywords(category_str):
    keywords = set()
    lines = category_str.strip().splitlines()
    for line in lines:
        parts = [x.strip() for x in line.split('>') if x.strip()]
        if parts:
            keywords.add(parts[-1])
    return list(keywords)

# 🔧 GPT 기반 KDC 추천
def recommend_kdc(title, author, api_key):
    try:
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""도서 제목: {title}
저자: {author}
이 책의 주제를 고려하여 한국십진분류(KDC) 번호 하나를 추천해 주세요.
정확한 숫자만 아래 형식으로 간단히 응답해 주세요:
KDC: 813.7"""
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        answer = response.choices[0].message.content
        for line in answer.strip().splitlines():
            if "KDC:" in line:
                return line.replace("KDC:", "").strip()
    except Exception as e:
        st.warning(f"🧠 GPT 오류: {e}")
    return "000"

# 📡 부가기호 추출 (국립중앙도서관)
def fetch_additional_code_from_nlk(isbn):
    try:
        url = f"https://www.nl.go.kr/seoji/SearchApi.do?cert_key={nlk_key}&result_style=xml&page_no=1&page_size=10&isbn={isbn}"
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)
        doc = root.find('.//docs/e')
        if doc is not None:
            add_code = doc.findtext('EA_ADD_CODE')
            return add_code.strip() if add_code else ""
    except Exception as e:
        st.warning(f"📡 국중API 오류: {e}")
    return ""

# 📄 653 필드 키워드 생성
def generate_653_keywords(title, description, toc, category):
    keywords = set()
    keywords.update(extract_category_keywords(category))
    keywords.update(extract_keywords_from_text(title, 2))
    keywords.update(extract_keywords_from_text(description, 7))
    keywords.update(extract_keywords_from_text(toc, 7))
    return list(keywords)[:8]

# 📚 MARC 생성 (알라딘 + GPT + 국중)
@st.cache_data(show_spinner=False)
def fetch_book_data_from_aladin(isbn, reg_mark="", reg_no="", copy_symbol=""):
    try:
        url = f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?ttbkey={aladin_key}&itemIdType=ISBN&ItemId={isbn}&output=js&Version=20131101&optResult=ebookList,reviewList"
        response = requests.get(url, verify=False, timeout=10)
        response.raise_for_status()
        data = response.json().get("item", [{}])[0]
    except Exception as e:
        st.error(f"🚨 알라딘 API 오류: {e}")
        return ""

    title = data.get("title", "제목없음")
    author = data.get("author", "저자미상")
    publisher = data.get("publisher", "출판사미상")
    pubdate = data.get("pubDate", "2025")[:4]
    price = data.get("priceStandard")
    series_title = data.get("seriesInfo", {}).get("seriesName", "").strip()
    category = data.get("categoryName", "")
    description = data.get("description", "")
    toc = data.get("subInfo", {}).get("toc", "")

    add_code = fetch_additional_code_from_nlk(isbn)
    kdc = recommend_kdc(title, author, api_key=openai_key)
    keywords = generate_653_keywords(title, description, toc, category)

    marc = f"=007  ta\n=245  00$a{title} /$c{author}\n=260  \\$a서울 :$b{publisher},$c{pubdate}.\n=020  \\$a{isbn}"
    if add_code:
        marc += f"$g{add_code}"
    if price:
        marc += f":$c\\{price}"
    if kdc and kdc != "000":
        marc += f"\n=056  \\$a{kdc}$26"
    if keywords:
        marc += "\n=653  \\" + "".join([f"$a{kw}" for kw in keywords])
    if series_title:
        marc += f"\n=490  10$a{series_title} ;$v\n=830  \\0$a{series_title} ;$v"
    if price:
        marc += f"\n=950  0\\$b\\{price}"
    if reg_mark or reg_no or copy_symbol:
        marc += f"\n=049  0\\$I{reg_mark}{reg_no}"
        if copy_symbol:
            marc += f"$f{copy_symbol}"

    return marc

# 🎛️ Streamlit UI
st.title("📚 ISBN to MARC 변환기 (Cloud용, konlpy 없이)")

isbn_list = []
single_isbn = st.text_input("🔹 단일 ISBN 입력", placeholder="예: 9788936434267")
if single_isbn.strip():
    isbn_list = [[single_isbn.strip(), "", "", ""]]

uploaded_file = st.file_uploader("📁 CSV 업로드 (ISBN, 등록기호, 등록번호, 별치기호)", type="csv")
if uploaded_file:
    df = pd.read_csv(uploaded_file)
    if {'ISBN', '등록기호', '등록번호', '별치기호'}.issubset(df.columns):
        isbn_list = df[['ISBN', '등록기호', '등록번호', '별치기호']].dropna(subset=['ISBN']).values.tolist()
    else:
        st.error("❌ 필요한 열이 없습니다: ISBN, 등록기호, 등록번호, 별치기호")

if isbn_list:
    st.subheader("📄 MARC 출력")
    marc_results = []
    for row in isbn_list:
        isbn, reg_mark, reg_no, copy_symbol = row
        marc = fetch_book_data_from_aladin(isbn, reg_mark, reg_no, copy_symbol)
        if marc:
            st.code(marc, language="text")
            marc_results.append(marc)

    full_text = "\n\n".join(marc_results)
    st.download_button("📦 모든 MARC 다운로드", data=full_text, file_name="marc_output.txt", mime="text/plain")

# 📄 템플릿 예시 다운로드
example_csv = "ISBN,등록기호,등록번호,별치기호\n9791173473968,JUT,12345,TCH\n"
buffer = io.BytesIO()
buffer.write(example_csv.encode("utf-8-sig"))
buffer.seek(0)
st.download_button("📄 서식 파일 다운로드", data=buffer, file_name="isbn_template.csv", mime="text/csv")

# ⬇️ 하단 마크
st.markdown("""
<div style='text-align: center; font-size: 14px; color: gray;'>
📚 <strong>도서 DB 제공</strong> : <a href='https://www.aladin.co.kr' target='_blank'>알라딘 인터넷서점(www.aladin.co.kr)</a>
</div>
""", unsafe_allow_html=True)
