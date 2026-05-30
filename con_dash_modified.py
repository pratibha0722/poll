import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
from pathlib import Path

st.set_page_config(page_title="Conference Analytics Dashboard", layout="wide", page_icon="🧬")

# ─────────────────────────────────────────────────────────────────
# STYLES
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #F1F5F9; }
    .block-container { padding-top: 1.5rem; }
    .metric-card {
        background: white; border-radius: 12px;
        padding: 1.2rem 1.5rem;
        box-shadow: 0 1px 6px rgba(0,0,0,0.08);
        border-left: 4px solid; margin-bottom: 0.5rem;
    }
    .metric-val { font-size: 2rem; font-weight: 700; }
    .metric-lbl { font-size: 0.82rem; color: #64748B; margin-top: 0.1rem; }
    .section-title {
        font-size: 1.1rem; font-weight: 700; color: #1E293B;
        border-left: 4px solid #4F46E5; padding-left: 0.6rem;
        margin: 1.2rem 0 0.6rem 0;
    }
    .insight-box {
        background: #EEF2FF; border-radius: 10px;
        padding: 0.9rem 1.1rem; margin: 0.4rem 0;
        font-size: 0.88rem; color: #312E81;
    }
    .comment-card {
        background: white; border-radius: 10px;
        padding: 0.9rem 1.2rem; margin: 0.5rem 0;
        border-left: 3px solid #4F46E5;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        font-size: 0.88rem;
    }
    .upload-area {
        background: white; border-radius: 16px;
        padding: 2rem; text-align: center;
        box-shadow: 0 2px 12px rgba(0,0,0,0.07);
    }
</style>
""", unsafe_allow_html=True)

PRIMARY = "#4F46E5"
SUCCESS = "#10B981"
WARNING = "#F59E0B"
DANGER  = "#EF4444"

# ─────────────────────────────────────────────────────────────────
# JSON PARSER  — works with the raw API response structure
# ─────────────────────────────────────────────────────────────────
def parse_json(raw: dict) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Accepts the full API JSON.  Returns:
      meta        – program-level info dict
      df_sessions – one row per session
      df_speakers – one row per talk that has feedback
      df_polls    – one row per poll option / question
    """
    # unwrap "data" wrapper if present
    data = raw.get("data", raw)

    meta = {
        "programName": data.get("programName", "Program"),
        "date":        data.get("date", "")[:10],
    }

    sessions_rows = []
    speaker_rows  = []
    poll_rows     = []

    for session in data.get("sessions", []):
        s_name  = session.get("sessionName", "")
        s_start = session.get("startTime", "")[:5]
        s_end   = session.get("endTime",   "")[:5]

        sessions_rows.append({
            "Session":   s_name,
            "StartTime": s_start,
            "EndTime":   s_end,
        })

        for talk in session.get("talks", []):
            topic    = talk.get("topic", "")
            speaker  = talk.get("speakerName", "") or ""
            t_start  = talk.get("startTime", "")[:5]
            t_end    = talk.get("endTime",   "")[:5]
            fb       = talk.get("feedbackSummary", {})

            # ── speaker feedback ──────────────────────────────────
            total_submits = fb.get("totalSubmits", 0)
            if total_submits and total_submits > 0:
                q_ratings = fb.get("questionRatings", [])
                def _find(keyword):
                    for q in q_ratings:
                        if keyword.lower() in q.get("question", "").lower():
                            return q.get("averageAnswer")
                    return None

                speaker_rows.append({
                    "Speaker":    speaker or "Unnamed",
                    "Topic":      topic,
                    "Session":    s_name,
                    "StartTime":  t_start,
                    "Submissions": total_submits,
                    "Avg Rating": round(fb.get("averageRating", 0), 2),
                    "Clarity":    _find("clarity"),
                    "Engagement": _find("engaging"),
                    "Relevance":  _find("relevant"),
                    "Overall":    _find("overall"),
                    "Comments":   [c.get("comment","") for c in fb.get("comments",[]) if c.get("comment")],
                })

            # ── polls ─────────────────────────────────────────────
            for poll in talk.get("pollsSummary", []):
                question   = poll.get("question", "").replace("\n", " ")
                poll_type  = poll.get("type", "QUIZ")
                total_v    = poll.get("totalVotes", 0)
                correct_id = poll.get("correctOptionId", "")

                # aggregate votes per option
                opt_map = {o["optionId"]: {"text": o["text"], "votes": o.get("votesCount", 0)}
                           for o in poll.get("options", [])}

                # count correct from individual votes array (more reliable)
                correct_votes = sum(
                    1 for v in poll.get("votes", []) if v.get("isCorrect") is True
                )
                # fallback to option votesCount if votes array absent
                if not poll.get("votes") and correct_id in opt_map:
                    correct_votes = opt_map[correct_id]["votes"]

                accuracy = round(correct_votes / total_v * 100, 1) if total_v > 0 else 0

                # infer pre/post from session/topic name heuristic
                inferred_type = "Pre-Quiz"
                lower_session = s_name.lower() + " " + topic.lower()
                if any(k in lower_session for k in ["post", "quick quiz", "session 1 quiz",
                                                     "session 2", "session 3", "interactive"]):
                    inferred_type = "Post-Quiz"
                if "pre" in lower_session:
                    inferred_type = "Pre-Quiz"

                poll_rows.append({
                    "Question":      question,
                    "Q_Short":       (question[:50] + "…") if len(question) > 50 else question,
                    "Session":       s_name,
                    "Topic":         topic,
                    "Type":          inferred_type,
                    "Correct":       correct_votes,
                    "Total Votes":   total_v,
                    "Incorrect":     total_v - correct_votes,
                    "Accuracy %":    accuracy,
                })

    df_sessions = pd.DataFrame(sessions_rows)
    df_speakers = pd.DataFrame(speaker_rows) if speaker_rows else pd.DataFrame()
    df_polls    = pd.DataFrame(poll_rows)    if poll_rows    else pd.DataFrame()

    return meta, df_sessions, df_speakers, df_polls


# ─────────────────────────────────────────────────────────────────
# HELPER WIDGETS
# ─────────────────────────────────────────────────────────────────
def kpi(col, val, label, color):
    col.markdown(f"""
    <div class="metric-card" style="border-color:{color}">
        <div class="metric-val" style="color:{color}">{val}</div>
        <div class="metric-lbl">{label}</div>
    </div>""", unsafe_allow_html=True)

def section(title):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)

def insight(text):
    st.markdown(f'<div class="insight-box">{text}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# LOAD JSON FILE
# ─────────────────────────────────────────────────────────────────

st.markdown("## 🧬 Conference Analytics Dashboard")

JSON_FILE = "res.json"  # <-- change filename here

try:
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    st.sidebar.success(f"✅ Loaded: {JSON_FILE}")

except Exception as e:
    st.error(f"❌ Could not load {JSON_FILE}")
    st.error(str(e))
    st.stop()

# ─────────────────────────────────────────────────────────────────
# PARSE
# ─────────────────────────────────────────────────────────────────
try:
    meta, df_sessions, df_speakers, df_polls = parse_json(raw_json)
except Exception as e:
    st.error(f"❌ Failed to parse JSON: {e}")
    st.stop()

if df_polls.empty and df_speakers.empty:
    st.warning("⚠️ JSON parsed successfully but no poll or feedback data was found. "
               "Check that your JSON contains `pollsSummary` or `feedbackSummary` fields inside talks.")
    st.stop()

# ─────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────
prog_name = meta["programName"]
prog_date = meta["date"]
st.markdown(f"**{prog_name}  ·  {prog_date}**")
st.divider()

# ─────────────────────────────────────────────────────────────────
# KPIs
# ─────────────────────────────────────────────────────────────────
total_sessions  = len(df_sessions)
total_polls_q   = len(df_polls) if not df_polls.empty else 0
total_votes     = int(df_polls["Total Votes"].sum()) if not df_polls.empty else 0
overall_acc     = round(df_polls["Correct"].sum() / df_polls["Total Votes"].sum() * 100, 1) \
                  if (not df_polls.empty and total_votes > 0) else 0
rated_speakers  = len(df_speakers)
avg_rating      = round(df_speakers["Avg Rating"].mean(), 2) if not df_speakers.empty else "—"

c1, c2, c3, c4, c5, c6 = st.columns(6)
kpi(c1, total_sessions,  "Sessions",               "#64748B")
kpi(c2, total_polls_q,   "Quiz Questions",          PRIMARY)
kpi(c3, total_votes,     "Total Poll Responses",    SUCCESS)
kpi(c4, f"{overall_acc}%","Overall Quiz Accuracy",  WARNING)
kpi(c5, rated_speakers,  "Speakers w/ Feedback",    "#8B5CF6")
kpi(c6, avg_rating,      "Avg Speaker Rating /5",   SUCCESS if isinstance(avg_rating, float) and avg_rating >= 4.5 else WARNING)

st.divider()

# ─────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────
tabs = st.tabs(["📊 Quiz Performance", "🎤 Speaker Ratings",
                "📈 Session Analysis", "🏆 Delegate Insights", "💬 Feedback & Comments"])

# ══════════════════════════════════════════════
# TAB 1 — QUIZ PERFORMANCE
# ══════════════════════════════════════════════
with tabs[0]:
    if df_polls.empty:
        st.info("No poll data found in this JSON.")
    else:
        c1, c2 = st.columns([3, 2])

        with c1:
            section("Quiz Accuracy per Question")
            fig = px.bar(
                df_polls.sort_values("Accuracy %"),
                x="Accuracy %", y="Q_Short",
                color="Accuracy %",
                color_continuous_scale=["#EF4444", "#F59E0B", "#10B981"],
                orientation="h", text="Accuracy %",
                hover_data={"Question": True, "Total Votes": True, "Correct": True, "Q_Short": False},
            )
            fig.update_traces(texttemplate="%{text}%", textposition="outside")
            fig.update_layout(
                height=max(400, len(df_polls) * 28),
                showlegend=False, coloraxis_showscale=False,
                plot_bgcolor="white", paper_bgcolor="white",
                yaxis=dict(tickfont=dict(size=10)),
                xaxis=dict(range=[0, 115], ticksuffix="%"),
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            section("Accuracy Distribution")
            bins = pd.cut(df_polls["Accuracy %"],
                          bins=[0, 50, 70, 85, 101],
                          labels=["<50%", "50–70%", "70–85%", ">85%"])
            bin_counts = bins.value_counts().reindex(["<50%", "50–70%", "70–85%", ">85%"]).fillna(0)
            fig2 = px.pie(values=bin_counts.values, names=bin_counts.index,
                          color_discrete_sequence=[DANGER, WARNING, "#3B82F6", SUCCESS], hole=0.45)
            fig2.update_traces(textinfo="label+percent+value", pull=[0.05] * 4)
            fig2.update_layout(height=260, margin=dict(l=0,r=0,t=10,b=0),
                               showlegend=False, paper_bgcolor="white")
            st.plotly_chart(fig2, use_container_width=True)

            if df_polls["Type"].nunique() > 1:
                section("Pre vs Post Quiz")
                type_stats = df_polls.groupby("Type").agg(
                    Avg_Accuracy=("Accuracy %", "mean"),
                    Count=("Accuracy %", "count"),
                ).reset_index()
                fig3 = px.bar(type_stats, x="Type", y="Avg_Accuracy",
                              color="Type",
                              color_discrete_map={"Pre-Quiz": PRIMARY, "Post-Quiz": SUCCESS},
                              text="Avg_Accuracy")
                fig3.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                fig3.update_layout(height=260, showlegend=False,
                                   plot_bgcolor="white", paper_bgcolor="white",
                                   yaxis=dict(range=[0,115], ticksuffix="%", title=""),
                                   xaxis_title="",
                                   margin=dict(l=10,r=10,t=10,b=10))
                st.plotly_chart(fig3, use_container_width=True)

        section("Correct vs Incorrect Votes per Question")
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(name="✅ Correct",   x=df_polls["Q_Short"], y=df_polls["Correct"],   marker_color=SUCCESS))
        fig4.add_trace(go.Bar(name="❌ Incorrect", x=df_polls["Q_Short"], y=df_polls["Incorrect"], marker_color=DANGER))
        fig4.update_layout(barmode="stack", height=380,
                           plot_bgcolor="white", paper_bgcolor="white",
                           xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                           legend=dict(orientation="h", y=1.05),
                           margin=dict(l=10,r=10,t=30,b=120))
        st.plotly_chart(fig4, use_container_width=True)

        section("Hardest & Easiest Questions")
        ca, cb = st.columns(2)
        hardest = df_polls.nsmallest(5, "Accuracy %")[["Q_Short","Accuracy %","Total Votes","Session"]]
        easiest = df_polls.nlargest(5,  "Accuracy %")[["Q_Short","Accuracy %","Total Votes","Session"]]
        ca.markdown("**🔴 Most Challenging**")
        ca.dataframe(hardest.rename(columns={"Q_Short":"Question"})
                     .style.background_gradient(subset=["Accuracy %"], cmap="RdYlGn"),
                     use_container_width=True)
        cb.markdown("**🟢 Easiest**")
        cb.dataframe(easiest.rename(columns={"Q_Short":"Question"})
                     .style.background_gradient(subset=["Accuracy %"], cmap="RdYlGn"),
                     use_container_width=True)

# ══════════════════════════════════════════════
# TAB 2 — SPEAKER RATINGS
# ══════════════════════════════════════════════
with tabs[1]:
    if df_speakers.empty:
        st.info("No speaker feedback data found in this JSON.")
    else:
        c1, c2 = st.columns(2)

        with c1:
            section("Overall Speaker Ratings")
            fig = px.bar(
                df_speakers.sort_values("Avg Rating"),
                x="Avg Rating", y="Speaker",
                color="Avg Rating",
                color_continuous_scale=["#F59E0B", "#10B981"],
                orientation="h", text="Avg Rating",
                range_color=[3, 5],
            )
            fig.update_traces(texttemplate="%{text}", textposition="outside")
            fig.update_layout(height=max(250, len(df_speakers)*60),
                              showlegend=False, coloraxis_showscale=False,
                              plot_bgcolor="white", paper_bgcolor="white",
                              xaxis=dict(range=[0, 5.6], title="Rating (out of 5)"),
                              margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            section("Radar: Feedback Dimensions")
            dims = ["Clarity", "Engagement", "Relevance", "Overall"]
            fig2 = go.Figure()
            for _, row in df_speakers.iterrows():
                vals = [row.get(d) for d in dims]
                if any(v is not None for v in vals):
                    clean_vals = [v if v is not None else 0 for v in vals]
                    fig2.add_trace(go.Scatterpolar(
                        r=clean_vals + [clean_vals[0]],
                        theta=dims + [dims[0]],
                        fill="toself", name=row["Speaker"], opacity=0.7,
                    ))
            fig2.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 5])),
                height=320, margin=dict(l=20,r=20,t=20,b=20),
                paper_bgcolor="white", legend=dict(font=dict(size=10)),
            )
            st.plotly_chart(fig2, use_container_width=True)

        section("Dimension Scores by Speaker")
        melt = df_speakers.melt(
            id_vars=["Speaker"], value_vars=dims,
            var_name="Dimension", value_name="Score"
        ).dropna()
        if not melt.empty:
            fig3 = px.bar(melt, x="Speaker", y="Score", color="Dimension",
                          barmode="group", text="Score",
                          color_discrete_sequence=[PRIMARY, SUCCESS, WARNING, "#8B5CF6"])
            fig3.update_traces(texttemplate="%{text}", textposition="outside")
            fig3.update_layout(height=340, plot_bgcolor="white", paper_bgcolor="white",
                               yaxis=dict(range=[0, 5.8], title="Score (0–5)"),
                               xaxis_title="", margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig3, use_container_width=True)

        section("Speaker Feedback Table")
        st.dataframe(
            df_speakers[["Speaker","Topic","Session","Submissions","Avg Rating",
                         "Clarity","Engagement","Relevance","Overall"]]
            .style.background_gradient(subset=["Avg Rating"], cmap="RdYlGn", vmin=3, vmax=5),
            use_container_width=True
        )

# ══════════════════════════════════════════════
# TAB 3 — SESSION ANALYSIS
# ══════════════════════════════════════════════
with tabs[2]:
    if df_polls.empty:
        st.info("No poll data available for session analysis.")
    else:
        session_stats = df_polls.groupby("Session").agg(
            Total_Votes=("Total Votes", "sum"),
            Questions=("Question", "count"),
            Avg_Accuracy=("Accuracy %", "mean"),
        ).reset_index()

        c1, c2 = st.columns(2)
        with c1:
            section("Total Poll Responses per Session")
            fig = px.bar(session_stats, x="Session", y="Total_Votes",
                         color="Session", text="Total_Votes",
                         color_discrete_sequence=px.colors.qualitative.Set2)
            fig.update_traces(textposition="outside")
            fig.update_layout(height=340, showlegend=False,
                              plot_bgcolor="white", paper_bgcolor="white",
                              xaxis=dict(tickangle=-20, tickfont=dict(size=9)),
                              yaxis_title="Total Votes", xaxis_title="",
                              margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            section("Session: Questions × Accuracy × Participation")
            fig2 = px.scatter(session_stats, x="Questions", y="Avg_Accuracy",
                              size="Total_Votes", color="Session",
                              text="Session",
                              color_discrete_sequence=px.colors.qualitative.Set2, size_max=60)
            fig2.update_traces(textposition="top center", textfont=dict(size=9))
            fig2.update_layout(height=340, showlegend=False,
                               plot_bgcolor="white", paper_bgcolor="white",
                               xaxis_title="Number of Questions",
                               yaxis_title="Avg Accuracy (%)",
                               margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig2, use_container_width=True)

        section("Accuracy Heatmap — Session × Question")
        heat = df_polls.pivot_table(
            values="Accuracy %", index="Session", columns="Q_Short", aggfunc="first"
        ).fillna(0)
        fig3 = px.imshow(heat, color_continuous_scale="RdYlGn",
                         aspect="auto", zmin=0, zmax=100, text_auto=".0f")
        fig3.update_layout(height=max(200, len(heat)*50),
                           paper_bgcolor="white",
                           xaxis=dict(tickfont=dict(size=8), tickangle=-40),
                           margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig3, use_container_width=True)

        # Timeline
        section("Session Timeline")
        def to_mins(t):
            try: h, m = map(int, str(t)[:5].split(":")); return h * 60 + m
            except: return 0

        color_map_type = {"Admin":"#94A3B8","Quiz":"#8B5CF6","Scientific":"#3B82F6","Break":"#10B981","Other":"#F59E0B"}

        def infer_type(name):
            n = name.lower()
            if any(k in n for k in ["registration","opening","inauguration","photo"]): return "Admin"
            if any(k in n for k in ["quiz","pre-knowledge","interactive"]): return "Quiz"
            if any(k in n for k in ["session","talk","discussion","panel"]): return "Scientific"
            if any(k in n for k in ["break","lunch","tea","breakfast","high tea"]): return "Break"
            return "Other"

        fig4 = go.Figure()
        for _, row in df_sessions.iterrows():
            start_m = to_mins(row["StartTime"]); end_m = to_mins(row["EndTime"])
            if end_m <= start_m: continue
            t = infer_type(row["Session"])
            fig4.add_trace(go.Bar(
                x=[end_m - start_m], y=[t], base=[start_m], orientation="h",
                marker_color=color_map_type.get(t, "#F59E0B"), opacity=0.85,
                name=row["Session"], showlegend=False,
                hovertemplate=f"<b>{row['Session']}</b><br>{row['StartTime']} – {row['EndTime']}<extra></extra>",
            ))
        all_mins = [to_mins(r["StartTime"]) for _, r in df_sessions.iterrows() if to_mins(r["StartTime"]) > 0]
        if all_mins:
            t_min, t_max = min(all_mins) - 10, max(to_mins(r["EndTime"]) for _, r in df_sessions.iterrows()) + 10
            tick_vals = list(range((t_min//30)*30, t_max, 30))
            tick_txt  = [f"{v//60:02d}:{v%60:02d}" for v in tick_vals]
            fig4.update_layout(barmode="overlay", height=280,
                               xaxis=dict(tickvals=tick_vals, ticktext=tick_txt, title="Time"),
                               yaxis_title="", plot_bgcolor="white", paper_bgcolor="white",
                               margin=dict(l=10,r=10,t=10,b=10))
            for t, c in color_map_type.items():
                fig4.add_trace(go.Bar(x=[0], y=[""], marker_color=c, name=t, showlegend=True))
            st.plotly_chart(fig4, use_container_width=True)

# ══════════════════════════════════════════════
# TAB 4 — DELEGATE INSIGHTS
# ══════════════════════════════════════════════
with tabs[3]:
    if df_polls.empty:
        st.info("No poll data available.")
    else:
        pre_acc  = df_polls[df_polls["Type"] == "Pre-Quiz"]["Accuracy %"]
        post_acc = df_polls[df_polls["Type"] == "Post-Quiz"]["Accuracy %"]
        pre_avg  = round(pre_acc.mean(),  1) if len(pre_acc)  else None
        post_avg = round(post_acc.mean(), 1) if len(post_acc) else None

        c1, c2 = st.columns(2)
        with c1:
            section("Accuracy Distribution — Box Plot")
            fig = go.Figure()
            if len(pre_acc):
                fig.add_trace(go.Box(y=pre_acc,  name="Pre-Quiz",  marker_color=PRIMARY, boxmean=True))
            if len(post_acc):
                fig.add_trace(go.Box(y=post_acc, name="Post-Quiz", marker_color=SUCCESS, boxmean=True))
            fig.update_layout(height=320, plot_bgcolor="white", paper_bgcolor="white",
                              yaxis=dict(ticksuffix="%", title="Accuracy"),
                              margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            section("Question Difficulty Tiers")
            df_polls["Difficulty"] = pd.cut(
                df_polls["Accuracy %"],
                bins=[0, 50, 70, 85, 101],
                labels=["Hard (<50%)", "Medium (50–70%)", "Easy (70–85%)", "Very Easy (>85%)"]
            )
            diff_counts = df_polls["Difficulty"].value_counts()
            fig2 = px.bar(
                x=diff_counts.index, y=diff_counts.values,
                color=diff_counts.index,
                color_discrete_map={"Hard (<50%)": DANGER, "Medium (50–70%)": WARNING,
                                    "Easy (70–85%)": "#3B82F6", "Very Easy (>85%)": SUCCESS},
                text=diff_counts.values,
            )
            fig2.update_traces(textposition="outside")
            fig2.update_layout(height=320, showlegend=False,
                               plot_bgcolor="white", paper_bgcolor="white",
                               xaxis_title="", yaxis_title="No. of Questions",
                               margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig2, use_container_width=True)

        section("Participation by Session")
        ses_vol = df_polls.groupby("Session")["Total Votes"].sum().reset_index()
        fig3 = px.pie(ses_vol, values="Total Votes", names="Session",
                      color_discrete_sequence=px.colors.qualitative.Pastel, hole=0.4)
        fig3.update_traces(textinfo="label+percent")
        fig3.update_layout(height=300, paper_bgcolor="white",
                           margin=dict(l=10,r=10,t=10,b=10), showlegend=False)
        st.plotly_chart(fig3, use_container_width=True)

        section("Cumulative Accuracy Trend (quiz order)")
        df_trend = df_polls.copy().reset_index(drop=True)
        df_trend["Quiz #"] = range(1, len(df_trend) + 1)
        df_trend["Cumulative Avg"] = df_trend["Accuracy %"].expanding().mean()
        fig4 = px.line(df_trend, x="Quiz #", y="Cumulative Avg",
                       markers=True, color="Type",
                       color_discrete_map={"Pre-Quiz": PRIMARY, "Post-Quiz": SUCCESS},
                       hover_data={"Question": True})
        fig4.add_hline(y=overall_acc, line_dash="dash", line_color="gray",
                       annotation_text=f"Overall avg {overall_acc}%")
        fig4.update_layout(height=320, plot_bgcolor="white", paper_bgcolor="white",
                           yaxis=dict(ticksuffix="%", title="Cumulative Avg Accuracy"),
                           margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig4, use_container_width=True)

        # Insights
        section("Key Insights")
        if not df_speakers.empty:
            best_spk = df_speakers.loc[df_speakers["Avg Rating"].idxmax()]
            insight(f"🏅 <b>Top-rated speaker:</b> {best_spk['Speaker']} — {best_spk['Avg Rating']}/5")
        if not df_polls.empty:
            hardest_q = df_polls.loc[df_polls["Accuracy %"].idxmin()]
            easiest_q = df_polls.loc[df_polls["Accuracy %"].idxmax()]
            insight(f"❓ <b>Toughest question:</b> \"{hardest_q['Question'][:80]}…\" — only {hardest_q['Accuracy %']:.0f}% correct")
            insight(f"✅ <b>Best-answered:</b> \"{easiest_q['Question'][:80]}…\" — {easiest_q['Accuracy %']:.0f}% correct")
            best_ses = df_polls.groupby("Session")["Total Votes"].sum().idxmax()
            insight(f"📊 <b>Most engaged session:</b> {best_ses}")
        if pre_avg and post_avg:
            delta = post_avg - pre_avg
            insight(f"📈 <b>Learning impact:</b> Accuracy shifted from {pre_avg}% (pre) → {post_avg}% (post) "
                    f"— a {'↑ ' if delta >= 0 else '↓ '}{abs(delta):.1f} pp {'gain' if delta >= 0 else 'drop'}.")

# ══════════════════════════════════════════════
# TAB 5 — FEEDBACK & COMMENTS
# ══════════════════════════════════════════════
with tabs[4]:
    if df_speakers.empty:
        st.info("No feedback data found.")
    else:
        # Comments
        section("Delegate Comments")
        any_comment = False
        for _, row in df_speakers.iterrows():
            for c in row.get("Comments", []):
                any_comment = True
                st.markdown(f"""
                <div class="comment-card">
                    💬 &nbsp;<i>"{c}"</i>
                    <br><small style="color:#94A3B8">— <b>{row['Topic']}</b> &nbsp;|&nbsp; {row['Session']}</small>
                </div>""", unsafe_allow_html=True)
        if not any_comment:
            st.info("No text comments were submitted.")

        # Per-speaker deep-dive
        section("Speaker Deep-Dive")
        selected = st.selectbox("Select speaker", df_speakers["Speaker"].tolist())
        row = df_speakers[df_speakers["Speaker"] == selected].iloc[0]
        dims = ["Clarity", "Engagement", "Relevance", "Overall"]

        c1, c2 = st.columns(2)
        with c1:
            for d in dims:
                v = row.get(d)
                if v is not None:
                    pct = int(v / 5 * 100)
                    color = SUCCESS if v >= 4.5 else (WARNING if v >= 3.5 else DANGER)
                    st.markdown(f"""
                    <div style="margin:0.4rem 0">
                        <div style="display:flex;justify-content:space-between;
                                    font-size:0.85rem;margin-bottom:2px">
                            <span>{d}</span><span><b>{v}/5</b></span>
                        </div>
                        <div style="background:#E2E8F0;border-radius:6px;height:10px">
                            <div style="background:{color};width:{pct}%;
                                        height:10px;border-radius:6px"></div>
                        </div>
                    </div>""", unsafe_allow_html=True)
            st.markdown(f"<br><b>Topic:</b> {row['Topic']}<br>"
                        f"<b>Session:</b> {row['Session']}<br>"
                        f"<b>Feedback submissions:</b> {row['Submissions']}",
                        unsafe_allow_html=True)
        with c2:
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=row["Avg Rating"],
                title={"text": "Avg Rating"},
                gauge={
                    "axis": {"range": [0, 5]},
                    "bar":  {"color": PRIMARY},
                    "steps": [
                        {"range": [0, 3], "color": "#FEE2E2"},
                        {"range": [3, 4], "color": "#FEF3C7"},
                        {"range": [4, 5], "color": "#D1FAE5"},
                    ],
                    "threshold": {"line": {"color": "red", "width": 3}, "value": 4},
                },
            ))
            fig.update_layout(height=260, margin=dict(l=20,r=20,t=30,b=10),
                              paper_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

# ─────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f"<small style='color:#94A3B8'>Conference Analytics Dashboard · {prog_name} · {prog_date}</small>",
    unsafe_allow_html=True
)
