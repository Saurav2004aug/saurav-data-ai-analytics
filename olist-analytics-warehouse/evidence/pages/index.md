---
title: Olist Marketplace - Executive Overview
---

```sql kpis
select * from olist.monthly_kpis where orders >= 50 order by order_month
```

```sql last_month
select * from olist.monthly_kpis order by order_month desc limit 1
```

<BigValue data={last_month} value=revenue title="Revenue (last month)" fmt=num0 comparison=revenue_mom_growth comparisonFmt=pct1 comparisonTitle="vs prior month"/>
<BigValue data={last_month} value=valid_orders title="Orders" fmt=num0/>
<BigValue data={last_month} value=avg_order_value title="Avg order value" fmt=num2/>
<BigValue data={last_month} value=late_delivery_rate title="Late deliveries" fmt=pct1/>
<BigValue data={last_month} value=avg_review_score title="Avg review" fmt=num2/>

## Revenue
<LineChart data={kpis} x=order_month y=revenue yFmt=num0 title="Monthly revenue (BRL)"/>

## New vs returning customers
<BarChart data={kpis} x=order_month y={["new_customers","returning_customers"]} type=stacked title="Active customers per month"/>

## Service level
<LineChart data={kpis} x=order_month y=late_delivery_rate yFmt=pct1 title="Late-delivery rate"/>

```sql categories
select category, revenue, revenue_share, avg_review_score, late_delivery_rate
from olist.category_performance order by revenue desc limit 15
```

## Top categories
<DataTable data={categories}>
  <Column id=category/>
  <Column id=revenue fmt=num0 contentType=bar/>
  <Column id=revenue_share fmt=pct1/>
  <Column id=avg_review_score fmt=num2/>
  <Column id=late_delivery_rate fmt=pct1/>
</DataTable>
