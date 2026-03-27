import pandas as pd
import numpy as np
from neo4j import GraphDatabase
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, average_precision_score
import xgboost as xgb
import joblib
import warnings
import os
from dotenv import load_dotenv
warnings.filterwarnings("ignore")

# ========================= CONFIG =========================
load_dotenv()

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("DOCKER_PASSWORD")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ====================== EXTRACTION (OPTIMIZED) ======================
query = """
MATCH (a:Account)-[r:TRANSFER]->(b:Account)
RETURN 
    r.amount AS amount,
    r.is_laundering AS label,
    r.payment_format AS payment_format,
    
    // Core Graph Features (Instant Subqueries)
    COUNT { (a)-[:TRANSFER]->() } AS src_out_degree,
    COUNT { (a)<-[:TRANSFER]-() } AS src_in_degree,
    COUNT { (b)-[:TRANSFER]->() } AS dest_out_degree,
    COUNT { (b)<-[:TRANSFER]-() } AS dest_in_degree,
    
    // GDS Features (The "Intelligence")
    coalesce(a.pagerank, 0.15) AS src_pagerank,
    coalesce(b.pagerank, 0.15) AS dest_pagerank,
    coalesce(a.community, 0) AS src_community,
    coalesce(b.community, 0) AS dest_community,
    
    // Cluster Logic
    CASE WHEN a.community = b.community AND a.community IS NOT NULL THEN 1 ELSE 0 END AS same_community,
    a.risk_score AS src_risk
"""

print("📥 Extracting features from Neo4j...")
with driver.session() as session:
    result = session.run(query)
    df = pd.DataFrame([record.data() for record in result])

# ====================== FEATURE ENGINEERING ======================
print("⚙️ Engineering fraud-specific features...")

df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
df['label'] = df['label'].fillna(0).astype(int)

# 1. Log Transform (Handles skew)
df['amount_log'] = np.log1p(df['amount'])

# 2. Structuring flag (smurfing pattern)
df['is_structuring'] = ((df['amount'] >= 9000) & (df['amount'] < 10000)).astype(int)

# 3. Round Number Check (Fraudsters often use round increments)
df['is_round_amount'] = (df['amount'] % 100 == 0).astype(int)

# 4. Degree Ratios
df['src_degree_ratio'] = df['src_out_degree'] / (df['src_in_degree'] + 1.0)
df['dest_degree_ratio'] = df['dest_out_degree'] / (df['dest_in_degree'] + 1.0)

# 5. One-Hot Encoding for Format
df = pd.get_dummies(df, columns=['payment_format'], prefix='fmt', dtype='int')

# Final feature list
features = [
    'amount', 'amount_log', 'src_out_degree', 'src_in_degree', 
    'dest_out_degree', 'dest_in_degree', 'src_degree_ratio', 
    'dest_degree_ratio', 'same_community', 'src_pagerank', 
    'dest_pagerank', 'is_structuring', 'is_round_amount', 'src_risk'
]
features += [col for col in df.columns if col.startswith('fmt_')]

X = df[features].fillna(0)
y = df['label']

# ====================== TRAINING ======================
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, stratify=y, random_state=42)

# Imbalance ratio (Boosted by 20% to help Recall)
ratio = ((y_train == 0).sum() / max((y_train == 1).sum(), 1)) * 1.2

model = xgb.XGBClassifier(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.05,
    scale_pos_weight=ratio,
    eval_metric='aucpr', # Focus on Precision-Recall
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42
)

print(f"🚀 Training XGBoost on {len(X_train)} samples...")
model.fit(X_train, y_train)

# ====================== EVALUATION ======================
y_prob = model.predict_proba(X_test)[:, 1]
y_pred = (y_prob > 0.5).astype(int)

print("\n" + "="*45)
print("📊 FINAL PROJECT PERFORMANCE REPORT")
print("="*45)
print(classification_report(y_test, y_pred))
print(f"ROC-AUC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"PR-AUC:  {average_precision_score(y_test, y_prob):.4f}")

# Save model
joblib.dump(model, "aml_model.pkl")
print("\n✅ Saved: aml_model.pkl")
driver.close()