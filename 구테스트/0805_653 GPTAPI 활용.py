import streamlit as st
import requests
import pandas as pd
import openai
import xml.etree.ElementTree as ET
import re
import io
import xml.etree.ElementTree as ET
from collections import Counter
from bs4 import BeautifulSoup
from openai import OpenAI
from requests.adapters import HTTPAdapter, Retry
from concurrent.futures import ThreadPoolExecutor

# ── 한 번만 생성: 국중API용 세션 & 재시도 설정
_nlk_session = requests.Session()
_nlk_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=1,                # 재시도 1회
            backoff_factor=0.5,     # 0.5초 간격
            status_forcelist=[429,500,502,503,504]
        )
    )
)

# ✅ API 키 (secrets.toml에서 불러오기)
openai_key = st.secrets["api_keys"]["openai_key"]
aladin_key = st.secrets["api_keys"]["aladin_key"]
nlk_key = st.secrets["api_keys"]["nlk_key"]

gpt_client = OpenAI(api_key=openai_key)

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
@st.cache_data(ttl=24*3600)
def fetch_additional_code_from_nlk(isbn: str) -> str:
    url = (
        f"https://www.nl.go.kr/seoji/SearchApi.do?"
        f"cert_key={nlk_key}&result_style=xml"
        f"&page_no=1&page_size=1&isbn={isbn}"
    )
    try:
        res = _nlk_session.get(url, timeout=3)  # 3초만 기다리고
        res.raise_for_status()
        root = ET.fromstring(res.text)
        doc  = root.find('.//docs/e')
        return (doc.findtext('EA_ADD_CODE') or "").strip() if doc is not None else ""
    except Exception:
        st.warning("⚠️ 국중API 지연, 부가기호는 생략합니다.")
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
# ② 알라딘 메타데이터 호출 함수
def fetch_aladin_metadata(isbn):
    url = (
        "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
        f"?ttbkey={aladin_key}"
        "&ItemIdType=ISBN"
        f"&ItemId={isbn}"
        "&output=js"
        "&Version=20131101"
        "&OptResult=Toc" 
    )
    data = requests.get(url).json()
    item = data["item"][0]
    return {
        "category": item.get("categoryName", ""),
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "toc": item.get("toc", ""),
    }


# ③ GPT-4 기반 653 생성 함수
def generate_653_with_gpt(category, title, description, toc, max_keywords=7):
    parts = [p.strip() for p in category.split(">") if p.strip()]
    cat_kw = parts[-1] if parts else ""
    system_msg = {
        "role": "system",
        "content": (
            "당신은 도서관 메타데이터 전문가입니다. "
            "책의 분류, 제목, 설명, 목차 정보를 바탕으로 "
            "MARC 653 필드용 주제어를 추출하세요."
        )
    }
    user_msg = {
        "role": "user",
        "content": (
            f"다음 입력으로 최대 {max_keywords}개의 MARC 653 주제어를 한 줄로 출력해 주세요:\n\n"
            f"- 분류: \"{cat_kw}\"\n"
            f"- 제목: \"{title}\"\n"
            f"- 설명: \"{description}\"\n"
            f"- 목차: \"{toc}\"\n\n"
             "※ “제목”에 사용된 단어는 제외하고, 순수하게 분류·설명·목차에서 추출된 주제어만 뽑아주세요.\n"
            "출력 형식: $a키워드1 $a키워드2 …"
        )
    }
    try:
        resp = gpt_client.chat.completions.create(
            model="gpt-4",
            messages=[system_msg, user_msg],
            temperature=0.2,
            max_tokens=150,
        )
        # 1) 원본 응답을 raw에 담습니다
        raw = resp.choices[0].message.content.strip()

        # 2) $a … 다음 $a 또는 끝까지 캡처 (non-greedy)
        pattern = re.compile(r"\$a(.*?)(?=(?:\$a|$))", re.DOTALL)
        kws = [m.group(1).strip() for m in pattern.finditer(raw)]

        # 3) 각 키워드 내부 공백 제거
        kws = [kw.replace(" ", "") for kw in kws]

        # 4) 다시 "$a키워드" 형태로 조립
        return "".join(f"$a{kw}" for kw in kws)

    except Exception as e:
        st.warning(f"⚠️ 653 주제어 생성 실패: {e}")
        return None
    

# ④ Streamlit UI
st.title("📚 ISBN to MARC + 653 주제어 자동 생성")

isbn_input = st.text_input("ISBN 입력")
if st.button("메타데이터 조회 & 653 생성"):
    if not isbn_input:
        st.error("ISBN을 입력해 주세요.")
    else:
        meta = fetch_aladin_metadata(isbn_input)
        st.subheader("알라딘 메타데이터")
        st.write(meta)

        gpt_653 = generate_653_with_gpt(
            meta["category"],
            meta["title"],
            meta["description"],
            meta["toc"],
        )
        if gpt_653:
            st.subheader("=653")
            st.text_area("MARC 653 주제어", gpt_653, height=100)
        else:
            st.error("653 주제어 생성을 실패했습니다.")




# 📚 MARC 생성
@st.cache_data(show_spinner=False)
def fetch_book_data_from_aladin(isbn, reg_mark="", reg_no="", copy_symbol=""):
    import re

    # 1) 알라딘(API)과 국중(API) 부가기호를 동시에 요청하기
    url = (
        f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?"
        f"ttbkey={aladin_key}&itemIdType=ISBN&ItemId={isbn}"
        f"&output=js&Version=20131101"
    )
    with ThreadPoolExecutor(max_workers=2) as ex:
        # 1-1) 알라딘 API (5초 타임아웃)
        future_aladin = ex.submit(lambda: requests.get(url, verify=False, timeout=5))
        # 1-2) 국중 부가기호 (캐시+3초 타임아웃)
        future_nlk    = ex.submit(fetch_additional_code_from_nlk, isbn)

        # — 알라딘 응답 파싱
        try:
            resp = future_aladin.result()
            resp.raise_for_status()
            data = resp.json().get("item", [{}])[0]
        except Exception as e:
            st.error(f"🚨 알라딘API 오류: {e}")
            return ""

        # — 국중 부가기호 받기 (실패해도 빈 문자열)
        add_code = future_nlk.result()
        st.write("▶ [DEBUG] add_code:", repr(add_code))

    # 2) 기본 필드값들
    title       = data.get("title",       "제목없음")
    author      = data.get("author",      "저자미상")
    publisher   = data.get("publisher",   "출판사미상")
    pubdate     = data.get("pubDate",     "2025")[:4]
    category    = data.get("categoryName", "")
    description = data.get("description", "")
    toc         = data.get("subInfo", {}).get("toc", "")
    raw_price   = data.get("priceStandard", "")
    price       = str(raw_price)
    st.write("▶ priceStandard 확인:", price)

    # 3) 언어 태그
    lang_a  = detect_language(title)
    lang_h  = detect_language(data.get("title", ""))
    tag_041 = f"=041  \\$a{lang_a}" + (f"$h{lang_h}" if lang_h != "und" else "")
    tag_546 = f"=546  \\$a{generate_546_from_041_kormarc(tag_041)}"

    # 4) 020 필드: ISBN 뒤에 :$c{price}를 항상 붙이기
    tag_020 = f"=020  \\$a{isbn}:$c{price}"
    if add_code:
        tag_020 += f"$g{add_code}"


    # 5) KDC·653
    kdc     = recommend_kdc(title, author, api_key=openai_key)
    # GPT-4로 653 주제어 생성 (None 반환 시 빈 문자열 처리)
    gpt_653 = generate_653_with_gpt(category, title, description, toc, max_keywords=7)
    tag_653 = f"=653  \\{gpt_653.replace(' ', '')}" if gpt_653 else ""


    # 6) MARC 라인 초기화
    marc_lines = [
        "=007  ta",
        f"=245  00$a{title} /$c{author}",
        f"=260  \\$a서울 :$b{publisher},$c{pubdate}.",
    ]

    # 7) 490·830 (총서명 + 항상 ;$v)
    series = data.get("seriesInfo", {})
    name   = series.get("seriesName", "").strip()
    vol    = series.get("volume",    "").strip()
    if name:
        marc_lines.append(f"=490  \\$a{name};$v{vol}")
        marc_lines.append(f"=830  \\$a{name};$v{vol}")

    # 8) 나머지 필드
    marc_lines.append(tag_020)
    marc_lines.append(tag_041)
    marc_lines.append(tag_546)
    if kdc and kdc != "000":
        marc_lines.append(f"=056  \\$a{kdc}$26")
    if tag_653:
        marc_lines.append(tag_653)

    # 9) 950은 무조건!
    marc_lines.append(f"=950  0\\$b{price}")

    # 10) 049: 소장기호
    if reg_mark or reg_no or copy_symbol:
        line = f"=049  0\\$I{reg_mark}{reg_no}"
        if copy_symbol:
            line += f"$f{copy_symbol}"
        marc_lines.append(line)

    # 11) 숫자 오름차순 정렬
    marc_lines.sort(key=lambda L: int(re.match(r"=(\d+)", L).group(1)))

    # 12) 최종 리턴
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
