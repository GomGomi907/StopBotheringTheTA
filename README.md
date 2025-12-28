# 🎓 Smart Academic Dashboard for Dankook Univ

![Project Status](https://img.shields.io/badge/Term%20Project-2025-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![Streamlit](https://img.shields.io/badge/Streamlit-1.40+-red)

> **2025-2 LLM Term Project**
> 
> An AI-powered centralized academic dashboard that crawls LMS data and provides intelligent analytics, summaries, and Q&A using **Local LLM (Ollama gpt-oss:20B)** and **Mem0 (Memory Layer)**.

## 📌 Project Overview
Students often struggle with scattered academic information (LMS, Portal, Manual Notes). This project resolves this by:
1.  **Automating Data Collection**: Crawling Canvas LMS & Portal.
2.  **Structuring Unstructured Data**: Using LLM to extract dates, importance, and context from texts.
3.  **Providing Smart Interaction**: RAG-based Q&A and personalized briefing.

## ✨ Key Features
- **Smart Crawler**: Fetches Course Syllabus, Announcements, Assignments, Files, and External Tools.
- **AI ETL Pipeline**: Cleans and organizes raw JSON logs into a structured Knowledge Base.
- **Interactive Dashboard**:
  - **Home**: Weekly Progress & Urgent Tasks (D-Day).
  - **Timeline**: Gantt chart view of the semester.
  - **AI Chat**: Ask anything about your courses (e.g., "What is the midterm scope?").
- **UX Enhancements**:
  - Dark Mode support.
  - Sticky Navigation Tabs.
  - Real-time ETL Progress Tracking.

## 🛠️ Installation

```bash
# 1. Clone Repository
git clone https://github.com/your-username/dc-term-project-llm.git
cd dc-term-project-llm

# 2. Install Dependencies
pip install -r requirements.txt
playwright install

# 3. Run Application
streamlit run dashboard.py
```

## 📂 Project Structure
```
d:\학사크롤러\
├── src\
│   ├── domains\       # Crawler Logic (Canvas, Portal)
│   ├── etl\           # LLM-based Data Structuring
│   ├── llm\           # LLM Client & RAG
│   └── ui\            # Streamlit Views
├── data\              # Local DB (Ignored)
├── dashboard.py       # Main Entry Point
└── dashboard.py       # Main Entry Point
```


