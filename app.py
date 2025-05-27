import streamlit as st
import requests
import google.generativeai as genai
import os
os.environ["CURL_CA_BUNDLE"] = ""

# 🔐 API 키 환경변수에서 불러오기
API_KEY = os.getenv("GEMINI_API_KEY", "")  # 로컬에서는 .env에서 불러올 수 있게 하고, 배포 환경에서도 설정 가능
genai.configure(api_key=API_KEY)

# 💬 Gemini 프롬프트 → KDC 추천 함수
def recommend_kdc(title, author):
    prompt = f"""도서 제목: {title}
저자: {author}
이 책에 가장 적절한 한국십진분류(KDC) 번호 1개를 추천해줘.
정확한 숫자만 아래 형식처럼 간결하게 말해줘:
KDC: 813.7"""
    try:
        # 🧠 최신 모델 사용
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
        response = model.generate_content(prompt)
        st.write("🧠 Gemini 응답 원문:", response.text)
        lines = response.text.strip().splitlines()
        for line in lines:
            if "KDC:" in line:
                return line.replace("KDC:", "").strip()
    except Exception as e:
        st.error(f"❌ Gemini 오류 발생: {e}")
        return "000"
    return "000"
