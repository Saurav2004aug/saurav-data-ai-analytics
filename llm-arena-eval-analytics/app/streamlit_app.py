"""Interactive dashboard for the Arena evaluation results.

    streamlit run app/streamlit_app.py

Reads the tables written by scripts/run_pipeline.py (reports/tables/*).
"""
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arena_eval.data import load_table  # noqa: E402

REPORTS = ROOT / "reports"
TABLES = REPORTS / "tables"
BLUE, ORANGE, INK_2 = "#2a78d6", "#eb6834", "#52514e"
DIVERGING = [[0, ORANGE], [0.5, "#f4f3ef"], [1, BLUE]]
SEQUENTIAL = [[0, "#eef4fc"], [0.5, "#9cc2ef"], [1, "#123f78"]]
SEQUENTIAL_R = [[0, "#123f78"], [0.5, "#9cc2ef"], [1, "#eef4fc"]]  # rank 1 = darkest

st.set_page_config(page_title="Arena Eval Analytics", page_icon="📊", layout="wide")


@st.cache_data
def load(name: str) -> pd.DataFrame:
    return load_table(TABLES / name)


@st.cache_data
def metrics() -> dict:
    return json.loads((REPORTS / "metrics.json").read_text())


try:
    m = metrics()
    lb = load("leaderboard")
except FileNotFoundError:
    st.error("No results yet. Run `python scripts/run_pipeline.py` first.")
    st.stop()

st.title("LLM Evaluation Analytics: Chatbot Arena")
st.caption(f"Source: {m['source']} · {m['n_battles']:,} battles · {m['n_models']} models · "
           f"{m['n_boot']} bootstrap rounds")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Leader", lb["model"].iloc[0], f"{lb['rating'].iloc[0]:.0f} rating", delta_color="off")
c2.metric("First-position win share", f"{m['position']['a_win_share']:.1%}",
          f"p = {m['position']['p_value']:.1g}", delta_color="off")
c3.metric("Longer response win share", f"{m['length']['longer_win_share']:.1%}",
          f"p = {m['length']['p_value']:.1g}", delta_color="off")
judge_label = "LLM-judge κ" + (" (mock)" if m["judge"]["backend"] == "mock" else "")
c4.metric(judge_label, f"{m['judge']['cohen_kappa']:.2f}",
          f"{m['judge']['agreement_decisive']:.0%} decisive agreement", delta_color="off")

tab_lb, tab_h2h, tab_bias, tab_topic, tab_judge, tab_data = st.tabs(
    ["Leaderboard", "Head-to-head", "Evaluator bias", "Topics", "LLM judge", "Data"])

# --------------------------------------------------------------------------- #
with tab_lb:
    ordered = lb.sort_values("rating")
    fig = go.Figure(go.Scatter(
        x=ordered["rating"], y=ordered["model"], mode="markers",
        marker=dict(color=BLUE, size=10, line=dict(color="white", width=2)),
        error_x=dict(type="data", symmetric=False, color=BLUE, thickness=2, width=0,
                     array=ordered["ci_high"] - ordered["rating"],
                     arrayminus=ordered["rating"] - ordered["ci_low"]),
        customdata=ordered[["ci_low", "ci_high", "rank_ub"]],
        hovertemplate="<b>%{y}</b><br>Rating %{x:.0f}<br>95% CI %{customdata[0]:.0f}–"
                      "%{customdata[1]:.0f}<br>Statistical rank %{customdata[2]}<extra></extra>",
    ))
    fig.update_layout(height=40 * len(lb) + 120, xaxis_title="Bradley-Terry rating (95% CI)",
                      yaxis_title=None, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("**Statistical rank** = 1 + number of models whose CI lies entirely above "
                "this model's CI. Models sharing a rank are not reliably distinguishable.")
    st.dataframe(lb, hide_index=True, use_container_width=True)

    elo = load("online_elo").rename(columns={"elo": "online_elo"})
    comp = lb[["model", "rating"]].merge(elo, on="model")
    st.subheader("Online Elo vs Bradley-Terry")
    fig = px.scatter(comp, x="rating", y="online_elo", text="model",
                     color_discrete_sequence=[BLUE])
    fig.update_traces(textposition="top center", marker=dict(size=10))
    st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------- #
with tab_h2h:
    kind = st.radio("Win matrix", ["Predicted (BT model)", "Observed"], horizontal=True)
    wm = load("win_matrix_pred" if kind.startswith("Pred") else "win_matrix_obs").set_index("model")
    order = [x for x in lb["model"] if x in wm.index]
    wm = wm.loc[order, order]
    counts = load("battle_counts").set_index("model").reindex(index=order, columns=order)
    fig = px.imshow(wm, color_continuous_scale=DIVERGING, zmin=0, zmax=1, text_auto=".2f",
                    aspect="auto", labels=dict(color="P(row beats col)"))
    fig.update_traces(customdata=counts.values,
                      hovertemplate="%{y} vs %{x}<br>Win prob %{z:.2f}<br>"
                                    "Battles %{customdata}<extra></extra>")
    fig.update_layout(height=60 + 38 * len(order))
    st.plotly_chart(fig, use_container_width=True)

    a, b = st.columns(2)
    m1 = a.selectbox("Model A", order, index=0)
    m2 = b.selectbox("Model B", order, index=1)
    if m1 != m2:
        st.info(f"Predicted: **{m1}** beats **{m2}** with probability "
                f"**{load('win_matrix_pred').set_index('model').loc[m1, m2]:.1%}** "
                f"({int(counts.loc[m1, m2]) if pd.notna(counts.loc[m1, m2]) else 0} direct battles).")

# --------------------------------------------------------------------------- #
with tab_bias:
    left, right = st.columns(2)
    with left:
        st.subheader("Length bias")
        curve = load("length_curve")
        fig = go.Figure([
            go.Scatter(x=pd.concat([curve["log_ratio_mid"], curve["log_ratio_mid"][::-1]]),
                       y=pd.concat([curve["ci_high"], curve["ci_low"][::-1]]),
                       fill="toself", fillcolor="rgba(42,120,214,0.15)", line=dict(width=0),
                       hoverinfo="skip", showlegend=False),
            go.Scatter(x=curve["log_ratio_mid"], y=curve["a_win_share"], mode="lines+markers",
                       line=dict(color=BLUE, width=2), marker=dict(size=8), showlegend=False,
                       customdata=curve["n"],
                       hovertemplate="log ratio %{x:.2f}<br>A wins %{y:.1%}<br>n=%{customdata}"
                                     "<extra></extra>"),
        ])
        fig.add_hline(y=0.5, line_dash="dash", line_color=INK_2)
        fig.update_layout(xaxis_title="log(len A / len B)", yaxis_title="A win share",
                          yaxis_tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Raw vs length-controlled rating")
        shift = load("style_shift").sort_values("rating")
        fig = go.Figure()
        for _, r in shift.iterrows():
            fig.add_shape(type="line", x0=r["rating"], x1=r["rating_style_ctrl"],
                          y0=r["model"], y1=r["model"], line=dict(color="#e6e5e0", width=3))
        fig.add_scatter(x=shift["rating"], y=shift["model"], mode="markers", name="Raw",
                        marker=dict(color=BLUE, size=10))
        fig.add_scatter(x=shift["rating_style_ctrl"], y=shift["model"], mode="markers",
                        name="Length-controlled", marker=dict(color=ORANGE, size=10))
        fig.update_layout(height=40 * len(shift) + 120, legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Tie rate vs rating gap")
    ties = load("tie_by_gap")
    fig = px.line(ties, x="gap_mid", y="tie_rate", markers=True,
                  color_discrete_sequence=[BLUE],
                  labels={"gap_mid": "Rating gap between models", "tie_rate": "Tie rate"})
    fig.update_layout(yaxis_tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Healthy voters tie more when models are close; a flat line suggests ties are noise.")

# --------------------------------------------------------------------------- #
with tab_topic:
    tl = load("topic_leaderboards")
    mat = tl.pivot_table(index="model", columns="topic", values="rank")
    mat = mat.reindex([x for x in lb["model"] if x in mat.index])
    fig = px.imshow(mat, color_continuous_scale=SEQUENTIAL_R, text_auto=".0f", aspect="auto", labels=dict(color="Rank"))
    fig.update_layout(height=60 + 38 * len(mat))
    st.plotly_chart(fig, use_container_width=True)
    topic = st.selectbox("Topic leaderboard", sorted(tl["topic"].unique()))
    st.dataframe(tl[tl["topic"] == topic].drop(columns="topic"), hide_index=True,
                 use_container_width=True)

# --------------------------------------------------------------------------- #
with tab_judge:
    jr = load("judge_results")
    if m["judge"]["backend"] == "mock":
        st.warning("These results come from the offline **mock** judge and are placeholders. "
                   "Run the pipeline with `--judge anthropic` for real findings.")
    a, b, c = st.columns(3)
    a.metric("Cohen's κ", f"{m['judge']['cohen_kappa']:.3f}")
    b.metric("Agreement (decisive)", f"{m['judge']['agreement_decisive']:.1%}")
    c.metric("Position consistency", f"{m['judge']['position_consistency']:.1%}")
    cm = pd.crosstab(jr["human"], jr["judge"]).reindex(index=["A", "B", "tie"],
                                                       columns=["A", "B", "tie"], fill_value=0)
    fig = px.imshow(cm, text_auto=True, color_continuous_scale=SEQUENTIAL,
                    labels=dict(x="Judge verdict", y="Human verdict", color="Count"))
    st.plotly_chart(fig, use_container_width=True)
    per_model = (jr.assign(agree=jr["human"] == jr["judge"])
                   .melt(id_vars=["agree"], value_vars=["model_a", "model_b"], value_name="model")
                   .groupby("model", as_index=False)["agree"].mean().sort_values("agree"))
    st.subheader("Judge-human agreement by model involved")
    fig = px.bar(per_model, x="agree", y="model", orientation="h",
                 color_discrete_sequence=[BLUE], labels={"agree": "Agreement", "model": ""})
    fig.update_layout(xaxis_tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------- #
with tab_data:
    st.subheader("Downloads")
    for name in ["leaderboard", "style_shift", "topic_leaderboards", "judge_results"]:
        df = load(name)
        st.download_button(f"{name}.csv", df.to_csv(index=False), file_name=f"{name}.csv")
    summary = REPORTS / "summary.md"
    if summary.exists():
        with st.expander("Static report (summary.md)"):
            st.markdown(summary.read_text().split("## Figures")[0])
