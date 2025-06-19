# 📚 통합된 Streamlit 웹앱: ISBN -> MARC 변환기 (KDC, NLK, 알라딘 통합)

import streamlit as st
import os
import requests
import pandas as pd
import google.generativeai as genai
import xml.etree.ElementTree as ET
import re
import io

# 🔐 API 키들
TTB_KEY = "ttbdawn63091003001"
NLK_KEY = "45b1715858c57fa38cdefdf80fefdca3502e93f2e03576bde074048b412da3db"

# ✅ Gemini API
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error(f"Gemini API 설정 오류: {e}")

# 🎯 Gemini 기반 KDC 추천
@st.cache_data(show_spinner=False)
def recommend_kdc(title, author):
    prompt = f"""도서 제목: {title}
저자: {author}
이 책에 가장 적절한 한국십진분류(KDC) 번호 1개를 추천해줘.
정확한 숫자만 아래 형식처럼 간결하게 말해줘:
KDC: 813.7"""
    try:
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
        response = model.generate_content(prompt)
        for line in response.text.strip().splitlines():
            if "KDC:" in line:
                return line.replace("KDC:", "").strip()
    except:
        return "000"
    return "000"

# 🧠 언어코드 & 언어판별
ISDS_LANGUAGE_CODES = {'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어', 'und': '알 수 없음'}

def detect_language(text):
    text = re.sub(r'[\s\W_]+', '', text)
    if not text: return 'und'
    ch = text[0]
    if '\uac00' <= ch <= '\ud7a3': return 'kor'
    elif '\u3040' <= ch <= '\u30ff': return 'jpn'
    elif '\u4e00' <= ch <= '\u9fff': return 'chi'
    elif '\u0400' <= ch <= '\u04FF': return 'rus'
    elif 'a' <= ch.lower() <= 'z': return 'eng'
    else: return 'und'

def generate_546_from_041_kormarc(marc_041):
    a_codes, h_code = [], None
    for part in marc_041.split():
        if part.startswith("$a"): a_codes.append(part[2:])
        elif part.startswith("$h"): h_code = part[2:]

    if len(a_codes) == 1:
        a_lang = ISDS_LANGUAGE_CODES.get(a_codes[0], "알 수 없음")
        if h_code:
            h_lang = ISDS_LANGUAGE_CODES.get(h_code, "알 수 없음")
            return f"{a_lang}로 씀, 원저는 {h_lang}임"
        else:
            return f"{a_lang}로 씀"
    elif len(a_codes) > 1:
        langs = [ISDS_LANGUAGE_CODES.get(code, "알 수 없음") for code in a_codes]
        return f"{'、'.join(langs)} 병기"
    else:
        return "언어 정보 없음"

def get_kormarc_041_tag(isbn):
    params = {"ttbkey": TTB_KEY, "itemIdType": "ISBN13", "ItemId": isbn, "output": "xml", "Version": "20131101"}
    response = requests.get("https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx", params=params)
    try:
        root = ET.fromstring(response.content)
        ns = {"ns": "http://www.aladin.co.kr/ttb/apiguide.aspx"}
        item = root.find("ns:item", namespaces=ns)
        title = item.findtext("ns:title", default="", namespaces=ns)
        original = item.find("ns:subInfo", namespaces=ns).findtext("ns:originalTitle", default="", namespaces=ns)
        lang_a = detect_language(title)
        lang_h = detect_language(original)
        marc_041 = f"041 $a{lang_a} {'$h'+lang_h if original else ''}".strip()
        marc_546 = generate_546_from_041_kormarc(marc_041)
        return marc_041, marc_546
    except:
        return "041 오류", ""

# 📚 NLK 기반 245 + 700 생성
from bs4 import BeautifulSoup

def fetch_from_nlk(isbn, nlk_key):
    url = f"https://www.nl.go.kr/seoji/SearchApi.do?cert_key={nlk_key}&result_style=xml&page_no=1&page_size=10&isbn={isbn}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)
        doc = root.find('.//docs/e')
        title = doc.findtext('TITLE')
        author = doc.findtext('AUTHOR')
        return title, author
    except:
        return "제목없음", "지은이 미생"

def reverse_name_order(name):
    parts = name.strip().split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) >= 2 else name

def split_title(full):
    for sep in [":", "-", "：", "–"]:
        if sep in full:
            return full.split(sep, 1)[0].strip(), full.split(sep, 1)[1].strip()
    return full.strip(), ""

def generate_245(title_str, author_str):
    def safe_extract(raw, keyword):
        for entry in raw.split(";"):
            if keyword in entry:
                parts = entry.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip()
        return ""

    title, subtitle = split_title(title_str)

    writer_raw = safe_extract(author_str, "지은이")
    translator_raw = safe_extract(author_str, "옮긴이")

    writer_list = [name.strip() for name in writer_raw.split(",") if name.strip()]
    translator_list = [name.strip() for name in translator_raw.split(",") if name.strip()]

    parts = []
    if writer_list:
        writer_parts = []
        for i, name in enumerate(writer_list):
            if i == 0:
                writer_parts.append(f"$d{name}")
            else:
                writer_parts.append(f"$e{name}")
        writer_parts[-1] += " 지음"
        parts.append(", ".join(writer_parts))

    if translator_list:
        translator_str = ";$e" + ", $e".join(translator_list) + " 옮김"
        parts.append(translator_str)

    responsibility = " ".join(parts)
    line = "=245  00"
    line += f"$a{title}"
    if subtitle:
        line += f" :$b{subtitle}"
    if responsibility:
        line += f" /{responsibility}"
    return line

def generate_700(author_str):
    def safe_extract_list(raw, keyword):
        for entry in raw.split(";"):
            if keyword in entry:
                parts = entry.split(":", 1)
                if len(parts) == 2:
                    return [name.strip() for name in parts[1].split(",") if name.strip()]
        return []

    lines = []
    writer_list = safe_extract_list(author_str, "지은이")
    translator_list = safe_extract_list(author_str, "옮긴이")

    for name in writer_list + translator_list:
        if ' ' in name:  # 성과 이름이 공백으로 분리됨
            name_final = reverse_name_order(name)
        else:
            name_final = name
        lines.append(f"=700  1\\$a{name_final}")

    return lines

def generate_nlk_marc_fields(isbn):
    title, author = fetch_from_nlk(isbn, NLK_KEY)
    if not title or not author: return None, None, []
    return title, author, [generate_245(title, author)] + generate_700(author)

# 📚 알라딘 기반 필드 생성
@st.cache_data(show_spinner=False)
def fetch_book_data_from_aladin(isbn, reg_mark="", reg_no="", copy_symbol=""):
    url = f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?ttbkey={TTB_KEY}&itemIdType=ISBN&ItemId={isbn}&output=js&Version=20131101"
    response = requests.get(url, verify=False)
    data = response.json().get("item", [{}])[0]
    
    title = data.get("title", "제목없음")
    author = data.get("author", "저자미생")
    publisher = data.get("publisher", "출판사미생")
    pubdate = data.get("pubDate", "2025")[:4]
    price = data.get("priceStandard")
    series_title = data.get("seriesInfo", {}).get("seriesName", "").strip()
    kdc = recommend_kdc(title, author)

    marc = rf"=001  {isbn}"
    marc += rf"\n=245  10$a{title} /$c{author}"
    marc += rf"\n=260  \\$a서울 :$b{publisher},$c{pubdate}."
    marc += rf"\n=020  \\$a{isbn}" + (rf":$c\{price}" if price else "")

    if kdc and kdc != "000":
        marc += rf"\n=056  \\$a{kdc}$26"

    if series_title:
        marc += rf"\n=490  10$a{series_title} ;$v"
        marc += rf"\n=830  \\0$a{series_title} ;$v"

    if price:
        marc += rf"\n=950  0\\$b\{price}"

    if reg_mark or reg_no or copy_symbol:
        tag_049 = rf"=049  0\\"
        if reg_mark or reg_no:
            tag_049 += rf"$I{reg_mark}{reg_no}"
        if copy_symbol:
            tag_049 += rf"$f{copy_symbol}"
        marc += rf"\n{tag_049}"

    return marc


# 🎛️ UI 영역
st.title("📚 ISBN to MARC 변환기 + KDC + 041/546 + NLK")

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
        tag_041, tag_546 = get_kormarc_041_tag(isbn)
        title, author, nlk_fields = generate_nlk_marc_fields(isbn)
        if marc:
            if tag_041: marc += f"\n={tag_041}"
            if tag_546: marc += f"\n=546  \\${tag_546}"
            if nlk_fields: marc += "\n" + "\n".join(nlk_fields)
            st.code(marc, language="text")
            marc_results.append(marc)

    full_text = "\n\n".join(marc_results)
    st.download_button("📦 모든 MARC 다운로드", data=full_text, file_name="marc_output.txt", mime="text/plain")

# 📄 예시파일 다운로드
example_csv = "ISBN,등록기호,등록번호,별치기호\n'9791173473968,JUT,12345,TCH\n"
buffer = io.BytesIO()
buffer.write(example_csv.encode("utf-8-sig"))
buffer.seek(0)
st.markdown("""
📌 **서식 파일 사용 안내**  
서식 파일의 두 번째 줄은 예시 데이터입니다. ISBN 앞 작은따옴표(`'`)는 Excel에서 숫자 자동변환을 막기 위한 것입니다. 실제 사용 시에는 삭제해 주세요.
""")
st.download_button("📄 서식 파일 다운로드", data=buffer, file_name="isbn_template.csv", mime="text/csv")

# 🔗 출처 표시
st.markdown("""
<div style='text-align: center; font-size: 14px; color: gray;'>
📚 <strong>도서 DB 제공</strong> : <a href='https://www.aladin.co.kr' target='_blank'>알라딘 인터넷서점(www.aladin.co.kr)</a>
</div>
""", unsafe_allow_html=True)
