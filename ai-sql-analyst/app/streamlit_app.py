"""Chat with the warehouse.   streamlit run app/streamlit_app.py"""
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlanalyst.agent import STRATEGIES, SQLAgent  # noqa: E402
from sqlanalyst.catalog import Catalog  # noqa: E402
from sqlanalyst.db import Database  # noqa: E402
from sqlanalyst.llm import AnthropicLLM  # noqa: E402

st.set_page_config(page_title="AI SQL Analyst", page_icon="🔎", layout="wide")

EXAMPLES = [
    "What are the top 5 product categories by revenue?",
    "Show monthly revenue for 2018",
    "How does late delivery affect review scores?",
    "Which states have the slowest delivery?",
    "What share of revenue comes from repeat customers?",
]


@st.cache_resource
def get_db():
    return Database()


@st.cache_resource
def get_agent(strategy: str, model: str):
    return SQLAgent(AnthropicLLM(model), get_db(), Catalog(), strategy=strategy)


def summarize(agent: SQLAgent, question: str, ans) -> str:
    """Ask the model for a 1-2 sentence plain-English answer grounded in the result rows."""
    preview = ans.data.head(20).to_csv(index=False)
    reply = agent.llm.complete(
        "You are a concise data analyst. Answer in at most two sentences using ONLY the numbers "
        "in the result. Do not speculate beyond the data.",
        [{"role": "user", "content": f"Question: {question}\n\nSQL result (CSV):\n{preview}"}])
    return reply.text


with st.sidebar:
    st.header("Settings")
    strategy = st.selectbox("Strategy", list(STRATEGIES), index=list(STRATEGIES).index("full"),
                            help="full = schema retrieval + few-shot examples + self-correction")
    model = st.text_input("Claude model", os.getenv("SQLANALYST_MODEL", "claude-haiku-4-5"))
    explain = st.toggle("Plain-English answer", value=True)
    st.divider()
    st.caption("Try:")
    for ex in EXAMPLES:
        if st.button(ex, use_container_width=True):
            st.session_state["pending"] = ex
    with st.expander("Warehouse schema"):
        st.code(Catalog().schema_text(), language="sql")

st.title("🔎 AI SQL Analyst")
st.caption("Ask a business question about the Olist marketplace. Every answer shows the SQL it ran.")

if not os.getenv("ANTHROPIC_API_KEY"):
    st.warning("Set ANTHROPIC_API_KEY in your environment to start asking questions.")
    st.stop()

st.session_state.setdefault("history", [])
for turn in st.session_state["history"]:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])

question = st.chat_input("e.g. Which categories have the worst reviews?") or st.session_state.pop("pending", None)
if question:
    st.session_state["history"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        agent = get_agent(strategy, model)
        with st.spinner("Writing and running SQL..."):
            ans = agent.ask(question)
        if not ans.ok:
            st.error(ans.error)
            text = f"Couldn't answer: {ans.error}"
        else:
            if explain:
                text = summarize(agent, question, ans)
                st.markdown(text)
            else:
                text = f"{len(ans.data)} rows"
            if ans.chart:
                chart_df = ans.data.set_index(ans.chart["x"])[ans.chart["y"]]
                (st.line_chart if ans.chart["type"] == "line" else st.bar_chart)(chart_df)
            st.dataframe(ans.data, use_container_width=True, hide_index=True)
            st.download_button("Download CSV", ans.data.to_csv(index=False), "result.csv")
        with st.expander(f"SQL · {len(ans.attempts)} attempt(s) · {ans.latency_s:.1f}s · ${ans.cost_usd:.4f}"):
            for i, a in enumerate(ans.attempts, 1):
                st.code(a.sql, language="sql")
                if a.error:
                    st.caption(f"Attempt {i} failed: {a.error}")
            st.caption("Tables given to the model: " + ", ".join(ans.tables_used_in_prompt))
    st.session_state["history"].append({"role": "assistant", "content": text})
