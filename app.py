import streamlit as st
import requests
import pandas as pd
import io
import datetime
import xml.etree.ElementTree as ET
import re
import unicodedata
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

# 한국 발행지 문자열 → KORMARC 3자리 코드 (필요 시 확장)
KR_REGION_TO_CODE = {
    "서울": "ulk", "서울특별시": "ulk",
    "경기": "ggk", "경기도": "ggk",
    "부산": "bnk", "부산광역시": "bnk",
    "대구": "tgk", "대구광역시": "tgk",
    "인천": "ick", "인천광역시": "ick",
    "광주": "kjk", "광주광역시": "kjk",
    "대전": "tjk", "대전광역시": "tjk",
    "울산": "usk", "울산광역시": "usk",
    "세종": "sjk", "세종특별자치시": "sjk",
    "강원": "gak", "강원특별자치도": "gak",
    "충북": "hbk", "충청북도": "hbk",
    "충남": "hck", "충청남도": "hck",
    "전북": "jbk", "전라북도": "jbk",
    "전남": "jnk", "전라남도": "jnk",
    "경북": "gbk", "경상북도": "gbk",
    "경남": "gnk", "경상남도": "gnk",
    "제주": "jjk", "제주특별자치도": "jjk",
}

# 기본값: 발행국/언어/목록전거
COUNTRY_FIXED = "ulk"   # 발행국 기본값
LANG_FIXED    = "kor"   # 언어 기본값

# 008 본문(40자) 조립기 — 단행본 기준(type_of_date 기본 's')
def build_008_kormarc_bk(
    date_entered,          # 00-05 YYMMDD
    date1,                 # 07-10 4자리(예: '2025' / '19uu')
    country3,              # 15-17 3자리
    lang3,                 # 35-37 3자리
    date2="",              # 11-14
    illus4="",             # 18-21 최대 4자(예: 'a','ad','ado'…)
    has_index="0",         # 31 '0' 없음 / '1' 있음
    lit_form=" ",          # 33 (p시/f소설/e수필/i서간문학/m기행·일기·수기)
    bio=" ",               # 34 (a 자서전 / b 전기·평전 / d 부분적 전기)
    type_of_date="s",      # 06
    modified_record=" ",   # 28
    cataloging_src="a",    # 32  ← 기본값 'a'
):
    def pad(s, n, fill=" "):
        s = "" if s is None else str(s)
        return (s[:n] + fill * n)[:n]

    if len(date_entered) != 6 or not date_entered.isdigit():
        raise ValueError("date_entered는 YYMMDD 6자리 숫자여야 합니다.")
    if len(date1) != 4:
        raise ValueError("date1은 4자리여야 합니다. 예: '2025', '19uu'")

    body = "".join([
        date_entered,               # 00-05
        pad(type_of_date,1),        # 06
        date1,                      # 07-10
        pad(date2,4),               # 11-14
        pad(country3,3),            # 15-17
        pad(illus4,4),              # 18-21
        " " * 4,                    # 22-25 (이용대상/자료형태/내용형식) 공백
        " " * 2,                    # 26-27 공백
        pad(modified_record,1),     # 28
        " ",                        # 29 회의간행물
        " ",                        # 30 기념논문집
        has_index if has_index in ("0","1") else "0",  # 31 색인
        pad(cataloging_src,1),      # 32 목록 전거
        pad(lit_form,1),            # 33 문학형식
        pad(bio,1),                 # 34 전기
        pad(lang3,3),               # 35-37 언어
        " " * 2                     # 38-39 (정부기관부호 등) 공백
    ])
    if len(body) != 40:
        raise AssertionError(f"008 length != 40: {len(body)}")
    return body

# 발행연도 추출(알라딘 pubDate 우선)
def extract_year_from_aladin_pubdate(pubdate_str: str) -> str:
    m = re.search(r"(19|20)\d{2}", pubdate_str or "")
    return m.group(0) if m else "19uu"

# 300 발행지 문자열 → country3 추론
def guess_country3_from_place(place_str: str) -> str:
    if not place_str:
        return COUNTRY_FIXED
    for key, code in KR_REGION_TO_CODE.items():
        if key in place_str:
            return code
    # 한국 일반코드("ko ")는 사용하지 않으므로, 기본값으로 통일
    return COUNTRY_FIXED


# ====== 단어 감지 ======
def detect_illus4(text: str) -> str:
    # a: 삽화/일러스트/그림, d: 도표/그래프/차트, o: 사진/화보
    keys = []
    if re.search(r"삽화|삽도|도해|일러스트|일러스트레이션|그림|illustration", text, re.I): keys.append("a")
    if re.search(r"도표|표|차트|그래프|chart|graph", text, re.I):                          keys.append("d")
    if re.search(r"사진|포토|화보|photo|photograph|컬러사진|칼라사진", text, re.I):          keys.append("o")
    out = []
    for k in keys:
        if k not in out:
            out.append(k)
    return "".join(out)[:4]

def detect_index(text: str) -> str:
    return "1" if re.search(r"색인|찾아보기|인명색인|사항색인|index", text, re.I) else "0"

def detect_lit_form(title: str, category: str, extra_text: str = "") -> str:
    blob = f"{title} {category} {extra_text}"
    if re.search(r"서간집|편지|서간문|letters?", blob, re.I): return "i"    # 서간문학
    if re.search(r"기행|여행기|여행 에세이|일기|수기|diary|travel", blob, re.I): return "m"  # 기행/일기/수기
    if re.search(r"시집|산문시|poem|poetry", blob, re.I): return "p"        # 시
    if re.search(r"소설|장편|중단편|novel|fiction", blob, re.I): return "f"  # 소설
    if re.search(r"에세이|수필|essay", blob, re.I): return "e"               # 수필
    return " "

def detect_bio(text: str) -> str:
    if re.search(r"자서전|회고록|autobiograph", text, re.I): return "a"
    if re.search(r"전기|평전|인물 평전|biograph", text, re.I): return "b"
    if re.search(r"전기적|자전적|회고|회상", text): return "d"
    return " "

# 메인: ISBN 하나로 008 생성 (toc/300/041 연동 가능)
def build_008_from_isbn(
    isbn: str,
    *,
    aladin_pubdate: str = "",
    aladin_title: str = "",
    aladin_category: str = "",
    aladin_desc: str = "",
    aladin_toc: str = "",            # 목차가 있으면 감지에 활용
    source_300_place: str = "",      # 300 발행지 문자열(있으면 country3 추정)
    override_country3: str = None,   # 외부 모듈이 주면 최우선
    override_lang3: str = None,      # 외부 모듈이 주면 최우선(041)
    cataloging_src: str = "a",       # 32 목록 전거(기본 'a')
):
    today  = datetime.datetime.now().strftime("%y%m%d")  # YYMMDD
    date1  = extract_year_from_aladin_pubdate(aladin_pubdate)

    # country 우선순위: override > 300발행지 매핑 > 기본값
    if override_country3:
        country3 = override_country3
    elif source_300_place:
        country3 = guess_country3_from_place(source_300_place)
    else:
        country3 = COUNTRY_FIXED

    # lang 우선순위: override(041) > 기본값
    lang3 = override_lang3 or LANG_FIXED

    # 단어 감지용 텍스트: 제목 + 소개 + 목차
    bigtext = " ".join([aladin_title or "", aladin_desc or "", aladin_toc or ""])
    illus4    = detect_illus4(bigtext)
    has_index = detect_index(bigtext)
    lit_form  = detect_lit_form(aladin_title or "", aladin_category or "", bigtext)
    bio       = detect_bio(bigtext)

    return build_008_kormarc_bk(
        date_entered=today,
        date1=date1,
        country3=country3,
        lang3=lang3,
        illus4=illus4,
        has_index=has_index,
        lit_form=lit_form,
        bio=bio,
        cataloging_src=cataloging_src,
    )
# ========= 008 생성 블록 v3 끝 =========

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

        # ← 여기부터 보강된 부분
        msg = response.choices[0].message
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content", "")
        content = content or ""

        # ✂️ “KDC:” 뒤의 숫자만 꺼내서 돌려드립니다
        for line in content.splitlines():
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

# ---- 653 전처리 유틸 ----
def _norm(text: str) -> str:
    import re, unicodedata
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s\uac00-\ud7a3]", " ", text)  # 한/영/숫자/공백만
    return re.sub(r"\s+", " ", text).strip()

def _clean_author_str(s: str) -> str:
    import re
    if not s:
        return ""
    s = re.sub(r"\(.*?\)", " ", s)      # (지은이), (옮긴이) 등 제거
    s = re.sub(r"[/;·,]", " ", s)       # 구분자 공백화
    return re.sub(r"\s+", " ", s).strip()

def _build_forbidden_set(title: str, authors: str) -> set:
    t_norm = _norm(title)
    a_norm = _norm(authors)
    forb = set()
    if t_norm:
        forb.update(t_norm.split())
        forb.add(t_norm.replace(" ", ""))  # '죽음 트릴로지' → '죽음트릴로지'
    if a_norm:
        forb.update(a_norm.split())
        forb.add(a_norm.replace(" ", ""))
    return {f for f in forb if f and len(f) >= 2}  # 1글자 제거

def _should_keep_keyword(kw: str, forbidden: set) -> bool:
    n = _norm(kw)
    if not n or len(n.replace(" ", "")) < 2:
        return False
    for tok in forbidden:
        if tok in n or n in tok:
            return False
    return True
# -------------------------

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
    item = (data.get("item") or [{}])[0]

    # 저자 필드 다양한 키 대응
    raw_author = item.get("author") or item.get("authors") or item.get("author_t") or ""
    authors = _clean_author_str(raw_author)

    return {
        "category": item.get("categoryName", "") or "",
        "title": item.get("title", "") or "",
        "authors": authors,                           # ⬅️ 추가됨
        "description": item.get("description", "") or "",
        "toc": item.get("toc", "") or "",
    }



# ③ GPT-4 기반 653 생성 함수
def generate_653_with_gpt(category, title, authors, description, toc, max_keywords=7):
    parts = [p.strip() for p in (category or "").split(">") if p.strip()]
    cat_kw = parts[-1] if parts else ""

    forbidden = _build_forbidden_set(title, authors)

    system_msg = {
        "role": "system",
        "content": (
            "당신은 도서관 메타데이터 전문가입니다. "
            "책의 분류, 설명, 목차를 바탕으로 MARC 653 주제어를 도출하세요. "
            "서명(245)·저자(100/700)에 존재하는 단어는 제외합니다."
        )
    }
    user_msg = {
        "role": "user",
        "content": (
            f"입력 정보로부터 최대 {max_keywords}개의 MARC 653 주제어를 한 줄로 출력해 주세요.\n\n"
            f"- 분류: \"{cat_kw}\"\n"
            f"- 제목(245): \"{title}\"\n"
            f"- 저자(100/700): \"{authors}\"\n"
            f"- 설명: \"{description}\"\n"
            f"- 목차: \"{toc}\"\n\n"
            "제외어 목록(서명/저자에서 유래): "
            f"{', '.join(sorted(forbidden)) or '(없음)'}\n\n"
            "규칙:\n"
            "1) '제목'과 '저자'에 쓰인 단어·표현은 절대 포함하지 마세요.\n"
            "2) 분류/설명/목차에서 핵심 개념을 명사 중심으로 뽑으세요.\n"
            "3) 출력 형식: $a키워드1 $a키워드2 … (한 줄)\n"
        )
    }
    try:
        resp = gpt_client.chat.completions.create(
            model="gpt-4",
            messages=[system_msg, user_msg],
            temperature=0.2,
            max_tokens=180,
        )
        raw = (resp.choices[0].message.content or "").strip()

        # $a 단위 파싱
        pattern = re.compile(r"\$a(.*?)(?=(?:\$a|$))", re.DOTALL)
        kws = [m.group(1).strip() for m in pattern.finditer(raw)]
        if not kws:
            # 백업 파싱
            tmp = re.split(r"[,\n]", raw)
            kws = [t.strip().lstrip("$a") for t in tmp if t.strip()]

        # 공백 삭제(원하면 유지 가능)
        kws = [kw.replace(" ", "") for kw in kws]

        # 1차: 금칙어(서명/저자) 필터
        kws = [kw for kw in kws if _should_keep_keyword(kw, forbidden)]

        # 2차: 정규화 중복 제거
        seen = set()
        uniq = []
        for kw in kws:
            n = _norm(kw)
            if n not in seen:
                seen.add(n)
                uniq.append(kw)

        # 3차: 최대 개수 제한
        uniq = uniq[:max_keywords]

        return "".join(f"$a{kw}" for kw in uniq)

    except Exception as e:
        st.warning(f"⚠️ 653 주제어 생성 실패: {e}")
        return None
   


# 📚 MARC 생성
@st.cache_data(show_spinner=False)
def fetch_book_data_from_aladin(isbn, reg_mark="", reg_no="", copy_symbol=""):
    import re
    from concurrent.futures import ThreadPoolExecutor

    # 1) 알라딘 + (옵션) 국중 부가기호 동시 요청
    url = (
        f"https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?"
        f"ttbkey={aladin_key}&itemIdType=ISBN&ItemId={isbn}"
        f"&output=js&Version=20131101"
    )
    with ThreadPoolExecutor(max_workers=2) as ex:
        future_aladin = ex.submit(lambda: requests.get(url, verify=False, timeout=5))
        future_nlk    = ex.submit(fetch_additional_code_from_nlk, isbn)

        try:
            resp = future_aladin.result()
            resp.raise_for_status()
            data = resp.json().get("item", [{}])[0]
        except Exception as e:
            st.error(f"🚨 알라딘API 오류: {e}")
            return ""

        add_code = future_nlk.result()  # 실패 시 빈 문자열

    # 2) 메타데이터 (알라딘)
    title       = data.get("title",       "제목없음")
    author      = data.get("author",      "저자미상")
    publisher   = data.get("publisher",   "출판사미상")
    pubdate     = data.get("pubDate",     "2025")  # 'YYYY' 또는 'YYYY-MM-DD'
    category    = data.get("categoryName", "")
    description = data.get("description", "")
    toc         = data.get("subInfo", {}).get("toc", "")
    price       = str(data.get("priceStandard", ""))  # 020/950 용

    # 3) =008 생성 (ISBN만으로 자동, country/lang은 임시 고정값 → 추후 override)
    tag_008 = "=008  " + build_008_from_isbn(
        isbn,
        aladin_pubdate=pubdate,
        aladin_title=title,
        aladin_category=category,
        aladin_desc=description,
        # override_country3="ulk",  # 300 모듈 완성 시 사용
        # override_lang3="kor",     # 041 모듈 완성 시 사용
    )

    # 4) 041/546 (간이 감지: 기존 로직 유지)
    lang_a  = detect_language(title)
    lang_h  = detect_language(data.get("title", ""))
    tag_041 = f"=041  \\$a{lang_a}" + (f"$h{lang_h}" if lang_h != "und" else "")
    tag_546 = f"=546  \\$a{generate_546_from_041_kormarc(tag_041)}"

    # 5) 020 (부가기호 있으면 $g 추가)
    tag_020 = f"=020  \\$a{isbn}"
    if price:
        tag_020 += f":$c{price}"
    if add_code:
        tag_020 += f"$g{add_code}"


    # 6) 653/KDC — ✅ 여기서만 생성 (GPTAPI 최신 함수로 통일)
    kdc     = recommend_kdc(title, author, api_key=openai_key)

    # ⬇️ authors 인자 추가(저자 문자열을 전처리해서 넘김)
    gpt_653 = generate_653_with_gpt(
    category,
    title,
    _clean_author_str(author),   # ← 추가된 부분
    description,
    toc,
    max_keywords=7
    )

    tag_653 = f"=653  \\{gpt_653.replace(' ', '')}" if gpt_653 else ""


    # 7) 기본 MARC 라인
    marc_lines = [
        tag_008,
        "=007  ta",
        f"=245  00$a{title} /$c{author}",
        f"=260  \\$a서울 :$b{publisher},$c{pubdate[:4]}.",
    ]

    # 8) 490·830 (총서)
    series = data.get("seriesInfo", {})
    name = (series.get("seriesName") or "").strip()
    vol  = (series.get("volume")    or "").strip()
    if name:
        marc_lines.append(f"=490  \\$a{name};$v{vol}")
        marc_lines.append(f"=830  \\$a{name};$v{vol}")

    # 9) 기타 필드
    marc_lines.append(tag_020)
    marc_lines.append(tag_041)
    marc_lines.append(tag_546)
    if kdc and kdc != "000":
        marc_lines.append(f"=056  \\$a{kdc}$26")
    if tag_653:
        marc_lines.append(tag_653)
    marc_lines.append(f"=950  0\\$b{price}")

    # 10) 049: 소장기호(입력된 경우만)
    if reg_mark or reg_no or copy_symbol:
        line = f"=049  0\\$I{reg_mark}{reg_no}"
        if copy_symbol:
            line += f"$f{copy_symbol}"
        marc_lines.append(line)

    # 11) 번호 오름차순 정렬 후 출력
    marc_lines.sort(key=lambda L: int(re.match(r"=(\d+)", L).group(1)))
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
