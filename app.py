import streamlit as st
from neo4j import GraphDatabase
import pandas as pd
from pyvis.network import Network
import networkx as nx
import tempfile
import os
from dotenv import load_dotenv
# ========================= CONFIG =========================
load_dotenv()
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("DOCKER_PASSWORD")

st.set_page_config(page_title="AML Fund Flow Tracker", layout="wide")
st.title("🛡️ Intelligent Fund Flow Tracking System")
st.markdown("### Anti-Money Laundering & Fraud Detection using Graph Analytics + Neo4j")

# ====================== NEO4J CONNECTION ======================
@st.cache_resource
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

driver = get_driver()

# ====================== MAIN DASHBOARD ======================
st.sidebar.header("Investigation Panel")
account_id = st.sidebar.text_input("Enter Account ID", placeholder="Enter Account ID from your sample")

if st.sidebar.button("🔍 Analyze Fund Flow", type="primary"):
    if not account_id.strip():
        st.error("Please enter a valid Account ID")
    else:
        with st.spinner("Querying Neo4j and generating visualization..."):

            query = """
            MATCH p = (a:Account)-[r:TRANSFER*1..3]->(b:Account)
            WHERE a.id = $account_id
            RETURN p
            LIMIT 120
            """

            with driver.session() as session:
                result = session.run(query, account_id=account_id)
                records = list(result)

            if not records:
                st.warning(f"Account **{account_id}** not found in the current sample.")
            else:
                G = nx.DiGraph()
                laundering_edges = set()
                total_amount = 0

                # ================= GRAPH BUILD =================
                for record in records:
                    path = record["p"]
                    nodes = path.nodes
                    rels = path.relationships

                    for i in range(len(rels)):
                        u = nodes[i]["id"]
                        v = nodes[i+1]["id"]

                        amt = rels[i]["amount"]
                        is_l = rels[i]["is_laundering"]

                        total_amount += amt

                        G.add_node(u, label=u[:10] + "..." if len(u) > 12 else u)
                        G.add_node(v, label=v[:10] + "..." if len(v) > 12 else v)

                        G.add_edge(u, v, amount=amt, is_laundering=is_l)

                        if is_l == 1:
                            laundering_edges.add((u, v))

                # ================= VISUALIZATION =================
                net = Network(
                    height="750px",
                    width="100%",
                    directed=True,
                    bgcolor="#ffffff",
                    font_color="black"
                )

                net.from_nx(G)

                # Node styling
                for node in net.nodes:
                    node["size"] = 25
                    node["font"] = {"size": 14}
                    node["color"] = "#90EE90"  # light green

                # Edge styling
                for edge in net.edges:
                    if (edge["from"], edge["to"]) in laundering_edges:
                        edge["color"] = "#FF0000"
                        edge["width"] = 4
                        edge["title"] = "Suspicious Transaction"
                    else:
                        edge["color"] = "#1E90FF"
                        edge["width"] = 2
                        edge["title"] = "Normal Transaction"

                # Save graph
                with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmp:
                    net.save_graph(tmp.name)
                    html_path = tmp.name

                # ================= DASHBOARD LAYOUT =================
                col1, col2 = st.columns([3, 1])

                with col1:
                    st.subheader(f"Fund Flow Visualization for Account: **{account_id}**")
                    st.components.v1.html(open(html_path, "r", encoding="utf-8").read(), height=750)

                with col2:
                    st.subheader("Risk Summary")

                    laundering_count = len(laundering_edges)

                    st.metric("Connected Nodes", len(G.nodes))
                    st.metric("Total Transactions", len(G.edges))
                    st.metric("Suspicious Transactions", laundering_count)
                    st.metric("Total Amount Flow", f"₹ {total_amount:,.0f}")

                    # Risk Logic
                    if laundering_count > 5:
                        st.error("🚨 HIGH RISK ACCOUNT")
                    elif laundering_count > 0:
                        st.warning("⚠️ MEDIUM RISK ACCOUNT")
                    else:
                        st.success("✅ LOW RISK ACCOUNT")

                os.unlink(html_path)

# ====================== SIDEBAR HELP ======================
st.sidebar.markdown("---")
st.sidebar.markdown("### How to Use")
st.sidebar.markdown("""
1. Enter Account ID  
2. Click Analyze  
3. Red edges = Suspicious transactions  
4. Blue edges = Normal transactions  
""")