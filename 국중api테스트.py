import requests
import xml.etree.ElementTree as ET
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_additional_code_from_nlk(isbn):
    nlk_key = "732621025ef3ad9ef1bd2975c6aab5ea42c7fdb889129a85ebeb865361f360bc"
    url = f"https://www.nl.go.kr/seoji/SearchApi.do?cert_key={nlk_key}&result_style=xml&page_no=1&page_size=10&isbn={isbn}"

    try:
        response = requests.get(url, timeout=30, verify=False)  # 시간 늘리기
        response.encoding = 'utf-8'
        root = ET.fromstring(response.text)

        doc = root.find('.//docs/e')
        add_code = doc.findtext('ADDCODE')
        return add_code or ""

    except Exception as e:
        print("❌ 오류 발생:", e)
        return ""

if __name__ == "__main__":
    isbn = "9791141609597"
    print("📡 부가기호:", fetch_additional_code_from_nlk(isbn))
