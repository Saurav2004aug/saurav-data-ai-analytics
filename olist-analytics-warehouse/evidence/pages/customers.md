---
title: Customers - Retention & Segments
---

```sql cohorts
select cohort_month, months_since_first, retention_rate
from olist.cohort_retention
where months_since_first between 1 and 6 and cohort_customers >= 100
```

## Repeat-purchase retention by cohort
<Heatmap data={cohorts} x=months_since_first y=cohort_month value=retention_rate valueFmt=pct2/>

```sql segments
select segment, count(*) as customers, sum(monetary) as revenue, avg(recency_days) as avg_recency_days
from olist.customer_rfm group by segment order by revenue desc
```

## RFM segments
<BarChart data={segments} x=segment y=revenue swapXY=true yFmt=num0 title="Revenue by segment"/>
<DataTable data={segments}/>
