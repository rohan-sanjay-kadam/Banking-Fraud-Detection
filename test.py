import pandas as pd
acc = pd.read_csv("data/HI-Small_Accounts.csv")
print(acc.columns.tolist())
print(acc.head(2))