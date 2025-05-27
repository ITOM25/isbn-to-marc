import streamlit as st
import os

st.write("✅ 앱 시작됨")

try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    st.write("🔑 secrets 불러오기 성공")
except Exception as e:
    st.error(f"❌ [에러] secrets 불러오기 실패: {e}")
    raise e  # 반드시 다시 raise해서 로그에 찍히게 함

try:
    import google.generativeai as genai
    genai.configure(api_key=API_KEY)
    st.write("🧠 Gemini 설정 완료")
except Exception as e:
    st.error(f"❌ [에러] Gemini 모듈 문제: {e}")
    raise e

try:
    import requests
    st.write("🌐 requests 모듈 로드 완료")
except Exception as e:
    st.error(f"❌ [에러] requests 모듈 문제: {e}")
    raise e
