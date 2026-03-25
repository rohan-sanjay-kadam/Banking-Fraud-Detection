import pandas as pd
from neo4j import GraphDatabase
from tqdm import tqdm
import warnings
warnings.filterwarnings("ignore")

# ========================= CONFIG =========================
TRANS_CSV_PATH = "data/HI-Small_Trans.csv"
SAMPLE_ACCOUNTS = 50000                    # Safe for your 8GB RAM laptop
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "Optimisticbull@7"

print("=== AML Fund Flow Tracker - Neo4j Setup ===\n")

# ====================== LOAD TRANSACTIONS ======================
print("Loading HI-Small_Trans.csv ...")
trans_df = pd.read_csv(TRANS_CSV_PATH)

# Standardize column names
trans_df = trans_df.rename(columns={
    'Account': 'from_account',
    'Account.1': 'to_account',
    'Amount Paid': 'amount',
    'Payment Currency': 'currency',
    'Payment Format': 'payment_format',
    'Is Laundering': 'is_laundering',
    'From Bank': 'from_bank',
    'To Bank': 'to_bank',
    'Timestamp': 'timestamp',
    'Step': 'timestamp'
})

trans_df['amount'] = pd.to_numeric(trans_df['amount'], errors='coerce')
trans_df['is_laundering'] = trans_df['is_laundering'].fillna(0).astype(int)
trans_df['from_account'] = trans_df['from_account'].astype(str)
trans_df['to_account'] = trans_df['to_account'].astype(str)

print(f"Total transactions loaded: {len(trans_df):,}")

# ====================== SMART SAMPLING ======================
print("Performing smart sampling around laundering transactions...")
laundering = trans_df[trans_df['is_laundering'] == 1]
normal = trans_df[trans_df['is_laundering'] == 0]

laundering_accounts = pd.concat([laundering['from_account'], laundering['to_account']]).unique()

extra_normal = normal.sample(
    n=min(SAMPLE_ACCOUNTS - len(laundering_accounts), len(normal)), 
    random_state=42
)['from_account'].unique()

selected_accounts = set(laundering_accounts) | set(extra_normal)

mask = trans_df['from_account'].isin(selected_accounts) | trans_df['to_account'].isin(selected_accounts)
sampled_trans_df = trans_df[mask].copy()

print(f"→ Using {len(selected_accounts):,} accounts and {len(sampled_trans_df):,} transactions")

# ====================== NEO4J SETUP ======================
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

with driver.session() as session:
    # Create constraint
    session.run("""
        CREATE CONSTRAINT account_id_idx IF NOT EXISTS 
        FOR (a:Account) REQUIRE a.id IS UNIQUE
    """)
    print("✅ Uniqueness constraint created")

    # Clear previous data (safe during development)
    session.run("MATCH (n) DETACH DELETE n")
    print("✅ Previous database cleared")

# ====================== IMPORT FUNCTION ======================
def import_batch(tx, batch):
    query = """
    UNWIND $batch AS row
    MERGE (from:Account {id: row.from_account})
    MERGE (to:Account {id: row.to_account})
    CREATE (from)-[r:TRANSFER {
        amount: row.amount,
        timestamp: row.timestamp,
        currency: row.currency,
        payment_format: row.payment_format,
        is_laundering: row.is_laundering,
        from_bank: row.from_bank,
        to_bank: row.to_bank
    }]->(to)
    """
    tx.run(query, batch=batch)

# ====================== IMPORT TRANSACTIONS ======================
print("Importing transactions into Neo4j...")
batch = []
with driver.session() as session:
    for _, row in tqdm(sampled_trans_df.iterrows(), total=len(sampled_trans_df), desc="Importing"):
        batch.append({
            "from_account": row['from_account'],
            "to_account": row['to_account'],
            "amount": float(row['amount']),
            "timestamp": str(row.get('timestamp', '')),
            "currency": str(row.get('currency', 'USD')),
            "payment_format": str(row.get('payment_format', '')),
            "is_laundering": int(row['is_laundering']),
            "from_bank": str(row.get('from_bank', '')),
            "to_bank": str(row.get('to_bank', ''))
        })
        if len(batch) >= 4000:          # Smaller batch size for your 8GB RAM
            session.execute_write(import_batch, batch)
            batch = []
    if batch:
        session.execute_write(import_batch, batch)

print("\n🎉 NEO4J SETUP COMPLETED SUCCESSFULLY!")
print(f"   • Accounts used     : {len(selected_accounts):,}")
print(f"   • Transactions loaded: {len(sampled_trans_df):,}")

# Final stats
with driver.session() as session:
    total = session.run("MATCH ()-[r:TRANSFER]->() RETURN count(r) as cnt").single()['cnt']
    laundering = session.run("MATCH ()-[r:TRANSFER]->() WHERE r.is_laundering = 1 RETURN count(r) as cnt").single()['cnt']
    print(f"   • Total relationships in Neo4j : {total:,}")
    print(f"   • Laundering relationships     : {laundering:,}")

driver.close()
print("\nYou can now run Cypher queries in Neo4j Browser.")