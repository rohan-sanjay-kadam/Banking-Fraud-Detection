import streamlit as st
from neo4j import GraphDatabase
import pandas as pd
from pyvis.network import Network
# import nx_helper as nxh # Optional, but standard networkx is fine
import networkx as nx
import tempfile
import time
import os
from dotenv import load_dotenv

# ========================= CONFIG & SESSION =========================
load_dotenv()
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("DOCKER_PASSWORD")

# Initialize Session States for Playback and Expansion
if 'explored_nodes' not in st.session_state: st.session_state.explored_nodes = set()
if 'target_acc' not in st.session_state: st.session_state.target_acc = ""
if 'playing' not in st.session_state: st.session_state.playing = False
if 'ts_index' not in st.session_state: st.session_state.ts_index = 0

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ====================== DATA FETCHING ======================

@st.cache_data(ttl=3600)
def get_suspicious_accounts():
    query = """
    MATCH (a:Account)-[r:TRANSFER]->(b:Account)
    WHERE r.is_laundering = 1
    WITH a.id AS acc_id, r.amount AS amt LIMIT 5000 
    RETURN acc_id, COUNT(*) AS flags, SUM(amt) AS total_flagged_amt
    ORDER BY total_flagged_amt DESC LIMIT 50
    """
    with driver.session() as session:
        return pd.DataFrame([dict(rec) for rec in session.run(query)])

@st.cache_data(ttl=600)
def fetch_investigation_data(node_list_tuple):
    query = """
    MATCH (a:Account)-[r:TRANSFER]->(b:Account)
    WHERE a.id IN $ids OR b.id IN $ids
    RETURN a.id as src, b.id as dest, r.amount as amt, 
           r.timestamp as ts, r.is_laundering as is_l
    LIMIT 2000
    """
    with driver.session() as session:
        res = session.run(query, ids=list(node_list_tuple))
        return pd.DataFrame([dict(rec) for rec in res])

def generate_viz(df, use_physics=True):
    net = Network(height="600px", width="100%", directed=True, bgcolor="#ffffff")
    if not use_physics: net.toggle_physics(False)
    for _, row in df.iterrows():
        s_col = "#e74c3c" if row['is_l'] == 1 else "#2ecc71"
        net.add_node(row['src'], label=row['src'], color=s_col, size=25)
        net.add_node(row['dest'], label=row['dest'], color="#2ecc71", size=25)
        net.add_edge(row['src'], row['dest'], title=f"${row['amt']}", 
                     color="#FF0000" if row['is_l'] == 1 else "#1E90FF")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
        net.save_graph(tmp.name)
        return tmp.name

# ====================== SIDEBAR: DISCOVERY & SEARCH ======================
with st.sidebar:
    st.header("🔍 Global Investigation")
    
    # 1. MANUAL SEARCH
    manual_search = st.text_input("Search ANY Account ID", placeholder="Type ID here...")
    if st.button("🚀 Analyze Search ID"):
        if manual_search.strip():
            st.session_state.target_acc = manual_search.strip()
            st.session_state.explored_nodes = {manual_search.strip()}
            st.session_state.ts_index = 0
            st.rerun()

    st.write("---")
    
    # 2. SUSPICIOUS DROP DOWN
    st.subheader("⚠️ High-Risk Leads")
    leads = get_suspicious_accounts()
    selected_lead = st.selectbox("Quick Select Suspicious:", [""] + leads['acc_id'].tolist())
    if selected_lead and selected_lead != st.session_state.target_acc:
        st.session_state.target_acc = selected_lead
        st.session_state.explored_nodes = {selected_lead}
        st.session_state.ts_index = 0
        st.rerun()

# ====================== MAIN DASHBOARD ======================
if st.session_state.target_acc:
    df = fetch_investigation_data(tuple(st.session_state.explored_nodes))
    
    tab1, tab2 = st.tabs(["🌐 Explorer & Search-Expand", "🕒 Automated Playback"])

    # TAB 1: SMART EXPANSION (Searchable)
    with tab1:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.components.v1.html(open(generate_viz(df,use_physics=False), 'r').read(), height=650)
        with c2:
            st.subheader("Expand Node")
            nodes_on_graph = sorted(list(pd.concat([df['src'], df['dest']]).unique()))
            
            # SEARCHABLE SELECTBOX (User can type characters to filter)
            to_expand = st.selectbox("Search Node in Graph:", options=nodes_on_graph, index=0)
            
            if st.button("➕ Expand Selected"):
                st.session_state.explored_nodes.add(to_expand)
                st.rerun()
            if st.button("🧹 Reset"):
                st.session_state.explored_nodes = {st.session_state.target_acc}
                st.rerun()

    # TAB 2: AUTOMATED PLAYBACK & LIVE STATS
    with tab2:
        st.subheader("Live Transaction Playback")
        
        @st.fragment
        def playback_section(data):
            unique_ts = sorted(data['ts'].unique())
            
            # BUTTONS: Step & Play
            col_p, col_l, col_r = st.columns([2, 1, 1])
            
            # Play/Pause Logic
            if col_p.button("▶️ Play / ⏸️ Pause", use_container_width=True):
                st.session_state.playing = not st.session_state.playing

            # Manual Stepping
            if col_l.button("⬅️ Step Back"):
                st.session_state.ts_index = max(0, st.session_state.ts_index - 1)
            if col_r.button("➡️ Step Forward"):
                st.session_state.ts_index = min(len(unique_ts)-1, st.session_state.ts_index + 1)

            # Sync Slider with Button Clicks
            current_ts = st.select_slider(
                "Timeline Slider", 
                options=unique_ts, 
                value=unique_ts[st.session_state.ts_index]
            )
            st.session_state.ts_index = unique_ts.index(current_ts)

            # The Graph
            current_data = data[data['ts'] <= unique_ts[st.session_state.ts_index]]
            st.components.v1.html(open(generate_viz(current_data, use_physics=False), 'r').read(), height=500)

            # LIVE STATS TABLE
            st.divider()
            st.subheader("📊 Live Cumulative Statistics")
            total_amt = current_data['amt'].sum()
            flagged_amt = current_data[current_data['is_l'] == 1]['amt'].sum()
            
            stat_c1, stat_c2 = st.columns(2)
            stat_c1.metric("Total Money Flowed", f"₹{total_amt:,.2f}")
            stat_c2.metric("Flagged/Dirty Money", f"₹{flagged_amt:,.2f}", delta=f"{flagged_amt/total_amt*100:.1f}% Risk")
            
            st.dataframe(current_data.tail(5), use_container_width=True)

            # Auto-Increment logic
            if st.session_state.playing:
                if st.session_state.ts_index < len(unique_ts)-1:
                    time.sleep(1.3) # Adjust for speed
                    st.session_state.ts_index += 1
                    st.rerun()
                else:
                    st.session_state.playing = False
                    st.rerun()

        if not df.empty:
            playback_section(df)
else:
    st.title("AML Fund Flow Hub")
    st.info("👈 Use the Sidebar to search any Account ID or pick from the Suspicious Lead List.")
    st.dataframe(get_suspicious_accounts(), use_container_width=True)