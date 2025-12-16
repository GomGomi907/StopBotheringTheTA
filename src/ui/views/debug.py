import streamlit as st
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

def load_all_records():
    path = Path("data/raw/records.jsonl")
    if not path.exists():
        return []
        
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except: pass
    return records

def render_debug_view():
    st.header("🐞 Crawler Debugger")
    
    # 1. Load Data
    records = load_all_records()
    if not records:
        st.warning("No raw records found. 텅 비었습니다!")
        return
        
    st.success(f"Loaded {len(records)} raw records.")
    
    # 2. Filter Controls
    courses = sorted(list(set([str(r.get("payload", {}).get("course_id", "Unknown")) for r in records])))
    selected_course = st.selectbox("Select Course ID", ["All"] + courses)
    
    # 3. Filter Data
    filtered = records
    if selected_course != "All":
        filtered = [r for r in records if str(r.get("payload", {}).get("course_id", "Unknown")) == selected_course]
        
    st.subheader(f"Records ({len(filtered)})")
    
    # 4. Visualization (Table)
    # Convert to simple Dict for DF
    df_data = []
    for r in filtered:
        p = r.get("payload", {})
        df_data.append({
            "Category": r.get("category"),
            "Title": r.get("title") or p.get("title"),
            "Type": p.get("type"),
            "ID": r.get("id"),
            "URL": r.get("url"),
            "Updated": r.get("updated_at")
        })
        
    if df_data:
        st.dataframe(pd.DataFrame(df_data), use_container_width=True)
        
    # 5. Detail Inspector
    st.divider()
    st.subheader("🔍 Detail Inspector")
    idx = st.number_input("Select Index to Inspect", 0, len(filtered)-1, 0)
    if filtered:
        item = filtered[idx]
        st.write(f"**[{item.get('category')}] {item.get('title')}**")
        st.json(item)
