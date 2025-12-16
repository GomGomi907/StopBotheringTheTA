import streamlit as st
from collections import defaultdict

def render_timeline_view(data, state_manager):
    st.header("📅 Weekly Timeline")
    
    # --- Filter Tools ---
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        search_kw = st.text_input("🔍 Search (Title/Course)", "")
    with c2:
        filter_done = st.checkbox("Hide Completed", value=False)
    with c3:
        filter_type = st.multiselect("Filter Type", ["assignment", "material", "notice"], default=[])

    # --- Data Processing ---
    filtered = data
    if search_kw:
        k = search_kw.lower()
        filtered = [x for x in filtered if k in x.get("title", "").lower() or k in x.get("course_name", "").lower()]
    
    if filter_done:
        filtered = [x for x in filtered if not state_manager.is_done(x.get("original_id"))]
        
    if filter_type:
        filtered = [x for x in filtered if x.get("category") in filter_type]
        
    # Group by Week
    weeks = defaultdict(list)
    unknown = []
    for item in filtered:
        w = item.get("week_index")
        if w and isinstance(w, int) and w > 0:
            weeks[w].append(item)
        else:
            unknown.append(item)
            
    sorted_weeks = sorted(weeks.keys())

    # --- Rendering ---
    if not sorted_weeks and not unknown:
        st.info("No items match your filter.")
        return

    # 3 Columns Layout
    cols = st.columns(3)
    
    for i, w in enumerate(sorted_weeks):
        with cols[i % 3]:
            _render_week_column(w, weeks[w], state_manager)
            
    if unknown:
        st.divider()
        st.subheader("📌 Uncategorized / Others")
        ucols = st.columns(3)
        for i, item in enumerate(unknown):
            with ucols[i % 3]:
                _render_item_card(item, state_manager, key_suffix=f"u_{i}")

def _render_week_column(week_idx, items, state_manager):
    st.markdown(f"### 🗓️ Week {week_idx}")
    # Date Sort
    items.sort(key=lambda x: x.get("due_date") or x.get("inferred_date") or "9999")
    
    for i, item in enumerate(items):
        _render_item_card(item, state_manager, key_suffix=f"w{week_idx}_{i}")

def _render_item_card(item, state_manager, key_suffix=""):
    oid = item.get("original_id")
    # [Fix] Handle missing original_id by generating a unique key based on content
    if not oid:
        import hashlib
        # Safely handle None values
        t = item.get('title') or "NoTitle"
        c = item.get('course_name') or "NoCourse"
        content = item.get('content_clean') or ""
        unique_str = f"{t}_{c}_{content[:20]}"
        oid = hashlib.md5(unique_str.encode()).hexdigest()
        
    is_done = state_manager.is_done(oid)
    
    cat = item.get("category", "other")
    title = item.get("title", "No Title")
    cname = item.get("course_name", "")
    content = item.get("content_clean", "")
    
    # Icon & Color
    icon = "🔹"
    if cat == "assignment": icon = "📝"
    elif cat == "material": icon = "📚"
    elif cat == "notice": icon = "📢"
    
    # Visual Strikethrough if done
    title_display = f"~~{title}~~" if is_done else f"**{title}**"
    
    with st.expander(f"{icon} {title_display}"):
        st.caption(f"📘 {cname}")
        st.write(content)
        
        # Checkbox with callback
        # Streamlit checkbox state is tricky with external state manager.
        # We assume immediate update.
        unique_key = f"chk_{oid}_{key_suffix}"
        new_done = st.checkbox("Done", value=is_done, key=unique_key)
        if new_done != is_done:
            state_manager.set_done(oid, new_done)
            st.rerun()
