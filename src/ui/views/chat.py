"""
AI Chat View - 단순화된 버전
"""

import streamlit as st
import time
from src.rag.retriever import ContextRetriever
from src.llm.client import LLMClient


def render_chat_view(data):
    st.header("🤖 AI Academic Assistant")
    st.caption("학사 정보에 대해 무엇이든 질문하세요.")

    # 채팅 기록 초기화
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {"role": "assistant", "content": "안녕하세요! 이번 주 과제나 공지사항에 대해 무엇이든 물어보세요."}
        ]

    # 채팅 기록 표시
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)

    # 사용자 입력
    if prompt := st.chat_input("Ex: '이번 주 마감 과제 알려줘'"):
        # 사용자 메시지 추가
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)

        # AI 응답 생성
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            
            with st.spinner("생각 중..."):
                try:
                    # 현재 학기
                    current_semester = st.session_state.get("current_semester")
                    
                    # 컨텍스트 검색
                    retriever = ContextRetriever(data, semester=current_semester)
                    relevant_items = retriever.retrieve_context(mode="query", query=prompt)
                    
                    st.caption(f"ℹ️ 검색 결과: {len(relevant_items)}개 항목")
                    
                    # LLM 호출
                    response_text = _generate_response(prompt, relevant_items)
                    
                    # 스트리밍 효과
                    full_response = ""
                    for i in range(0, len(response_text), 5):
                        full_response = response_text[:i+5]
                        time.sleep(0.01)
                        message_placeholder.markdown(full_response + "▌")
                    
                    message_placeholder.markdown(full_response)
                    
                    # 기록에 추가
                    st.session_state["chat_history"].append({
                        "role": "assistant", 
                        "content": full_response
                    })
                    
                    # 참고 자료 표시
                    if relevant_items:
                        with st.expander(f"📚 참고 자료 ({len(relevant_items)}개)", expanded=False):
                            for item in relevant_items[:5]:
                                st.markdown(f"- **{item.get('title', 'No Title')}** ({item.get('course_name', '')})")
                    
                except Exception as e:
                    error_msg = f"오류 발생: {e}"
                    message_placeholder.error(error_msg)
                    st.session_state["chat_history"].append({
                        "role": "assistant",
                        "content": error_msg
                    })


def _generate_response(query: str, context_items: list) -> str:
    """LLM으로 응답 생성"""
    import httpx
    from datetime import datetime
    
    # 컨텍스트 포맷팅
    context_str = ""
    for item in context_items[:10]:
        title = item.get("title", "")
        course = item.get("course_name", "")
        content = str(item.get("content_clean", "") or item.get("body_text", ""))[:500]
        due = item.get("due_date", "")
        context_str += f"- [{course}] {title} (Due: {due})\n  {content[:200]}...\n"
    
    if not context_str:
        context_str = "관련 정보를 찾을 수 없습니다."
    
    # 시스템 프롬프트
    today_str = datetime.now().strftime("%Y-%m-%d %A")
    sys_prompt = f"""You are a helpful academic assistant. Today is {today_str}.
Answer the user's question based on the following course data.
Use Korean and be concise. If you don't know, say so."""

    user_msg = f"Context:\n{context_str}\n\nQuestion: {query}"
    
    try:
        client = LLMClient()
        payload = {
            "model": client.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg}
            ],
            "stream": False,
            "options": {"temperature": 0.3}
        }
        
        with httpx.Client(timeout=60) as c:
            resp = c.post(f"{client.api_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "응답을 생성할 수 없습니다.")
    
    except Exception as e:
        return f"LLM 연결 오류: {e}"
