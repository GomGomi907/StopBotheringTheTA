import streamlit as st
import time
from src.rag.retriever import ContextRetriever
from src.llm.client import LLMClient

def render_chat_view(data):
    st.header("🤖 AI Academic Assistant")
    st.caption("Ask anything about your courses, deadlines, or materials.")

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {"role": "assistant", "content": "안녕하세요! 이번 주 과제나 공지사항에 대해 무엇이든 물어보세요."}
        ]

    # [Layout] Restrict width to ~A4 size (Left aligned) while keeping page wide
    # Using columns: Main Content (Left) | Empty Space (Right)
    main_col, _ = st.columns([2, 1]) 
    
    # [CSS] Constrain Chat Input Width to match 'main_col' (approx A4 on left)
    # Note: Streamlit class names are tricky, simplified attempt
    st.markdown(
        """
        <style>
        .stChatInput {
            max-width: 65% !important;
            margin-right: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with main_col:
        # Display History
        for msg in st.session_state["chat_history"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"], unsafe_allow_html=True) 

    # Input (Root Level -> Fixed to Bottom)
    if prompt := st.chat_input("Ex: '이번 주 마감 과제 알려줘'"):
        # User Message
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        
        # Render actions inside the Main Column to keep alignment
        with main_col:
            # User Bubble
            with st.chat_message("user"):
                st.markdown(prompt, unsafe_allow_html=True)
    
            # Assistant Response
            with st.chat_message("assistant"):
                    message_placeholder = st.empty()
                    full_response = ""
                
                    with st.spinner("지식 베이스 검색 중..."):
                        try:
                            # 1. Retrieve Context
                            retriever = ContextRetriever(data)
                            # Use semantic search if integrated
                            mem0_items = retriever.retrieve_context(mode="query", query=prompt)
                        
                            found_source = f"Mem0AI ({len(mem0_items)})"
                        
                            # [Improvement] Hybrid Search Strategy: Merge Mem0 + Keyword
                            # Always perform keyword search to ensure we don't miss obvious matches
                            # Then dedup by ID (if available) or Title
                        
                            # Keyword Search manual call (since retriever.retrieve_context("query") does mem0)
                            kw_items = []
                            q_tokens = prompt.split()
                            for item in data:
                                if not isinstance(item, dict): continue
                                score = 0
                                text = (item.get("title", "") + " " + item.get("content_clean", "") + " " + item.get("course_name", "")).lower()
                                for t in q_tokens:
                                    if t.lower() in text: score += 1
                                if score > 0: kw_items.append(item)
                            kw_items = kw_items[:10] # Top 10 keywords
                        
                            # Merge (Mem0 priorities first)
                            relevant_items = mem0_items + kw_items
                        
                            # Dedup simple
                            seen = set()
                            final_items = []
                            for it in relevant_items:
                                # Use ID or Title as key
                                k = str(it.get("original_id") or it.get("title"))
                                if k not in seen:
                                    seen.add(k)
                                    final_items.append(it)
                            relevant_items = final_items
                        
                            # Debug Info
                            st.caption(f"ℹ️ Hybrid Search: {len(mem0_items)} (Vector) + {len(kw_items)} (Keyword) -> {len(relevant_items)} unique items")
                        
                            # [Debug] Show Context
                            with st.expander("🔍 Debug: 검색된 컨텍스트 (Retrieved Context)", expanded=False):
                                context_str = _format_context(data, prompt, relevant_items)
                                st.text(context_str)
                        
                            # 2. Generate Answer via LLM
                            client = LLMClient()
                        
                            # Construct Prompt
                            context_str = _format_context(data, prompt, relevant_items)
                        
                            # Call LLM
                            response_text = _simple_llm_chat(client, context_str, prompt)
                        
                            # [Fix] Streaming simulation that preserves newlines!
                            # Previous .split() destroyed Markdown formatting
                            step_size = 5
                            for i in range(0, len(response_text), step_size):
                                full_response = response_text[:i+step_size]
                                time.sleep(0.01)
                                message_placeholder.markdown(full_response + "▌", unsafe_allow_html=True)
                            
                            message_placeholder.markdown(full_response, unsafe_allow_html=True)
                        
                            st.session_state["chat_history"].append({"role": "assistant", "content": full_response})
                        
                            # [UI Improvement] Render Source Cards nicely
                            if relevant_items:
                                with st.expander(f"📚 참고 자료 (Sources) - {len(relevant_items)}개", expanded=False):
                                    for idx, item in enumerate(relevant_items):
                                        with st.container(border=True):
                                            c1, c2 = st.columns([3, 1])
                                            with c1:
                                                # Title with Icon
                                                cat = item.get('category', 'other')
                                                icon = "📝" if cat == "assignment" else "📢" if cat == "notice" else "📄"
                                                st.markdown(f"**{icon} {item.get('title', 'No Title')}**")
                                                st.caption(f"{item.get('course_name')} | {item.get('due_date') or ''}")
                                            with c2:
                                                # Link Button
                                                if item.get("url"):
                                                    st.link_button("View", item.get("url"))
                                            
                                            # Content Preview
                                            content_preview = (item.get('content_clean') or item.get('body_text') or "")[:200]
                                            st.markdown(f"<div style='font-size: 0.8em; color: grey;'>{content_preview}...</div>", unsafe_allow_html=True)
                        
                            # [Auto-Scroll] Scroll to Input Box
                            js = """
                            <script>
                                function scrollDown() {
                                    var input = window.parent.document.querySelector('.stChatInput');
                                    if (input) {
                                        input.scrollIntoView({behavior: "smooth", block: "end"});
                                    }
                                }
                                setTimeout(scrollDown, 500); 
                            </script>
                            """
                            st.components.v1.html(js, height=0, width=0)

                        
                        except Exception as e:
                            st.error(f"Error: {e}")

def _format_context(data, query, relevant_items=None):
    # Use relevant_items from retriever if allowed, else simple scan
    items = relevant_items if relevant_items else data
    
    # If using Keyword fallback (not Mem0), manually filter
    if not relevant_items:
       pass # Fallback logic already handled in render_chat_view
    
    context = "Found Relevant Items:\n"
    for h in items:
        # [Fix] Handle String items (don't skip)
        if isinstance(h, str):
            context += f"- [Raw Text] {h[:500]}\n"
            continue
            
        # Handle Mem0 structure vs Raw structure
        title = h.get('title')
        category = h.get('category')
        content = h.get('content_clean') or h.get('body_text') or ""
        date = h.get('due_date') or h.get('dates', {}).get('due_at')
        cname = h.get('course_name') or h.get('course_id') or "General"
        
        context += f"- [Course: {cname}] [{category}] {title} (Due: {date})\n  Summary: {content[:1000]}\n"
    return context

def _simple_llm_chat(client, context, query):
    import httpx
    from datetime import datetime
    
    today_str = datetime.now().strftime("%Y-%m-%d %A")
    
    sys_prompt = (
        f"You are a helpful academic teaching assistant. Today is **{today_str}**.\n"
        "Your primary role is to answer questions based on the provided **Context** (Course Data).\n"
        "\n"
        "**RESPONSE FORMAT (Strictly Follow)**:\n"
        "1. **Summary**: Start with a summary using '> '. **End the summary with DOUBLE NEWLINES (\\n\\n).**\n"
        "\n"
        "2. **Details (Table)**:\n"
        "   - **MUST** start on a new line (Do NOT put inside blockquote).\n"
        "   - **MUST** use proper Markdown Table syntax with newlines between rows.\n"
        "   | 강의명 | 내용 | 기한 | D-Day |\n"
        "   |---|---|---|---|\n"
        "   | ... | ... | ... | ... |\n"
        "\n"
        "3. **Key Points**: Use Bullet points for details.\n"
        "\n"
        "**Style Rules**:\n"
        "- Use **Bold** for importance.\n"
        "- Use emojis (📅, ⚠️, ✅) liberally.\n"
        "- **CRITICAL**: Ensure there is a blank line before and after the Table.\n"
        "- If info is missing: '관련 정보를 찾을 수 없습니다.'."
    )
    
    user_msg = f"Context:\n{context}\n\nQuestion: {query}"
    
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
        return resp.json().get("message", {}).get("content", "")
