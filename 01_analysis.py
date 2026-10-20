"""
E-Commerce Sales Performance Analysis
-------------------------------------
Dataset : Online Retail / E-Commerce Data (Kaggle, 541,909 rows)
          columns: InvoiceNo, StockCode, Description, Quantity,
                   InvoiceDate, UnitPrice, CustomerID, Country
Run     : python 01_analysis.py data.csv
Output  : output/  (clean CSVs for Power BI, charts, SQLite DB, summary)
"""
import os
import sqlite3
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

DATA = sys.argv[1] if len(sys.argv) > 1 else "data.csv"
OUT = "output"
CH = f"{OUT}/charts"
os.makedirs(CH, exist_ok=True)
sns.set_theme(style="whitegrid")
summary = []  # key numbers for interview


def log(msg):
    print(msg)
    summary.append(msg)


# ------------------------------------------------------------------
# 1. LOAD
# ------------------------------------------------------------------
df = pd.read_csv(DATA, encoding="ISO-8859-1")
df.columns = [c.strip() for c in df.columns]
df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
log(f"Raw rows: {len(df):,}")

# ------------------------------------------------------------------
# 2. CLEANING  (har step ka count log hota hai -> interview mein bolne ke liye)
# ------------------------------------------------------------------
n0 = len(df)
df = df.drop_duplicates()
log(f"Duplicates removed: {n0 - len(df):,}")

df["InvoiceNo"] = df["InvoiceNo"].astype(str)
df["StockCode"] = df["StockCode"].astype(str)
df["IsCancel"] = df["InvoiceNo"].str.startswith("C")

# Cancellations / returns alag rakhte hain (return analysis ke liye)
returns = df[df["IsCancel"]].copy()
sales = df[~df["IsCancel"]].copy()
log(f"Cancelled/return rows set aside: {len(returns):,}")

# Invalid quantity / price
n1 = len(sales)
sales = sales[(sales["Quantity"] > 0) & (sales["UnitPrice"] > 0)]
log(f"Rows with qty<=0 or price<=0 removed: {n1 - len(sales):,}")

# Non-product codes (POST, DOT, M, BANK CHARGES, etc.) - product codes 5 digit se start hote hain
n2 = len(sales)
sales = sales[sales["StockCode"].str.match(r"^\d{5}")]
log(f"Non-product rows (postage, fees, manual) removed: {n2 - len(sales):,}")

sales["Description"] = sales["Description"].fillna("UNKNOWN").str.strip().str.upper()
sales["Revenue"] = sales["Quantity"] * sales["UnitPrice"]
gross_rev_before_netting = sales["Revenue"].sum()

# ---- NETTING: pura cancel ho chuke orders hatao ----
# Agar kisi customer ne same product, same quantity cancel kiya hai, to wo original sale
# asli revenue nahi hai (jaise 80,995 units ka order jo usi din cancel ho gaya).
# Match key = CustomerID + StockCode + Quantity (sirf known customers ke liye).
ret_known = returns.dropna(subset=["CustomerID"]).copy()
ret_known["key"] = (ret_known["CustomerID"].astype(int).astype(str) + "|"
                    + ret_known["StockCode"] + "|" + ret_known["Quantity"].abs().astype(str))
cancel_counts = ret_known.groupby("key").size()

sales["key"] = (sales["CustomerID"].astype("Int64").astype(str) + "|"
                + sales["StockCode"] + "|" + sales["Quantity"].astype(str))
sales = sales.sort_values("InvoiceDate")
# har key ke andar latest sale ko rank 0 do
sales["rank_from_latest"] = sales.groupby("key").cumcount(ascending=False)
sales["n_cancel"] = sales["key"].map(cancel_counts).fillna(0)
reversed_mask = (sales["rank_from_latest"] < sales["n_cancel"]) & sales["CustomerID"].notna()
log(f"Fully-cancelled sale rows netted out: {reversed_mask.sum():,} "
    f"(value {sales.loc[reversed_mask, 'Revenue'].sum():,.0f})")
sales = sales[~reversed_mask].drop(columns=["key", "rank_from_latest", "n_cancel"])

# Outlier cap (sirf extreme 0.1% - wholesale buyers ko delete nahi karte)
cap = sales["Revenue"].quantile(0.999)
log(f"99.9th percentile line revenue: {cap:,.1f} (outliers flagged, not deleted)")
sales["IsOutlier"] = sales["Revenue"] > cap

# Time features
sales["Month"] = sales["InvoiceDate"].dt.to_period("M").astype(str)
sales["Year"] = sales["InvoiceDate"].dt.year
sales["MonthNum"] = sales["InvoiceDate"].dt.month
sales["DayOfWeek"] = sales["InvoiceDate"].dt.day_name()
sales["Hour"] = sales["InvoiceDate"].dt.hour

missing_cust = sales["CustomerID"].isna().mean()
log(f"Missing CustomerID share: {missing_cust:.1%} (sales analysis mein rakha, RFM/cohort se bahar)")
sales["CustomerID"] = sales["CustomerID"].astype("Int64")

log(f"Clean sales rows: {len(sales):,} | Customers: {sales['CustomerID'].nunique():,} "
    f"| Invoices: {sales['InvoiceNo'].nunique():,} | Products: {sales['StockCode'].nunique():,}")
log(f"Period: {sales['InvoiceDate'].min():%Y-%m-%d} to {sales['InvoiceDate'].max():%Y-%m-%d}")

total_rev = sales["Revenue"].sum()
log(f"Total revenue: {total_rev:,.0f}")

# ------------------------------------------------------------------
# 3. SALES ANALYSIS
# ------------------------------------------------------------------
# 3a. Monthly trend
monthly = (sales.groupby("Month")
           .agg(Revenue=("Revenue", "sum"),
                Orders=("InvoiceNo", "nunique"),
                Customers=("CustomerID", "nunique"))
           .reset_index())
monthly["AOV"] = monthly["Revenue"] / monthly["Orders"]
monthly["MoM_Growth_%"] = monthly["Revenue"].pct_change() * 100
monthly.to_csv(f"{OUT}/monthly_sales.csv", index=False)

fig, ax = plt.subplots(figsize=(11, 4.5))
ax.plot(monthly["Month"], monthly["Revenue"], marker="o")
ax.set_title("Monthly Revenue Trend")
ax.set_ylabel("Revenue")
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(f"{CH}/01_monthly_revenue.png", dpi=150)
plt.close()

peak = monthly.loc[monthly["Revenue"].idxmax()]
log(f"Peak month: {peak['Month']} (revenue {peak['Revenue']:,.0f})")

# 3b. Seasonality (month-of-year, sirf poore saal wale months compare karne ke liye average)
season = sales.groupby("MonthNum")["Revenue"].sum().reset_index()
season["Share_%"] = season["Revenue"] / season["Revenue"].sum() * 100
season.to_csv(f"{OUT}/seasonality.csv", index=False)
q4 = season[season["MonthNum"].isin([10, 11, 12])]["Share_%"].sum()
log(f"Oct-Dec (Q4) share of revenue: {q4:.1f}%")

# 3c. Day of week / hour
dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
dow = sales.groupby("DayOfWeek")["Revenue"].sum().reindex(dow_order).fillna(0)
hour = sales.groupby("Hour")["Revenue"].sum()
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
dow.plot(kind="bar", ax=axes[0], title="Revenue by Day of Week")
hour.plot(kind="bar", ax=axes[1], title="Revenue by Hour")
plt.tight_layout()
plt.savefig(f"{CH}/02_dow_hour.png", dpi=150)
plt.close()

# 3d. Top products
top_prod_rev = (sales.groupby(["StockCode", "Description"])
                .agg(Revenue=("Revenue", "sum"), Units=("Quantity", "sum"))
                .sort_values("Revenue", ascending=False).reset_index())
top_prod_rev.to_csv(f"{OUT}/product_performance.csv", index=False)
top10 = top_prod_rev.head(10)
fig, ax = plt.subplots(figsize=(10, 5))
sns.barplot(data=top10, y="Description", x="Revenue", ax=ax)
ax.set_title("Top 10 Products by Revenue")
plt.tight_layout()
plt.savefig(f"{CH}/03_top_products.png", dpi=150)
plt.close()
log(f"Top product: {top10.iloc[0]['Description']} ({top10.iloc[0]['Revenue']:,.0f})")

# Pareto: top 20% products kitna revenue dete hain
p = top_prod_rev["Revenue"].values
k = max(1, int(len(p) * 0.2))
log(f"Top 20% products contribute {p[:k].sum() / p.sum():.1%} of revenue")

# 3e. Country
country = (sales.groupby("Country")
           .agg(Revenue=("Revenue", "sum"), Customers=("CustomerID", "nunique"),
                Orders=("InvoiceNo", "nunique"))
           .sort_values("Revenue", ascending=False).reset_index())
country["Share_%"] = country["Revenue"] / country["Revenue"].sum() * 100
country.to_csv(f"{OUT}/country_sales.csv", index=False)
log(f"Top country: {country.iloc[0]['Country']} ({country.iloc[0]['Share_%']:.1f}% of revenue)")

# 3f. Returns (profitability ka proxy - dataset mein cost nahi hai)
ret_val = (returns["Quantity"] * returns["UnitPrice"]).abs().sum()
log(f"Return value / gross revenue: {ret_val / gross_rev_before_netting:.1%}")
ret_prod = (returns.assign(Val=(returns["Quantity"] * returns["UnitPrice"]).abs())
            .groupby("Description")["Val"].sum().sort_values(ascending=False).head(10))
ret_prod.to_csv(f"{OUT}/top_returned_products.csv")

# ------------------------------------------------------------------
# 4. RFM SEGMENTATION (sirf known customers)
# ------------------------------------------------------------------
cust = sales.dropna(subset=["CustomerID"]).copy()
snapshot = cust["InvoiceDate"].max() + pd.Timedelta(days=1)
rfm = (cust.groupby("CustomerID")
       .agg(Recency=("InvoiceDate", lambda x: (snapshot - x.max()).days),
            Frequency=("InvoiceNo", "nunique"),
            Monetary=("Revenue", "sum"))
       .reset_index())

# Scores 1-5 (5 = best). Frequency mein rank(first) taaki qcut duplicates par na toote
rfm["R"] = pd.qcut(rfm["Recency"], 5, labels=[5, 4, 3, 2, 1]).astype(int)
rfm["F"] = pd.qcut(rfm["Frequency"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
rfm["M"] = pd.qcut(rfm["Monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
rfm["RFM_Score"] = rfm["R"].astype(str) + rfm["F"].astype(str) + rfm["M"].astype(str)


def segment(r):
    if r["R"] >= 4 and r["F"] >= 4:
        return "Champions"
    if r["R"] >= 3 and r["F"] >= 3:
        return "Loyal Customers"
    if r["R"] >= 4 and r["F"] <= 2:
        return "New / Promising"
    if r["R"] == 3 and r["F"] <= 2:
        return "Need Attention"
    if r["R"] <= 2 and r["F"] >= 4:
        return "Cant Lose Them"
    if r["R"] <= 2 and r["F"] >= 2:
        return "At Risk"
    return "Lost / Hibernating"


rfm["Segment"] = rfm.apply(segment, axis=1)
rfm.to_csv(f"{OUT}/rfm_customers.csv", index=False)

seg = (rfm.groupby("Segment")
       .agg(Customers=("CustomerID", "count"), Revenue=("Monetary", "sum"),
            Avg_Recency=("Recency", "mean"), Avg_Frequency=("Frequency", "mean"))
       .sort_values("Revenue", ascending=False).reset_index())
seg["Customer_%"] = seg["Customers"] / seg["Customers"].sum() * 100
seg["Revenue_%"] = seg["Revenue"] / seg["Revenue"].sum() * 100
seg.to_csv(f"{OUT}/rfm_segments_summary.csv", index=False)
print(seg.round(1).to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
sns.barplot(data=seg, y="Segment", x="Customers", ax=axes[0])
axes[0].set_title("Customers per Segment")
sns.barplot(data=seg, y="Segment", x="Revenue", ax=axes[1])
axes[1].set_title("Revenue per Segment")
plt.tight_layout()
plt.savefig(f"{CH}/04_rfm_segments.png", dpi=150)
plt.close()

champ = seg[seg["Segment"] == "Champions"]
if len(champ):
    c = champ.iloc[0]
    log(f"Champions: {c['Customer_%']:.1f}% of customers -> {c['Revenue_%']:.1f}% of revenue")

# Customer concentration
cs = rfm["Monetary"].sort_values(ascending=False).values
k = max(1, int(len(cs) * 0.2))
log(f"Top 20% customers contribute {cs[:k].sum() / cs.sum():.1%} of known-customer revenue")

# Repeat purchase rate
log(f"Repeat customers (2+ orders): {(rfm['Frequency'] > 1).mean():.1%}")

# ------------------------------------------------------------------
# 5. COHORT ANALYSIS (monthly retention)
# ------------------------------------------------------------------
cust["OrderMonth"] = cust["InvoiceDate"].dt.to_period("M")
cust["CohortMonth"] = cust.groupby("CustomerID")["InvoiceDate"].transform("min").dt.to_period("M")
cust["CohortIndex"] = ((cust["OrderMonth"].dt.year - cust["CohortMonth"].dt.year) * 12
                       + (cust["OrderMonth"].dt.month - cust["CohortMonth"].dt.month))

cohort_counts = (cust.groupby(["CohortMonth", "CohortIndex"])["CustomerID"]
                 .nunique().reset_index()
                 .pivot(index="CohortMonth", columns="CohortIndex", values="CustomerID"))
cohort_size = cohort_counts[0]
retention = cohort_counts.divide(cohort_size, axis=0) * 100
retention.index = retention.index.astype(str)
retention.round(1).to_csv(f"{OUT}/cohort_retention_matrix.csv")

# Long format - Power BI ke liye
ret_long = retention.reset_index().melt(id_vars="CohortMonth", var_name="MonthsSinceFirst",
                                        value_name="Retention_%").dropna()
ret_long.to_csv(f"{OUT}/cohort_retention_long.csv", index=False)

fig, ax = plt.subplots(figsize=(13, 7))
sns.heatmap(retention.round(0), annot=True, fmt=".0f", cmap="YlGnBu", ax=ax,
            cbar_kws={"label": "Retention %"})
ax.set_title("Monthly Cohort Retention (%)")
plt.tight_layout()
plt.savefig(f"{CH}/05_cohort_retention.png", dpi=150)
plt.close()

m1 = retention[1].mean() if 1 in retention.columns else float("nan")
m3 = retention[3].mean() if 3 in retention.columns else float("nan")
log(f"Avg Month-1 retention: {m1:.1f}% | Avg Month-3 retention: {m3:.1f}%")

# ------------------------------------------------------------------
# 6. EXPORT for Power BI + SQL
# ------------------------------------------------------------------
cols = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice",
        "CustomerID", "Country", "Revenue", "Month", "Year", "MonthNum", "DayOfWeek", "Hour"]
sales[cols].to_csv(f"{OUT}/clean_transactions.csv", index=False)

con = sqlite3.connect(f"{OUT}/ecommerce.db")
sales[cols].assign(InvoiceDate=sales["InvoiceDate"].astype(str)).to_sql(
    "transactions", con, if_exists="replace", index=False)
rfm.to_sql("rfm", con, if_exists="replace", index=False)
con.close()

with open(f"{OUT}/key_numbers_summary.txt", "w") as f:
    f.write("\n".join(summary))
print("\nDone. 'output/' folder check karo.")
