-- =====================================================================
-- E-Commerce Sales Analysis - SQL (SQLite syntax; MySQL/Postgres mein
-- strftime() ko DATE_FORMAT()/TO_CHAR() se badal dena)
-- Tables: transactions (clean data), rfm (01_analysis.py ne banayi)
-- DB Browser for SQLite se output/ecommerce.db open karo, ya Python se run karo.
-- =====================================================================

-- 1. KPI overview
SELECT ROUND(SUM(Revenue),0)              AS total_revenue,
       COUNT(DISTINCT InvoiceNo)          AS total_orders,
       COUNT(DISTINCT CustomerID)         AS total_customers,
       ROUND(SUM(Revenue)/COUNT(DISTINCT InvoiceNo),2) AS avg_order_value
FROM transactions;

-- 2. Monthly revenue + MoM growth (window function: LAG)
WITH m AS (
  SELECT Month, SUM(Revenue) AS revenue
  FROM transactions GROUP BY Month
)
SELECT Month, ROUND(revenue,0) AS revenue,
       ROUND((revenue - LAG(revenue) OVER (ORDER BY Month)) * 100.0
             / LAG(revenue) OVER (ORDER BY Month), 1) AS mom_growth_pct
FROM m ORDER BY Month;

-- 3. Top 10 products by revenue
SELECT StockCode, Description, ROUND(SUM(Revenue),0) AS revenue, SUM(Quantity) AS units
FROM transactions GROUP BY StockCode, Description
ORDER BY revenue DESC LIMIT 10;

-- 4. Revenue share by country (window SUM)
SELECT Country, ROUND(SUM(Revenue),0) AS revenue,
       ROUND(SUM(Revenue)*100.0 / SUM(SUM(Revenue)) OVER (), 1) AS share_pct
FROM transactions GROUP BY Country ORDER BY revenue DESC;

-- 5. Top 3 products in every country (RANK + PARTITION)
SELECT * FROM (
  SELECT Country, Description, ROUND(SUM(Revenue),0) AS revenue,
         RANK() OVER (PARTITION BY Country ORDER BY SUM(Revenue) DESC) AS rnk
  FROM transactions GROUP BY Country, Description
) WHERE rnk <= 3;

-- 6. Seasonality: month-of-year share
SELECT MonthNum, ROUND(SUM(Revenue)*100.0/(SELECT SUM(Revenue) FROM transactions),1) AS pct_of_revenue
FROM transactions GROUP BY MonthNum ORDER BY MonthNum;

-- 7. Pareto: top 20% customers ka revenue share
WITH c AS (
  SELECT CustomerID, SUM(Revenue) AS rev,
         NTILE(5) OVER (ORDER BY SUM(Revenue) DESC) AS quintile
  FROM transactions WHERE CustomerID IS NOT NULL GROUP BY CustomerID
)
SELECT quintile, COUNT(*) AS customers, ROUND(SUM(rev)*100.0/(SELECT SUM(rev) FROM c),1) AS revenue_pct
FROM c GROUP BY quintile ORDER BY quintile;

-- 8. RFM segment summary (rfm table se)
SELECT Segment, COUNT(*) AS customers, ROUND(SUM(Monetary),0) AS revenue,
       ROUND(AVG(Recency),0) AS avg_recency
FROM rfm GROUP BY Segment ORDER BY revenue DESC;

-- 9. Cohort retention in pure SQL
WITH first_purchase AS (
  SELECT CustomerID, MIN(substr(InvoiceDate,1,7)) AS cohort_month
  FROM transactions WHERE CustomerID IS NOT NULL GROUP BY CustomerID
),
activity AS (
  SELECT DISTINCT t.CustomerID, f.cohort_month, substr(t.InvoiceDate,1,7) AS order_month
  FROM transactions t JOIN first_purchase f USING (CustomerID)
),
idx AS (
  SELECT cohort_month,
         (CAST(substr(order_month,1,4) AS INT)*12 + CAST(substr(order_month,6,2) AS INT))
       - (CAST(substr(cohort_month,1,4) AS INT)*12 + CAST(substr(cohort_month,6,2) AS INT)) AS month_index,
         CustomerID
  FROM activity
)
SELECT cohort_month, month_index, COUNT(DISTINCT CustomerID) AS active_customers,
       ROUND(COUNT(DISTINCT CustomerID)*100.0 /
             FIRST_VALUE(COUNT(DISTINCT CustomerID)) OVER (PARTITION BY cohort_month ORDER BY month_index), 1) AS retention_pct
FROM idx GROUP BY cohort_month, month_index ORDER BY cohort_month, month_index;

-- 10. Customers jo 90+ din se inactive hain par high value the (win-back list)
SELECT CustomerID, Recency, Frequency, ROUND(Monetary,0) AS monetary
FROM rfm WHERE Segment IN ('Cant Lose Them','At Risk')
ORDER BY Monetary DESC LIMIT 50;
