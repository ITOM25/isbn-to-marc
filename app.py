import streamlit as st
import requests
import pandas as pd
import openai
import xml.etree.ElementTree as ET
import re
import io
from collections import Counter
from bs4 import BeautifulSoup
from openai import OpenAI


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

def clean_keywords(words):
    stopwords = {"아주", "가지", "필요한", "등", "위해", "것", "수", "더", "이런", "있다", "된다", "한다"}
    return [w for w in words if w not in stopwords and len(w) > 1]

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
# 🔧 GPT 기반 KDC 추천 (OpenAI 1.6.0+ 방식으로 리팩토링)
def recommend_kdc(title, author, api_key):
    try:
        # 🔑 비밀의 열쇠로 클라이언트를 깨웁니다
        client = OpenAI(api_key=api_key)

        # 📜 주문문을 준비하고
        prompt = (
            f"도서 제목: {title}\n"
            f"저자: {author}\n"
            "이 책의 주제를 고려하여 한국십진분류(KDC) 번호 하나를 추천해 주세요.\n"
            "정확한 숫자만 아래 형식으로 간단히 응답해 주세요:\n"
            "KDC: 813.7"
        )

        # 🧠 GPT의 지혜를 소환
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        # ✂️ “KDC:” 뒤의 숫자만 꺼내서 돌려드립니다
        for line in response.choices[0].message.content.splitlines():
            if "KDC:" in line:
                return line.split("KDC:")[1].strip()

    except Exception as e:
        st.warning(f"🧠 GPT 오류: {e}")

    # 🛡️ 만약 실패하면 디폴트 “000”
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

# 🔤 언어 감지 및 041, 546 생성
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'und': '알 수 없음'
}

def detect_language(text):
    text = re.sub(r'[\s\W_]+', '', text)
    if not text:
        return 'und'
    first_char = text[0]
    if '\uac00' <= first_char <= '\ud7a3':
        return 'kor'
    elif '\u3040' <= first_char <= '\u30ff':
        return 'jpn'
    elif '\u4e00' <= first_char <= '\u9fff':
        return 'chi'
    elif '\u0400' <= first_char <= '\u04FF':
        return 'rus'
    elif 'a' <= first_char.lower() <= 'z':
        return 'eng'
    else:
        return 'und'

def generate_546_from_041_kormarc(marc_041: str) -> str:
    a_codes, h_code = [], None
    for part in marc_041.split():
        if part.startswith("$a"):
            a_codes.append(part[2:])
        elif part.startswith("$h"):
            h_code = part[2:]
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
    return "언어 정보 없음"

def crawl_aladin_original_and_price(isbn13):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn13}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        original = soup.select_one("div.info_original")
        price = soup.select_one("span.price2")
        return {
            "original_title": original.text.strip() if original else "",
            "price": price.text.strip().replace("정가 : ", "").replace("원", "").replace(",", "").strip() if price else ""
        }
    except:
        return {}

# 📄 653 필드 키워드 생성
def build_653_field(title, description, toc, raw_category):
    # 1) 카테고리 마지막 요소
    parts   = [p.strip() for p in raw_category.split(">") if p.strip()]
    category = parts[-1] if parts else ""

    # 2) 제목에서 명사 2개, 목차 5개, 설명 3개
    title_kw = clean_keywords(extract_keywords_from_text(title,  top_n=2))
    toc_kw   = clean_keywords(extract_keywords_from_text(toc,    top_n=5))
    desc_kw  = clean_keywords(extract_keywords_from_text(description, top_n=3))

    # 3) 순서 유지하며 중복 제거, 최대 7개
    combined = list(dict.fromkeys(title_kw + toc_kw + desc_kw))
    body     = combined[:7]

    # 4) 카테고리 앞세우기
    final    = ([category] if category else []) + body

    # 5) 조립
    return "=653  \\" + "".join(f"$a{kw}" for kw in final) if final else ""



# 📚 MARC 생성
@st.cache_data(show_spinner=False)
def fetch_book_data_from_aladin(isbn, reg_mark="", reg_no="", copy_symbol=""):
    import re

    # 1) API 호출
    try:
        url = (
            f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?"
            f"ttbkey={aladin_key}&itemIdType=ISBN&ItemId={isbn}"
            f"&output=js&Version=20131101"
        )
        resp = requests.get(url, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("item", [{}])[0]
    except Exception as e:
        st.error(f"🚨 알라딘 API 오류: {e}")
        return ""

    # 2) 기본 필드값들
    title     = data.get("title",       "제목없음")
    author    = data.get("author",      "저자미상")
    publisher = data.get("publisher",   "출판사미상")
    pubdate   = data.get("pubDate", "2025")[:4]
    # — (추가) 카테고리 정보도 꺼내기
    category  = data.get("categoryName", "")
    # — 가격: TTB API에서 바로 꺼내되, int → str 변환
    raw_price = data.get("priceStandard", "")
    price     = str(raw_price)
    # ── (옵션) 디버그: 가격이 제대로 들어오는지 확인
    st.write("▶ priceStandard 확인:", price)

    # 3) 언어 태그
    lang_a  = detect_language(title)
    lang_h  = detect_language(data.get("title", ""))
    tag_041 = f"=041  \\$a{lang_a}" + (f"$h{lang_h}" if lang_h != "und" else "")
    tag_546 = f"=546  \\$a{generate_546_from_041_kormarc(tag_041)}"

    # 4) 020 필드: ISBN 뒤에 :$c{price}를 항상 붙이기
    tag_020 = f"=020  \\$a{isbn}:$c{price}"
    add_code = fetch_additional_code_from_nlk(isbn)
    if add_code:
        tag_020 += f"$g{add_code}"

    # — KDC·653 (원칙대로 제목·목차·설명·카테고리를 모두 넘겨 주기)
    kdc     = recommend_kdc(title, author, api_key=openai_key)
    tag_653 = build_653_field(title, description, toc, category)

    # 6) MARC 라인 초기화
    marc_lines = [
        "=007  ta",
        f"=245  00$a{title} /$c{author}",
        f"=260  \\$a서울 :$b{publisher},$c{pubdate}.",
    ]

    # 7) 490·830 (총서명 + 항상 ;$v)
    series = data.get("seriesInfo", {})  
    name   = series.get("seriesName", "").strip()
    vol    = series.get("volume",     "").strip()
    if name:
        marc_lines.append(f"=490  \\$a{name};$v{vol}")
        marc_lines.append(f"=830  \\$a{name};$v{vol}")

    # 8) 나머지 필드 (순서는 정렬에서 처리)
    marc_lines.append(tag_020)                # =020
    marc_lines.append(tag_041)                # =041
    marc_lines.append(tag_546)                # =546
    if kdc and kdc != "000":
        marc_lines.append(f"=056  \\$a{kdc}$26")   # =056
    if tag_653:
        marc_lines.append(tag_653)            # =653

    # 950은 무조건! (비어 있어도 필드만 남김)
    marc_lines.append(f"=950  0\\$b{price}")

    # 049: 소장기호
    if reg_mark or reg_no or copy_symbol:
        line = f"=049  0\\$I{reg_mark}{reg_no}"
        if copy_symbol:
            line += f"$f{copy_symbol}"
        marc_lines.append(line)

    # 9) 숫자 오름차순 정렬
    marc_lines.sort(key=lambda L: int(re.match(r"=(\d+)", L).group(1)))

    # 10) 최종 리턴
    return "\n".join(marc_lines)




# 🎛️ Streamlit UI
st.title("📚 ISBN to MARC 변환기 (통합버전)")

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
